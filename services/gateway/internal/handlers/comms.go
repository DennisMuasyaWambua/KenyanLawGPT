package handlers

import (
	"encoding/json"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/integrations/mpesa"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/repository"
)

func (s *Server) ListMessages(c *gin.Context) {
	var msgs []repository.Message
	if s.withTenant(c, func(tx pgx.Tx) error {
		m, err := repository.ListMessages(c.Request.Context(), tx, c.Query("client_id"), c.Query("channel"))
		msgs = m
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"messages": msgs})
	}
}

// SendMessage handles the unified outbox: SMS via Africa's Talking, email via
// the provider interface, and whatsapp/inapp stored for the hub timeline.
func (s *Server) SendMessage(c *gin.Context) {
	var in struct {
		ClientID *string `json:"client_id"`
		FileID *string `json:"file_id"`
		Channel  string  `json:"channel" binding:"required,oneof=sms email whatsapp inapp"`
		To       string  `json:"to"`
		Subject  string  `json:"subject"`
		Body     string  `json:"body" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	status, providerRef := "sent", ""
	switch in.Channel {
	case "sms":
		if in.To == "" {
			badRequest(c, "sms requires 'to'")
			return
		}
		res, err := s.SMS.Send(c.Request.Context(), in.To, in.Body)
		if err != nil {
			status = "failed"
		} else {
			status, providerRef = res.Status, res.MessageID
		}
	case "email":
		if in.To == "" {
			badRequest(c, "email requires 'to'")
			return
		}
		if err := s.Mail.Send(c.Request.Context(), in.To, in.Subject, in.Body); err != nil {
			status = "failed"
		}
	case "whatsapp":
		// Stored in the hub; delivery integration is a provider swap away.
		status = "queued"
	case "inapp":
		status = "delivered"
	}
	m := &repository.Message{
		ID: uuid.NewString(), FileID: in.FileID, ClientID: in.ClientID,
		Channel: in.Channel, Direction: "outbound", ToAddr: in.To, FromAddr: "firm",
		Body: in.Body, Status: status, ProviderRef: providerRef,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertMessage(c.Request.Context(), tx, m)
	}) {
		c.JSON(http.StatusCreated, gin.H{"message": m})
	}
}

func (s *Server) ListNotifications(c *gin.Context) {
	userID := s.claims(c).UserID()
	var notifs []repository.Notification
	if s.withTenant(c, func(tx pgx.Tx) error {
		n, err := repository.ListNotifications(c.Request.Context(), tx, userID)
		notifs = n
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"notifications": notifs})
	}
}

// --- Webhooks (no auth; validated by shape + idempotent processing) ---

// DarajaCallback settles the payment exactly once. The tenant slug travels in
// the callback URL query (?tenant=<slug>) set at STK-push time.
func (s *Server) DarajaCallback(c *gin.Context) {
	slug := c.Query("tenant")
	body, err := io.ReadAll(io.LimitReader(c.Request.Body, 1<<20))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "read body"})
		return
	}
	var env mpesa.CallbackEnvelope
	if err := json.Unmarshal(body, &env); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "bad payload"})
		return
	}
	cb := env.Body.StkCallback
	if cb.CheckoutRequestID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing CheckoutRequestID"})
		return
	}
	status := "failed"
	if cb.ResultCode == 0 {
		status = "success"
	}

	settle := func(t repository.Tenant) (bool, error) {
		var matched bool
		err := s.DB.WithTenant(c.Request.Context(), t.ID, t.SchemaName, func(tx pgx.Tx) error {
			invoiceID, settled, err := repository.SettlePayment(c.Request.Context(), tx, cb.CheckoutRequestID, status, env.Receipt(), body)
			if err != nil {
				return err
			}
			// settled==false can mean "already processed" (idempotent) or "not
			// this tenant"; distinguish by row existence.
			if !settled {
				var exists bool
				if err := tx.QueryRow(c.Request.Context(),
					"SELECT EXISTS(SELECT 1 FROM payments WHERE checkout_request_id=$1)", cb.CheckoutRequestID).Scan(&exists); err != nil {
					return err
				}
				matched = exists
				return nil
			}
			matched = true
			if status == "success" {
				return repository.MarkInvoicePaid(c.Request.Context(), tx, invoiceID)
			}
			return nil
		})
		return matched, err
	}

	if slug != "" {
		if t, err := repository.TenantBySlug(c.Request.Context(), s.DB.Pool, slug); err == nil {
			if _, err := settle(*t); err != nil {
				logging.L(c.Request.Context()).Error("daraja settle", "err", err)
			}
			c.JSON(http.StatusOK, gin.H{"ResultCode": 0, "ResultDesc": "Accepted"})
			return
		}
	}
	// Fallback: scan tenants (checkout ids are globally unique).
	tenants, err := repository.ListActiveTenants(c.Request.Context(), s.DB.Pool)
	if err == nil {
		for _, t := range tenants {
			if matched, err := settle(t); err == nil && matched {
				break
			}
		}
	}
	c.JSON(http.StatusOK, gin.H{"ResultCode": 0, "ResultDesc": "Accepted"})
}

// ATDelivery handles Africa's Talking delivery reports (form-encoded id +
// status) and updates the matching outbound message row.
func (s *Server) ATDelivery(c *gin.Context) {
	providerRef := c.PostForm("id")
	status := c.PostForm("status")
	if providerRef == "" || status == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing id/status"})
		return
	}
	normalized := map[string]string{
		"Success": "delivered", "Sent": "sent", "Buffered": "sent",
		"Rejected": "failed", "Failed": "failed",
	}[status]
	if normalized == "" {
		normalized = "sent"
	}
	tenants, err := repository.ListActiveTenants(c.Request.Context(), s.DB.Pool)
	if err != nil {
		c.Status(http.StatusOK)
		return
	}
	for _, t := range tenants {
		var updated bool
		err := s.DB.WithTenant(c.Request.Context(), t.ID, t.SchemaName, func(tx pgx.Tx) error {
			ok, err := repository.UpdateMessageStatusByRef(c.Request.Context(), tx, providerRef, normalized)
			updated = ok
			return err
		})
		if err == nil && updated {
			break
		}
	}
	c.Status(http.StatusOK)
}
