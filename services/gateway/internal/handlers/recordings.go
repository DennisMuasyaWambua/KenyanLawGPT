package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/storage"
)

// CreateRecording enforces the hard consent gate: no recording row is created
// unless the advocate has explicitly confirmed consent. Returns a presigned PUT
// URL for the browser to upload the audio straight to R2.
func (s *Server) CreateRecording(c *gin.Context) {
	var in struct {
		FileID           *string `json:"file_id"`
		ClientID         *string `json:"client_id"`
		Filename         string  `json:"filename" binding:"required"`
		MimeType         string  `json:"mime_type"`
		ConsentConfirmed bool    `json:"consent_confirmed"`
		// How many people are in the meeting (0 = estimate). Knowing it makes the
		// speaker labels far more accurate.
		NumSpeakers int `json:"num_speakers" binding:"min=0,max=10"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if !in.ConsentConfirmed {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "consent must be confirmed before recording"})
		return
	}
	tenant := s.tenant(c)
	id := uuid.NewString()
	key := storage.Key(tenant.ID, id, in.Filename)
	uploadURL, err := s.Store.PresignPut(c.Request.Context(), tenant.ID, key)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "could not presign upload"})
		return
	}
	r := &repository.Recording{
		ID: id, FileID: in.FileID, AdvocateUserID: s.claims(c).UserID(), ClientID: in.ClientID,
		ObjectKey: key, Filename: in.Filename, MimeType: in.MimeType, ConsentConfirmed: true, Status: "recording",
		NumSpeakers: in.NumSpeakers,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.InsertRecording(c.Request.Context(), tx, r)
	}) {
		c.JSON(http.StatusCreated, gin.H{"recording": r, "upload_url": uploadURL})
	}
}

// MarkRecordingUploaded flips a recording to "transcribing" after the browser
// finishes the R2 upload; the AI background worker takes it from there.
func (s *Server) MarkRecordingUploaded(c *gin.Context) {
	var in struct {
		DurationSeconds int `json:"duration_seconds"`
	}
	_ = c.ShouldBindJSON(&in)
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		err := repository.MarkUploaded(c.Request.Context(), tx, c.Param("id"), s.claims(c).UserID(), in.DurationSeconds)
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusForbidden, gin.H{"error": "recording not found or not yours"})
			return errHandled
		}
		return err
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true, "status": "transcribing"})
	}
}

// RetryRecording puts a failed recording back in the transcription queue (e.g.
// after a transient Whisper/LLM outage). The audio is still in object storage.
func (s *Server) RetryRecording(c *gin.Context) {
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		err := repository.RetryRecording(c.Request.Context(), tx, c.Param("id"), s.claims(c).UserID())
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusConflict, gin.H{"error": "only your own failed recordings can be retried"})
			return errHandled
		}
		return err
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true, "status": "transcribing"})
	}
}

// ListRecordings returns the caller's own recordings, or all firm recordings
// with recordings.view_all (and ?scope=all).
func (s *Server) ListRecordings(c *gin.Context) {
	wantAll := c.Query("scope") == "all" && s.can(c, rbac.PermRecordingsViewAll)
	var recs []repository.Recording
	if s.withTenant(c, func(tx pgx.Tx) error {
		var err error
		if wantAll {
			recs, err = repository.ListAllRecordings(c.Request.Context(), tx)
		} else {
			recs, err = repository.ListOwnRecordings(c.Request.Context(), tx, s.claims(c).UserID())
		}
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"recordings": recs})
	}
}

func (s *Server) GetRecording(c *gin.Context) {
	var rec *repository.Recording
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		r, err := repository.GetRecording(c.Request.Context(), tx, c.Param("id"))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "recording not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		// view_own callers may only see their own recordings.
		if r.AdvocateUserID != s.claims(c).UserID() && !s.can(c, rbac.PermRecordingsViewAll) {
			c.JSON(http.StatusForbidden, gin.H{"error": "not allowed to view this recording"})
			return errHandled
		}
		rec = r
		return nil
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"recording": rec})
	}
}

// SetRecordingSpeakers names the speaker labels ("Speaker 1" -> "Adv. Wanjiru").
// Giving two labels the same name merges them in the transcript view, which is
// how a speaker the diarizer split in two is corrected. Authz mirrors GetRecording.
func (s *Server) SetRecordingSpeakers(c *gin.Context) {
	var in struct {
		Names map[string]string `json:"names"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	names := map[string]string{}
	for label, name := range in.Names {
		n, err := strconv.Atoi(label)
		if err != nil || n < 1 || n > 20 {
			badRequest(c, "speaker labels are numbers from 1 to 20")
			return
		}
		name = strings.TrimSpace(name)
		if len([]rune(name)) > 80 {
			badRequest(c, "speaker names are limited to 80 characters")
			return
		}
		if name != "" {
			names[strconv.Itoa(n)] = name
		}
	}
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		r, err := repository.GetRecording(c.Request.Context(), tx, c.Param("id"))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "recording not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if r.AdvocateUserID != s.claims(c).UserID() && !s.can(c, rbac.PermRecordingsViewAll) {
			c.JSON(http.StatusForbidden, gin.H{"error": "not allowed to edit this recording"})
			return errHandled
		}
		return repository.SetSpeakerNames(c.Request.Context(), tx, r.ID, names)
	})
	if ok {
		c.JSON(http.StatusOK, gin.H{"ok": true, "speaker_names": names})
	}
}

