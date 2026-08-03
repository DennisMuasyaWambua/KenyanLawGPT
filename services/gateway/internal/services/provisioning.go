package services

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
)

type ProvisionInput struct {
	FirmName        string `json:"firm_name" binding:"required"`
	Slug            string `json:"slug" binding:"required"`
	Plan            string `json:"plan"`
	DataResidencyKE bool   `json:"data_residency_ke"`
	OwnerName       string `json:"owner_name" binding:"required"`
	OwnerEmail      string `json:"owner_email" binding:"required,email"`
	OwnerPassword   string `json:"owner_password" binding:"required,min=8"`
}

// ProvisionTenant implements signup: control-row insert -> schema creation ->
// tenant migrations -> owner user -> starter clause library. The Neo4j side
// needs no upfront namespace work: the AI service's TenantScopedGraphQuery
// builder stamps tenant_id on every node/edge at write time and filters on it
// at read time, so a new tenant's graph partition exists implicitly.
func ProvisionTenant(ctx context.Context, database *db.DB, cfg *config.Config, in *ProvisionInput) (*repository.Tenant, *repository.User, error) {
	slug := strings.ToLower(strings.TrimSpace(in.Slug))
	if len(slug) < 3 || len(slug) > 40 || strings.ContainsAny(slug, " _./\\") {
		return nil, nil, fmt.Errorf("invalid slug: use 3-40 chars, lowercase letters, digits and hyphens")
	}
	if in.Plan == "" {
		in.Plan = "starter"
	}
	tenantID := uuid.New()
	schema := "tenant_" + strings.ReplaceAll(tenantID.String(), "-", "")
	tenant := &repository.Tenant{
		ID:              tenantID.String(),
		Name:            in.FirmName,
		Slug:            slug,
		SchemaName:      schema,
		Plan:            in.Plan,
		DataResidencyKE: in.DataResidencyKE,
		Status:          "active",
	}

	if err := database.WithPublic(ctx, "", func(tx pgx.Tx) error {
		return repository.InsertTenant(ctx, tx, tenant)
	}); err != nil {
		return nil, nil, fmt.Errorf("tenant record: %w", err)
	}

	cleanup := func() {
		if _, err := database.Pool.Exec(context.Background(),
			"DROP SCHEMA IF EXISTS "+pgx.Identifier{schema}.Sanitize()+" CASCADE"); err != nil {
			logging.L(ctx).Error("provisioning cleanup: drop schema", "err", err)
		}
		if err := repository.DeleteTenant(context.Background(), database.Pool, tenant.ID); err != nil {
			logging.L(ctx).Error("provisioning cleanup: delete tenant", "err", err)
		}
	}

	if _, err := database.ApplyTenant(ctx, cfg.MigrationsDir, schema); err != nil {
		cleanup()
		return nil, nil, fmt.Errorf("tenant migrations: %w", err)
	}

	hash, err := auth.HashPassword(in.OwnerPassword)
	if err != nil {
		cleanup()
		return nil, nil, err
	}
	owner := &repository.User{
		ID:           uuid.NewString(),
		Email:        strings.ToLower(in.OwnerEmail),
		FullName:     in.OwnerName,
		Role:         rbac.RoleOwner,
		Status:       "active",
		PasswordHash: hash,
	}
	if err := database.WithTenant(ctx, tenant.ID, schema, func(tx pgx.Tx) error {
		if err := repository.InsertUser(ctx, tx, owner); err != nil {
			return err
		}
		return seedClauseLibrary(ctx, tx, owner.ID)
	}); err != nil {
		cleanup()
		return nil, nil, fmt.Errorf("owner user: %w", err)
	}
	logging.L(ctx).Info("tenant provisioned", "tenant_id", tenant.ID, "slug", slug, "schema", schema)
	return tenant, owner, nil
}

func seedClauseLibrary(ctx context.Context, tx pgx.Tx, ownerID string) error {
	clauses := []struct{ title, category, body string }{
		{"Governing Law (Kenya)", "boilerplate",
			"This Agreement shall be governed by and construed in accordance with the laws of the Republic of Kenya, and the parties submit to the exclusive jurisdiction of the courts of Kenya."},
		{"Dispute Resolution — Arbitration (NCIA)", "dispute-resolution",
			"Any dispute arising out of or in connection with this Agreement shall be referred to arbitration under the Nairobi Centre for International Arbitration (Arbitration) Rules, by a sole arbitrator appointed by agreement of the parties or, in default, by the NCIA."},
		{"Data Protection (KDPA 2019)", "compliance",
			"Each party shall comply with the Data Protection Act, No. 24 of 2019, in respect of any personal data processed under this Agreement, and shall implement appropriate technical and organisational measures against unauthorised or unlawful processing."},
		{"Advocate-Client Confidentiality", "engagement",
			"The Firm shall hold in strict confidence all information received from the Client in the course of the retainer, subject only to disclosures required by law or authorised in writing by the Client."},
	}
	for _, cl := range clauses {
		if _, err := tx.Exec(ctx,
			"INSERT INTO clause_library (id, title, category, body, created_by) VALUES ($1,$2,$3,$4,$5)",
			uuid.NewString(), cl.title, cl.category, cl.body, ownerID); err != nil {
			return err
		}
	}
	return nil
}
