package handlers

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"

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
// the provider interface, WhatsApp via the Meta Cloud API when configured
// (otherwise stored as queued), and in-app stored for the hub timeline.
//
// A delivery failure is returned to the caller (message.status == "failed" plus
// an "error" explaining why) rather than being swallowed, so the UI can tell the
// user their message did not go out.
func (s *Server) SendMessage(c *gin.Context) {
	var in struct {
		ClientID *string `json:"client_id"`
		FileID   *string `json:"file_id"`
		Channel  string  `json:"channel" binding:"required,oneof=sms email whatsapp inapp"`
		To       string  `json:"to"`
		Subject  string  `json:"subject"`
		Body     string  `json:"body" binding:"required"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	in.To = strings.TrimSpace(in.To)

	// No explicit recipient: fall back to the linked client's contact details
	// (only if they have consented to communications under the KDPA).
	if in.To == "" && in.ClientID != nil && *in.ClientID != "" && in.Channel != "inapp" {
		ok := s.withTenant(c, func(tx pgx.Tx) error {
			cl, err := repository.ClientByID(c.Request.Context(), tx, *in.ClientID)
			if err == pgx.ErrNoRows {
				badRequest(c, "client not found")
				return errHandled
			}
			if err != nil {
				return err
			}
			if !cl.KDPAConsent {
				c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "client has not consented to communications (KDPA)"})
				return errHandled
			}
			if in.Channel == "email" {
				in.To = cl.Email
			} else {
				in.To = cl.Phone
			}
			return nil
		})
		if !ok {
			return
		}
	}

	ctx := c.Request.Context()
	status, providerRef, failure := "sent", "", ""
	switch in.Channel {
	case "sms":
		if in.To == "" {
			badRequest(c, "sms requires a phone number ('to')")
			return
		}
		res, err := s.SMS.Send(ctx, in.To, in.Body)
		if err != nil {
			status, failure = "failed", err.Error()
		} else {
			status, providerRef = res.Status, res.MessageID
		}
	case "email":
		if in.To == "" {
			badRequest(c, "email requires an address ('to')")
			return
		}
		if err := s.Mail.Send(ctx, in.To, in.Subject, in.Body); err != nil {
			status, failure = "failed", err.Error()
		}
	case "whatsapp":
		if in.To == "" {
			badRequest(c, "whatsapp requires a phone number ('to')")
			return
		}
		if s.WA.Enabled() {
			if err := s.WA.Send(ctx, in.To, in.Body); err != nil {
				status, failure = "failed", err.Error()
			}
		} else {
			// Not configured: keep it in the hub timeline as queued.
			status = "queued"
		}
	case "inapp":
		status = "delivered"
	}
	if failure != "" {
		logging.L(ctx).Warn("message send failed", "channel", in.Channel, "err", failure)
	}
	m := &repository.Message{
		ID: uuid.NewString(), FileID: in.FileID, ClientID: in.ClientID,
		Channel: in.Channel, Direction: "outbound", ToAddr: in.To, FromAddr: "firm",
		Body: in.Body, Status: status, ProviderRef: providerRef,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertMessage(ctx, tx, m)
	}) {
		resp := gin.H{"message": m}
		if failure != "" {
			resp["error"] = failure
		}
		c.JSON(http.StatusCreated, resp)
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
