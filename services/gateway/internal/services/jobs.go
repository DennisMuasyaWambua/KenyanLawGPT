package services

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/integrations/africastalking"
	"github.com/wakiliai/gateway/internal/integrations/email"
	"github.com/wakiliai/gateway/internal/integrations/mpesa"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/metrics"
	"github.com/wakiliai/gateway/internal/repository"
)

// RunReminderLoop scans every active tenant for upcoming court dates and
// deadlines and fans out SMS (Africa's Talking) + email + in-app
// notifications, marking each item reminded exactly once.
func RunReminderLoop(ctx context.Context, database *db.DB, cfg *config.Config, sms *africastalking.Client, mail email.Provider) {
	ticker := time.NewTicker(cfg.RemindersInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			runRemindersOnce(ctx, database, sms, mail)
		}
	}
}

func runRemindersOnce(ctx context.Context, database *db.DB, sms *africastalking.Client, mail email.Provider) {
	tenants, err := repository.ListActiveTenants(ctx, database.Pool)
	if err != nil {
		logging.L(ctx).Error("reminders: list tenants", "err", err)
		return
	}
	for _, t := range tenants {
		t := t
		err := database.WithTenant(ctx, t.ID, t.SchemaName, func(tx pgx.Tx) error {
			courtDates, deadlines, err := repository.ListUpcoming(ctx, tx, 48*time.Hour)
			if err != nil {
				return err
			}
			for _, cd := range courtDates {
				m, err := repository.FileByID(ctx, tx, cd.FileID)
				if err != nil {
					continue
				}
				body := fmt.Sprintf("Court date reminder: %s (%s) on %s at %s. Purpose: %s",
					m.Title, m.Reference, cd.Date.Format("Mon 02 Jan 2006 15:04"), cd.Courtroom, cd.Purpose)
				notifyFile(ctx, tx, sms, mail, m, body)
				if err := repository.MarkReminded(ctx, tx, "court_dates", cd.ID); err != nil {
					return err
				}
				metrics.Inc("wakili_reminders_sent_total", map[string]string{"kind": "court_date"})
			}
			for _, d := range deadlines {
				m, err := repository.FileByID(ctx, tx, d.FileID)
				if err != nil {
					continue
				}
				body := fmt.Sprintf("Deadline reminder: %q for %s (%s) due %s",
					d.Title, m.Title, m.Reference, d.DueAt.Format("Mon 02 Jan 2006 15:04"))
				notifyFile(ctx, tx, sms, mail, m, body)
				if err := repository.MarkReminded(ctx, tx, "deadlines", d.ID); err != nil {
					return err
				}
				metrics.Inc("wakili_reminders_sent_total", map[string]string{"kind": "deadline"})
			}
			// Calendar event reminders (personal + shared; multiple per event).
			reminders, err := repository.DueReminders(ctx, tx)
			if err != nil {
				return err
			}
			for _, rem := range reminders {
				when := rem.StartAt.Format("Mon 02 Jan 2006 15:04")
				body := fmt.Sprintf("Reminder: %s at %s", rem.Title, when)
				if rem.Location != "" {
					body += " · " + rem.Location
				}
				switch rem.Channel {
				case "sms":
					// Per-user phone numbers aren't collected yet; the schema
					// already permits 'sms' so this branch lights up once they are.
					logging.L(ctx).Debug("sms calendar reminder skipped (no user phone)", "reminder", rem.ReminderID)
				default: // email
					notifyUser(ctx, tx, mail, rem.OwnerID, "C. Karwitha C.K Advocates calendar reminder", body)
				}
				if err := repository.MarkReminderSent(ctx, tx, rem.ReminderID); err != nil {
					return err
				}
				metrics.Inc("wakili_reminders_sent_total", map[string]string{"kind": "calendar"})
			}
			return nil
		})
		if err != nil {
			logging.L(ctx).Error("reminders: tenant scan", "tenant", t.Slug, "err", err)
		}
	}
}

