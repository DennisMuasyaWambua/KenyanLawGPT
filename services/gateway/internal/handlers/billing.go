package handlers

import (
	"math"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/repository"
)

const vatRate = 0.16 // Kenyan VAT on legal services

func (s *Server) CreateTimeEntry(c *gin.Context) {
	var in struct {
		FileID    string  `json:"file_id" binding:"required"`
		Description string  `json:"description" binding:"required"`
		Minutes     int     `json:"minutes" binding:"required,min=1"`
		RateKES     float64 `json:"rate_kes" binding:"required"`
		EntryDate   string  `json:"entry_date"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	entryDate := time.Now()
	if in.EntryDate != "" {
		if d, err := time.Parse("2006-01-02", in.EntryDate); err == nil {
			entryDate = d
		}
	}
	t := &repository.TimeEntry{
		ID: uuid.NewString(), FileID: in.FileID, UserID: s.claims(c).UserID(),
		Description: in.Description, Minutes: in.Minutes, RateKES: in.RateKES, EntryDate: entryDate,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertTimeEntry(c.Request.Context(), tx, t)
	}) {
		c.JSON(http.StatusCreated, gin.H{"time_entry": t})
	}
}

func (s *Server) ListTimeEntries(c *gin.Context) {
	var entries []repository.TimeEntry
	if s.withTenant(c, func(tx pgx.Tx) error {
		e, err := repository.ListTimeEntries(c.Request.Context(), tx, c.Query("file_id"), c.Query("unbilled") == "true")
		entries = e
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"time_entries": entries})
	}
}

// CreateInvoice builds an invoice either from unbilled time entries for a
// file or from explicit line items.
func (s *Server) CreateInvoice(c *gin.Context) {
	var in struct {
		ClientID       string `json:"client_id" binding:"required"`
		FileID       *string `json:"file_id"`
		FromTimeEntries bool   `json:"from_time_entries"`
		DueDays        int     `json:"due_days"`
		Items          []struct {
			Description string  `json:"description"`
			Quantity    float64 `json:"quantity"`
			UnitKES     float64 `json:"unit_kes"`
		} `json:"items"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if in.DueDays <= 0 {
		in.DueDays = 30
	}
	var invoice *repository.Invoice
	if s.withTenant(c, func(tx pgx.Tx) error {
		number, err := repository.NextInvoiceNumber(c.Request.Context(), tx)
		if err != nil {
			return err
		}
		invID := uuid.NewString()
		var items []repository.InvoiceItem
		subtotal := 0.0
		if in.FromTimeEntries && in.FileID != nil {
			entries, err := repository.ListTimeEntries(c.Request.Context(), tx, *in.FileID, true)
			if err != nil {
				return err
			}
			for _, e := range entries {
				e := e
				amount := math.Round(float64(e.Minutes)/60.0*e.RateKES*100) / 100
				items = append(items, repository.InvoiceItem{
					ID: uuid.NewString(), InvoiceID: invID,
					Description: e.Description, Quantity: float64(e.Minutes) / 60.0,
					UnitKES: e.RateKES, AmountKES: amount, TimeEntryID: &e.ID,
				})
				subtotal += amount
			}
		}
		for _, it := range in.Items {
			amount := math.Round(it.Quantity*it.UnitKES*100) / 100
			items = append(items, repository.InvoiceItem{
				ID: uuid.NewString(), InvoiceID: invID,
				Description: it.Description, Quantity: it.Quantity, UnitKES: it.UnitKES, AmountKES: amount,
			})
			subtotal += amount
		}
		if len(items) == 0 {
			badRequest(c, "invoice has no line items")
			return errHandled
		}
		vat := math.Round(subtotal*vatRate*100) / 100
		due := time.Now().AddDate(0, 0, in.DueDays)
		invoice = &repository.Invoice{
			ID: invID, Number: number, FileID: in.FileID, ClientID: in.ClientID,
			Status: "sent", SubtotalKES: subtotal, VATKES: vat, TotalKES: subtotal + vat, DueAt: &due,
		}
		return repository.InsertInvoice(c.Request.Context(), tx, invoice, items)
	}) {
		c.JSON(http.StatusCreated, gin.H{"invoice": invoice})
	}
}

func (s *Server) ListInvoices(c *gin.Context) {
	var invoices []repository.Invoice
	if s.withTenant(c, func(tx pgx.Tx) error {
		i, err := repository.ListInvoices(c.Request.Context(), tx, c.Query("client_id"))
		invoices = i
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"invoices": invoices})
	}
}

func (s *Server) GetInvoice(c *gin.Context) {
	var invoice *repository.Invoice
	var items []repository.InvoiceItem
	var payments []repository.Payment
	if s.withTenant(c, func(tx pgx.Tx) error {
		inv, err := repository.InvoiceByID(c.Request.Context(), tx, c.Param("id"))
		if err != nil {
			return err
		}
		invoice = inv
		if items, err = repository.ListInvoiceItems(c.Request.Context(), tx, inv.ID); err != nil {
			return err
		}
		payments, err = repository.ListPayments(c.Request.Context(), tx, inv.ID)
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"invoice": invoice, "items": items, "payments": payments})
	}
}

// STKPush starts an M-Pesa payment for an invoice. The Daraja callback URL
// carries the tenant slug so the webhook can settle in the right schema.
func (s *Server) STKPush(c *gin.Context) {
	var in struct {
		Phone string `json:"phone" binding:"required"` // 2547XXXXXXXX
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if !s.Daraja.Configured() {
		c.JSON(http.StatusNotImplemented, gin.H{"error": "M-Pesa Daraja is not configured (set DARAJA_* env vars)"})
		return
	}
	tenant := s.tenant(c)
	var invoice *repository.Invoice
	if !s.withTenant(c, func(tx pgx.Tx) error {
		inv, err := repository.InvoiceByID(c.Request.Context(), tx, c.Param("id"))
		invoice = inv
		return err
	}) {
		return
	}
	if invoice.Status == "paid" {
		badRequest(c, "invoice already paid")
		return
	}
	amount := int64(math.Ceil(invoice.TotalKES))
	// Tenant slug rides on the callback URL so the webhook settles in the
	// right schema without trusting the payload.
	callback := s.Cfg.DarajaCallbackURL + "?tenant=" + tenant.Slug
	resp, err := s.Daraja.STKPush(c.Request.Context(), in.Phone, amount, invoice.Number, "C. Karwitha & Co. Advocates invoice "+invoice.Number, callback)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "daraja request failed", "detail": err.Error()})
		return
	}
	if resp.ResponseCode != "0" {
		c.JSON(http.StatusBadGateway, gin.H{"error": "daraja rejected request", "detail": resp.ResponseDescription})
		return
	}
	payment := &repository.Payment{
		ID: uuid.NewString(), InvoiceID: invoice.ID, Method: "mpesa_stk",
		CheckoutRequestID: resp.CheckoutRequestID, MerchantRequestID: resp.MerchantRequestID,
		Phone: in.Phone, AmountKES: float64(amount), Status: "pending",
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertPayment(c.Request.Context(), tx, payment)
	}) {
		c.JSON(http.StatusAccepted, gin.H{
			"payment":          payment,
			"customer_message": resp.CustomerMessage,
		})
	}
}
