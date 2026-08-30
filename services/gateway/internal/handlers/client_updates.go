package handlers

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/repository"
)

// clientUpdateResult reports which channels a case update actually went out on.
type clientUpdateResult struct {
	Sent    []string `json:"sent"`
	Skipped []string `json:"skipped"`
}

// normalizeUpdateChannels defaults to email+sms and keeps only valid channels.
func normalizeUpdateChannels(in []string) []string {
	if len(in) == 0 {
		return []string{"email", "sms"}
	}
	seen := map[string]bool{}
	out := []string{}
	for _, ch := range in {
		ch = strings.ToLower(strings.TrimSpace(ch))
		if (ch == "email" || ch == "sms") && !seen[ch] {
			out = append(out, ch)
			seen[ch] = true
		}
	}
	return out
}

// NotifyClient sends a manual, free-text case-progress update to the matter's
// client over email and/or SMS. Gated by comms.send; requires the client to
// have consented (KDPA). Each message is logged (so it shows in the client
// portal) and a timeline entry is recorded on the matter.
func (s *Server) NotifyClient(c *gin.Context) {
	var in struct {
		Message  string   `json:"message" binding:"required"`
		Channels []string `json:"channels"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	channels := normalizeUpdateChannels(in.Channels)
	if len(channels) == 0 {
		badRequest(c, "channels must include 'email' and/or 'sms'")
		return
	}
	var result clientUpdateResult
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		file, err := repository.FileByID(c.Request.Context(), tx, c.Param("id"))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "matter not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		r, err := s.sendClientUpdate(c.Request.Context(), tx, file, in.Message, channels, s.claims(c).UserID())
		if err != nil {
			c.JSON(http.StatusUnprocessableEntity, gin.H{"error": err.Error()})
			return errHandled
		}
		result = r
		return nil
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true, "sent": result.Sent, "skipped": result.Skipped})
	}
}

// sendClientUpdate delivers a case-progress update to the matter's client over
// the requested channels, logging each as an outbound message (shown in the
// client portal) and recording a "client_update" timeline event. Shared by the
// manual NotifyClient endpoint and the automatic status-change hook in
// UpdateFile. Runs inside the caller's tenant transaction.
func (s *Server) sendClientUpdate(ctx context.Context, tx pgx.Tx, file *repository.File, message string, channels []string, byUser string) (clientUpdateResult, error) {
	var res clientUpdateResult
	if file.ClientID == nil {
		return res, errors.New("this matter has no linked client to notify")
	}
	cl, err := repository.ClientByID(ctx, tx, *file.ClientID)
	if err != nil {
		return res, errors.New("client not found")
	}
	if !cl.KDPAConsent {
		return res, errors.New("client has not consented to communications (KDPA)")
	}
	body := "Update on your matter " + file.Reference + " (" + file.Title + "):\n" + message
	subject := "Update on your matter " + file.Reference
	fid := file.ID
	for _, ch := range channels {
		switch ch {
		case "email":
			if cl.Email == "" {
				res.Skipped = append(res.Skipped, "email (no address on file)")
				continue
			}
			status := "sent"
			if err := s.Mail.Send(ctx, cl.Email, subject, body); err != nil {
				status = "failed"
			}
			_ = repository.InsertMessage(ctx, tx, &repository.Message{
				ID: uuid.NewString(), FileID: &fid, ClientID: file.ClientID,
				Channel: "email", Direction: "outbound", ToAddr: cl.Email, FromAddr: "firm",
				Body: body, Status: status,
			})
			if status == "sent" {
				res.Sent = append(res.Sent, "email")
			} else {
				res.Skipped = append(res.Skipped, "email (send failed)")
			}
		case "sms":
			if cl.Phone == "" {
				res.Skipped = append(res.Skipped, "sms (no phone on file)")
				continue
			}
			if s.SMS == nil {
				res.Skipped = append(res.Skipped, "sms (not configured)")
				continue
			}
			status, ref := "failed", ""
			if r, err := s.SMS.Send(ctx, cl.Phone, body); err == nil {
				status, ref = r.Status, r.MessageID
			}
			_ = repository.InsertMessage(ctx, tx, &repository.Message{
				ID: uuid.NewString(), FileID: &fid, ClientID: file.ClientID,
				Channel: "sms", Direction: "outbound", ToAddr: cl.Phone, FromAddr: "WAKILI",
				Body: body, Status: status, ProviderRef: ref,
			})
			if status != "failed" {
				res.Sent = append(res.Sent, "sms")
			} else {
				res.Skipped = append(res.Skipped, "sms (send failed)")
			}
		}
	}
	_ = repository.InsertFileEvent(ctx, tx, &repository.FileEvent{
		ID: uuid.NewString(), FileID: file.ID, EventType: "client_update", Note: message, CreatedBy: byUser,
	})
	return res, nil
}