// notifyUser fans a message to a single user via in-app notification + email.
func notifyUser(ctx context.Context, tx pgx.Tx, mail email.Provider, userID, subject, body string) {
	_ = repository.InsertNotification(ctx, tx, &repository.Notification{
		ID: uuid.NewString(), UserID: userID, Kind: "reminder", Body: body,
	})
	if u, err := repository.UserByID(ctx, tx, userID); err == nil {
		if err := mail.Send(ctx, u.Email, subject, body); err != nil {
			logging.L(ctx).Warn("reminder email failed", "err", err)
		}
	}
}

func notifyFile(ctx context.Context, tx pgx.Tx, sms *africastalking.Client, mail email.Provider, m *repository.File, body string) {
	// In-app notification for the assigned advocate (or file creator).
	target := m.CreatedBy
	if m.AssignedTo != nil {
		target = *m.AssignedTo
	}
	_ = repository.InsertNotification(ctx, tx, &repository.Notification{
		ID: uuid.NewString(), UserID: target, Kind: "reminder", Body: body,
	})
	if u, err := repository.UserByID(ctx, tx, target); err == nil {
		if err := mail.Send(ctx, u.Email, "C. Karwitha C.K Advocates reminder", body); err != nil {
			logging.L(ctx).Warn("reminder email failed", "err", err)
		}
	}
	// SMS to the client, if we have a consented phone number on file.
	if m.ClientID != nil {
		if cl, err := repository.ClientByID(ctx, tx, *m.ClientID); err == nil && cl.Phone != "" && cl.KDPAConsent {
			res, err := sms.Send(ctx, cl.Phone, body)
			status, ref := "failed", ""
			if err == nil {
				status, ref = res.Status, res.MessageID
			}
			_ = repository.InsertMessage(ctx, tx, &repository.Message{
				ID: uuid.NewString(), FileID: &m.ID, ClientID: m.ClientID,
				Channel: "sms", Direction: "outbound", ToAddr: cl.Phone, FromAddr: "WAKILI",
				Body: body, Status: status, ProviderRef: ref,
			})
		}
	}
}

// RunReconcileLoop re-queries Daraja for payments stuck in pending (missed or
// delayed callbacks) and settles them idempotently.
func RunReconcileLoop(ctx context.Context, database *db.DB, cfg *config.Config, daraja *mpesa.Daraja) {
	if !daraja.Configured() {
		logging.L(ctx).Info("daraja not configured; reconciliation loop disabled")
		return
	}
	ticker := time.NewTicker(cfg.ReconcileInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			reconcileOnce(ctx, database, daraja)
		}
	}
}

func reconcileOnce(ctx context.Context, database *db.DB, daraja *mpesa.Daraja) {
	tenants, err := repository.ListActiveTenants(ctx, database.Pool)
	if err != nil {
		return
	}
	for _, t := range tenants {
		t := t
		err := database.WithTenant(ctx, t.ID, t.SchemaName, func(tx pgx.Tx) error {
			pending, err := repository.PendingPayments(ctx, tx, 5*time.Minute)
			if err != nil {
				return err
			}
			for _, p := range pending {
				res, err := daraja.QueryStatus(ctx, p.CheckoutRequestID)
				if err != nil {
					continue
				}
				raw, _ := json.Marshal(res)
				var status string
				switch res.ResponseCode {
				case "0":
					status = "success"
				default:
					status = "failed"
				}
				invoiceID, settled, err := repository.SettlePayment(ctx, tx, p.CheckoutRequestID, status, "", raw)
				if err != nil {
					return err
				}
				if settled && status == "success" {
					if err := repository.MarkInvoicePaid(ctx, tx, invoiceID); err != nil {
						return err
					}
					metrics.Inc("wakili_payments_reconciled_total", nil)
				}
			}
			return nil
		})
		if err != nil {
			logging.L(ctx).Error("reconcile: tenant scan", "tenant", t.Slug, "err", err)
		}
	}
}
