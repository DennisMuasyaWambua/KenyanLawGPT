package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type TimeEntry struct {
	ID          string    `json:"id"`
	FileID    string    `json:"file_id"`
	UserID      string    `json:"user_id"`
	Description string    `json:"description"`
	Minutes     int       `json:"minutes"`
	RateKES     float64   `json:"rate_kes"` // hourly rate
	EntryDate   time.Time `json:"entry_date"`
	Billed      bool      `json:"billed"`
}

type Invoice struct {
	ID          string     `json:"id"`
	Number      string     `json:"number"`
	FileID    *string    `json:"file_id"`
	ClientID    string     `json:"client_id"`
	ClientName  string     `json:"client_name,omitempty"`
	Status      string     `json:"status"` // draft|sent|paid|void
	SubtotalKES float64    `json:"subtotal_kes"`
	VATKES      float64    `json:"vat_kes"`
	TotalKES    float64    `json:"total_kes"`
	IssuedAt    time.Time  `json:"issued_at"`
	DueAt       *time.Time `json:"due_at"`
	PaidAt      *time.Time `json:"paid_at"`
}

type InvoiceItem struct {
	ID          string  `json:"id"`
	InvoiceID   string  `json:"invoice_id"`
	Description string  `json:"description"`
	Quantity    float64 `json:"quantity"`
	UnitKES     float64 `json:"unit_kes"`
	AmountKES   float64 `json:"amount_kes"`
	TimeEntryID *string `json:"time_entry_id"`
}

type Payment struct {
	ID                string    `json:"id"`
	InvoiceID         string    `json:"invoice_id"`
	Method            string    `json:"method"` // mpesa_stk
	CheckoutRequestID string    `json:"checkout_request_id"`
	MerchantRequestID string    `json:"merchant_request_id"`
	MpesaReceipt      string    `json:"mpesa_receipt"`
	Phone             string    `json:"phone"`
	AmountKES         float64   `json:"amount_kes"`
	Status            string    `json:"status"` // pending|success|failed
	CreatedAt         time.Time `json:"created_at"`
}

func InsertTimeEntry(ctx context.Context, tx pgx.Tx, t *TimeEntry) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO time_entries (id, file_id, user_id, description, minutes, rate_kes, entry_date)
		 VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		t.ID, t.FileID, t.UserID, t.Description, t.Minutes, t.RateKES, t.EntryDate)
	return err
}