// ShareRecording emails a recording's structured notes + transcript to a
// recipient. Authz mirrors GetRecording (own, or view_all). The email body is
// built server-side from the stored recording — the client only supplies the
// destination address, so this can't be used as an open relay for arbitrary
// content.
func (s *Server) ShareRecording(c *gin.Context) {
	var in struct {
		Email string `json:"email" binding:"required,email"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	var rec *repository.Recording
	ok := s.withTenant(c, func(tx pgx.Tx) error {
		r, err := repository.GetRecording(c.Request.Context(), tx, c.Param("id"))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "recording not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		if r.AdvocateUserID != s.claims(c).UserID() && !s.can(c, rbac.PermRecordingsViewAll) {
			c.JSON(http.StatusForbidden, gin.H{"error": "not allowed to share this recording"})
			return errHandled
		}
		rec = r
		return nil
	})
	if !ok {
		return
	}
	if rec.Status != "complete" {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"error": "recording is not ready to share yet"})
		return
	}
	subject := "Meeting transcript & notes — " + rec.Filename
	if err := s.Mail.Send(c.Request.Context(), in.Email, subject, formatRecordingEmail(rec)); err != nil {
		logging.L(c.Request.Context()).Warn("share recording email failed", "recording", rec.ID, "err", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "could not send email: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// formatRecordingEmail renders the structured summary (if present) plus the full
// transcript as readable plain text suitable for email.
func formatRecordingEmail(r *repository.Recording) string {
	var b strings.Builder
	b.WriteString("Meeting notes — " + r.Filename + "\n")
	b.WriteString(strings.Repeat("=", 48) + "\n\n")
	b.WriteString(formatInsights(r.SummaryText))
	b.WriteString("\n\nFULL TRANSCRIPT\n")
	b.WriteString(strings.Repeat("-", 48) + "\n")
	if t := speakerTranscript(r); t != "" {
		b.WriteString(t + "\n")
	} else if strings.TrimSpace(r.TranscriptText) == "" {
		b.WriteString("(no transcript)\n")
	} else {
		b.WriteString(r.TranscriptText + "\n")
	}
	return b.String()
}

// speakerTranscript renders the diarized utterances with the names the user
// gave each speaker ("[01:12] Adv. Wanjiru: …"), merging consecutive lines that
// now belong to the same name. "" when the recording has no speaker data.
func speakerTranscript(r *repository.Recording) string {
	var segs []repository.Utterance
	if len(r.TranscriptSegments) == 0 || json.Unmarshal(r.TranscriptSegments, &segs) != nil || len(segs) == 0 {
		return ""
	}
	names := map[string]string{}
	_ = json.Unmarshal(r.SpeakerNames, &names)
	label := func(n int) string {
		if name := names[strconv.Itoa(n)]; name != "" {
			return name
		}
		return fmt.Sprintf("Speaker %d", n)
	}
	var lines []string
	prev := ""
	for _, u := range segs {
		who := label(u.Speaker)
		if who == prev && len(lines) > 0 {
			lines[len(lines)-1] += " " + u.Text
			continue
		}
		lines = append(lines, fmt.Sprintf("[%s] %s: %s", clock(u.Start), who, u.Text))
		prev = who
	}
	return strings.Join(lines, "\n")
}

func clock(seconds float64) string {
	t := int(seconds)
	if t >= 3600 {
		return fmt.Sprintf("%d:%02d:%02d", t/3600, t%3600/60, t%60)
	}
	return fmt.Sprintf("%02d:%02d", t/60, t%60)
}

// formatInsights turns the AI worker's structured-JSON summary into readable
// text. If the summary isn't the expected JSON it's returned verbatim.
func formatInsights(summary string) string {
	s := strings.TrimSpace(summary)
	if s == "" {
		return "(no summary available)"
	}
	var ins struct {
		ExecutiveSummary    string   `json:"executive_summary"`
		KeyDiscussionPoints []string `json:"key_discussion_points"`
		DecisionsMade       []string `json:"decisions_made"`
		ActionItems         []struct {
			Assignee        string  `json:"assignee"`
			TaskDescription string  `json:"task_description"`
			Deadline        *string `json:"deadline"`
		} `json:"action_items"`
		OpenQuestions []string `json:"open_questions"`
	}
	if err := json.Unmarshal([]byte(s), &ins); err != nil {
		return s // not the expected JSON — pass through as-is
	}
	var b strings.Builder
	if ins.ExecutiveSummary != "" {
		b.WriteString("EXECUTIVE SUMMARY\n" + ins.ExecutiveSummary + "\n\n")
	}
	writeList := func(title string, items []string) {
		if len(items) == 0 {
			return
		}
		b.WriteString(title + "\n")
		for _, it := range items {
			b.WriteString("  • " + it + "\n")
		}
		b.WriteString("\n")
	}
	writeList("KEY DISCUSSION POINTS", ins.KeyDiscussionPoints)
	writeList("DECISIONS MADE", ins.DecisionsMade)
	if len(ins.ActionItems) > 0 {
		b.WriteString("ACTION ITEMS\n")
		for _, a := range ins.ActionItems {
			who := a.Assignee
			if who == "" {
				who = "Unassigned"
			}
			line := "  • [" + who + "] " + a.TaskDescription
			if a.Deadline != nil && strings.TrimSpace(*a.Deadline) != "" {
				line += " (due " + *a.Deadline + ")"
			}
			b.WriteString(line + "\n")
		}
		b.WriteString("\n")
	}
	writeList("OPEN QUESTIONS", ins.OpenQuestions)
	out := strings.TrimSpace(b.String())
	if out == "" {
		return s
	}
	return out
}

// FileRecordings lists a file's recordings. Like ListRecordings, view_own
// callers only see their own — transcripts of other advocates' privileged client
// meetings require recordings.view_all.
func (s *Server) FileRecordings(c *gin.Context) {
	canAll := s.can(c, rbac.PermRecordingsViewAll)
	userID := s.claims(c).UserID()
	var recs []repository.Recording
	if s.withTenant(c, func(tx pgx.Tx) error {
		var err error
		if canAll {
			recs, err = repository.ListRecordingsByFile(c.Request.Context(), tx, c.Param("id"))
		} else {
			recs, err = repository.ListOwnRecordingsByFile(c.Request.Context(), tx, c.Param("id"), userID)
		}
		return err
	}) {
		c.JSON(http.StatusOK, gin.H{"recordings": recs})
	}
}
