package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/repository"
)

// The onboarding pipeline, in order. A client advances one stage at a time
// (except "closed", reachable from anywhere). Each forward step has a gate.
var stageOrder = map[string]int{
	"lead": 0, "intake": 1, "conflict_check": 2, "engaged": 3, "active": 4, "closed": 5,
}

func nextStage(cur string) string {
	for s, i := range stageOrder {
		if i == stageOrder[cur]+1 {
			return s
		}
	}
	return ""
}

// validateAdvance returns "" if the transition is allowed, else a reason. The
// gates encode the firm's intake requirements (retainer before engaging,
// KYC/AML + an open matter before active).
func validateAdvance(cl *repository.Client, to, retainerRef, kycRef string, matterCount int) string {
	if to == "closed" {
		return "" // a client may be closed from any stage
	}
	if _, ok := stageOrder[to]; !ok {
		return "unknown stage: " + to
	}
	if stageOrder[to] != stageOrder[cl.Status]+1 {
		if n := nextStage(cl.Status); n != "" {
			return "can only advance to the next stage (" + n + ")"
		}
		return "client cannot advance from " + cl.Status
	}
	switch to {
	case "intake":
		if cl.Email == "" && cl.Phone == "" {
			return "add an email or phone number before intake"
		}
	case "engaged":
		if cl.ConflictCheckAt == nil {
			return "complete the conflict check before engaging"
		}
		if retainerRef == "" && cl.RetainerRef == "" {
			return "a signed retainer reference is required to engage"
		}
	case "active":
		if kycRef == "" && cl.KYCRef == "" && cl.KYCCompletedAt == nil {
			return "KYC/AML must be completed before the client is active"
		}
		if matterCount == 0 {
			return "open a matter for this client before marking them active"
		}
	}
	return ""
}

// UpdateClient edits a client's contact/identity details (not pipeline status).
func (s *Server) UpdateClient(c *gin.Context) {
	var in struct {
		Name             string `json:"name" binding:"required"`
		Email            string `json:"email"`
		Phone            string `json:"phone"`
		IDNumber         string `json:"id_number"`
		ClientType       string `json:"client_type"`
		CompanyRegNumber string `json:"company_reg_number"`
		KDPAConsent      bool   `json:"kdpa_consent"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	cl := &repository.Client{
		ID: c.Param("id"), Name: in.Name, Email: in.Email, Phone: in.Phone, IDNumber: in.IDNumber,
		ClientType: in.ClientType, CompanyRegNumber: in.CompanyRegNumber, KDPAConsent: in.KDPAConsent,
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.UpdateClientDetails(c.Request.Context(), tx, cl)
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

// ConflictCheck records the manual conflict-check confirmation (a hard gate an
// advocate completes before a client can be engaged). Not automated search.
func (s *Server) ConflictCheck(c *gin.Context) {
	if s.withTenant(c, func(tx pgx.Tx) error {
		return repository.ConfirmConflictCheck(c.Request.Context(), tx, c.Param("id"), s.claims(c).UserID())
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	}
}

// AdvanceClientStage moves a client to the next pipeline stage after validating
// the gate, and writes an audit row to client_stage_events.
func (s *Server) AdvanceClientStage(c *gin.Context) {
	var in struct {
		ToStatus    string `json:"to_status" binding:"required"`
		Note        string `json:"note"`
		RetainerRef string `json:"retainer_ref"`
		KYCRef      string `json:"kyc_ref"`
		KYCDone     bool   `json:"kyc_done"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		badRequest(c, err.Error())
		return
	}
	if s.withTenant(c, func(tx pgx.Tx) error {
		cl, err := repository.ClientByID(c.Request.Context(), tx, c.Param("id"))
		if err == pgx.ErrNoRows {
			c.JSON(http.StatusNotFound, gin.H{"error": "client not found"})
			return errHandled
		}
		if err != nil {
			return err
		}
		matterCount := 0
		if in.ToStatus == "active" {
			if matterCount, err = repository.CountMattersByClient(c.Request.Context(), tx, cl.ID); err != nil {
				return err
			}
		}
		if msg := validateAdvance(cl, in.ToStatus, in.RetainerRef, in.KYCRef, matterCount); msg != "" {
			c.JSON(http.StatusUnprocessableEntity, gin.H{"error": msg})
			return errHandled
		}
		if err := repository.SetClientStage(c.Request.Context(), tx, cl.ID, in.ToStatus, in.RetainerRef, in.KYCRef, in.KYCDone); err != nil {
			return err
		}
		return repository.InsertStageEvent(c.Request.Context(), tx, &repository.StageEvent{
			ID: uuid.NewString(), ClientID: cl.ID, FromStatus: cl.Status, ToStatus: in.ToStatus,
			Note: in.Note, AdvancedBy: s.claims(c).UserID(),
		})
	}) {
		c.JSON(http.StatusOK, gin.H{"ok": true, "status": in.ToStatus})
	}
}