func ListTimeEntries(ctx context.Context, tx pgx.Tx, fileID string, unbilledOnly bool) ([]TimeEntry, error) {
	q := "SELECT id, file_id, user_id, description, minutes, rate_kes, entry_date, billed FROM time_entries WHERE 1=1"
	args := []any{}
	if fileID != "" {
		args = append(args, fileID)
		q += " AND file_id = $1"
	}
	if unbilledOnly {
		q += " AND NOT billed"
	}
	q += " ORDER BY entry_date DESC LIMIT 500"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []TimeEntry
	for rows.Next() {
		var t TimeEntry
		if err := rows.Scan(&t.ID, &t.FileID, &t.UserID, &t.Description, &t.Minutes, &t.RateKES, &t.EntryDate, &t.Billed); err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

func InsertInvoice(ctx context.Context, tx pgx.Tx, inv *Invoice, items []InvoiceItem) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO invoices (id, number, file_id, client_id, status, subtotal_kes, vat_kes, total_kes, due_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		inv.ID, inv.Number, inv.FileID, inv.ClientID, inv.Status, inv.SubtotalKES, inv.VATKES, inv.TotalKES, inv.DueAt)
	if err != nil {
		return err
	}
	for _, it := range items {
		if _, err := tx.Exec(ctx,
			`INSERT INTO invoice_items (id, invoice_id, description, quantity, unit_kes, amount_kes, time_entry_id)
			 VALUES ($1,$2,$3,$4,$5,$6,$7)`,
			it.ID, it.InvoiceID, it.Description, it.Quantity, it.UnitKES, it.AmountKES, it.TimeEntryID); err != nil {
			return err
		}
		if it.TimeEntryID != nil {
			if _, err := tx.Exec(ctx, "UPDATE time_entries SET billed = true WHERE id = $1", *it.TimeEntryID); err != nil {
				return err
			}
		}
	}
	return nil
}

const invoiceCols = `i.id, i.number, i.file_id, i.client_id, COALESCE(c.name,''), i.status,
	i.subtotal_kes, i.vat_kes, i.total_kes, i.issued_at, i.due_at, i.paid_at`

func scanInvoice(row pgx.Row) (*Invoice, error) {
	var i Invoice
	err := row.Scan(&i.ID, &i.Number, &i.FileID, &i.ClientID, &i.ClientName, &i.Status,
		&i.SubtotalKES, &i.VATKES, &i.TotalKES, &i.IssuedAt, &i.DueAt, &i.PaidAt)
	if err != nil {
		return nil, err
	}
	return &i, nil
}

func ListInvoices(ctx context.Context, tx pgx.Tx, clientID string) ([]Invoice, error) {
	q := "SELECT " + invoiceCols + " FROM invoices i LEFT JOIN clients c ON c.id = i.client_id"
	args := []any{}
	if clientID != "" {
		q += " WHERE i.client_id = $1"
		args = append(args, clientID)
	}
	q += " ORDER BY i.issued_at DESC LIMIT 200"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Invoice
	for rows.Next() {
		var i Invoice
		if err := rows.Scan(&i.ID, &i.Number, &i.FileID, &i.ClientID, &i.ClientName, &i.Status,
			&i.SubtotalKES, &i.VATKES, &i.TotalKES, &i.IssuedAt, &i.DueAt, &i.PaidAt); err != nil {
			return nil, err
		}
		out = append(out, i)
	}
	return out, rows.Err()
}

func InvoiceByID(ctx context.Context, tx pgx.Tx, id string) (*Invoice, error) {
	return scanInvoice(tx.QueryRow(ctx,
		"SELECT "+invoiceCols+" FROM invoices i LEFT JOIN clients c ON c.id = i.client_id WHERE i.id = $1", id))
}

func ListInvoiceItems(ctx context.Context, tx pgx.Tx, invoiceID string) ([]InvoiceItem, error) {
	rows, err := tx.Query(ctx,
		"SELECT id, invoice_id, description, quantity, unit_kes, amount_kes, time_entry_id FROM invoice_items WHERE invoice_id=$1",
		invoiceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []InvoiceItem
	for rows.Next() {
		var it InvoiceItem
		if err := rows.Scan(&it.ID, &it.InvoiceID, &it.Description, &it.Quantity, &it.UnitKES, &it.AmountKES, &it.TimeEntryID); err != nil {
			return nil, err
		}
		out = append(out, it)
	}
	return out, rows.Err()
}

func NextInvoiceNumber(ctx context.Context, tx pgx.Tx) (string, error) {
	var n int64
	if err := tx.QueryRow(ctx, "SELECT nextval('invoice_seq')").Scan(&n); err != nil {
		return "", err
	}
	return time.Now().Format("2006") + "-" + pad6(n), nil
}

func pad6(n int64) string {
	s := ""
	for i := 0; i < 6; i++ {
		s = string(rune('0'+n%10)) + s
		n /= 10
	}
	return s
}

func MarkInvoicePaid(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "UPDATE invoices SET status='paid', paid_at=now() WHERE id=$1 AND status <> 'paid'", id)
	return err
}

// --- payments (idempotent on checkout_request_id) ---

func InsertPayment(ctx context.Context, tx pgx.Tx, p *Payment) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO payments (id, invoice_id, method, checkout_request_id, merchant_request_id, phone, amount_kes, status)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		p.ID, p.InvoiceID, p.Method, p.CheckoutRequestID, p.MerchantRequestID, p.Phone, p.AmountKES, p.Status)
	return err
}

// SettlePayment transitions a pending payment exactly once (idempotent webhook
// processing). Returns the invoice id when a transition happened.
func SettlePayment(ctx context.Context, tx pgx.Tx, checkoutRequestID, status, receipt string, raw []byte) (string, bool, error) {
	var invoiceID string
	err := tx.QueryRow(ctx,
		`UPDATE payments SET status=$2, mpesa_receipt=$3, raw=$4, updated_at=now()
		 WHERE checkout_request_id=$1 AND status='pending'
		 RETURNING invoice_id`, checkoutRequestID, status, receipt, raw).Scan(&invoiceID)
	if err == pgx.ErrNoRows {
		return "", false, nil // already settled — idempotent no-op
	}
	if err != nil {
		return "", false, err
	}
	return invoiceID, true, nil
}

func ListPayments(ctx context.Context, tx pgx.Tx, invoiceID string) ([]Payment, error) {
	rows, err := tx.Query(ctx,
		`SELECT id, invoice_id, method, checkout_request_id, merchant_request_id, COALESCE(mpesa_receipt,''), phone, amount_kes, status, created_at
		 FROM payments WHERE invoice_id=$1 ORDER BY created_at DESC`, invoiceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Payment
	for rows.Next() {
		var p Payment
		if err := rows.Scan(&p.ID, &p.InvoiceID, &p.Method, &p.CheckoutRequestID, &p.MerchantRequestID, &p.MpesaReceipt, &p.Phone, &p.AmountKES, &p.Status, &p.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func PendingPayments(ctx context.Context, tx pgx.Tx, olderThan time.Duration) ([]Payment, error) {
	rows, err := tx.Query(ctx,
		`SELECT id, invoice_id, method, checkout_request_id, merchant_request_id, COALESCE(mpesa_receipt,''), phone, amount_kes, status, created_at
		 FROM payments WHERE status='pending' AND created_at < $1 LIMIT 50`, time.Now().Add(-olderThan))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Payment
	for rows.Next() {
		var p Payment
		if err := rows.Scan(&p.ID, &p.InvoiceID, &p.Method, &p.CheckoutRequestID, &p.MerchantRequestID, &p.MpesaReceipt, &p.Phone, &p.AmountKES, &p.Status, &p.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}
