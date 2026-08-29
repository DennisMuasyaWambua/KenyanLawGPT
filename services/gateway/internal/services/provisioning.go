package services

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/repository"
)

type ProvisionInput struct {
	FirmName        string `json:"firm_name"`
	Slug            string `json:"slug"`
	Plan            string `json:"plan"`
	RegNumber       string `json:"reg_number"` // LSK / firm registration number
	DataResidencyKE bool   `json:"data_residency_ke"`
	OwnerName       string `json:"owner_name"`
	OwnerEmail      string `json:"owner_email" binding:"required,email"`
	OwnerPassword   string `json:"owner_password"`
	// Set for Google sign-up: the owner authenticates with Google instead of a
	// password. When present, OwnerPassword is not required.
	GoogleSub string `json:"-"`
}

var slugSanitize = regexp.MustCompile(`[^a-z0-9]+`)

// deriveSlug builds a valid tenant slug from a firm/owner name, appending a
// short random suffix so solo (auto-provisioned) signups don't collide.
func deriveSlug(name string) string {
	base := strings.Trim(slugSanitize.ReplaceAllString(strings.ToLower(name), "-"), "-")
	if len(base) < 3 {
		base = "firm"
	}
	if len(base) > 30 {
		base = base[:30]
	}
	return base + "-" + strings.ReplaceAll(uuid.New().String(), "-", "")[:6]
}

// ProvisionTenant implements signup: control-row insert -> schema creation ->
// tenant migrations -> owner user -> starter clause library. The Neo4j side
// needs no upfront namespace work: the AI service's TenantScopedGraphQuery
// builder stamps tenant_id on every node/edge at write time and filters on it
// at read time, so a new tenant's graph partition exists implicitly.
func ProvisionTenant(ctx context.Context, database *db.DB, cfg *config.Config, in *ProvisionInput) (*repository.Tenant, *repository.User, error) {
	google := in.GoogleSub != ""
	if in.OwnerName == "" {
		in.OwnerName = strings.SplitN(in.OwnerEmail, "@", 2)[0]
	}
	if in.FirmName == "" {
		// Solo sign-up: a personal workspace named after the owner.
		in.FirmName = in.OwnerName + "'s Workspace"
	}
	if strings.TrimSpace(in.Slug) == "" {
		// Solo / auto path: derive a unique slug rather than requiring one.
		in.Slug = deriveSlug(in.OwnerName)
	}
	if !google && len(in.OwnerPassword) < 8 {
		return nil, nil, fmt.Errorf("owner_password must be at least 8 characters")
	}
	slug := strings.ToLower(strings.TrimSpace(in.Slug))
	if len(slug) < 3 || len(slug) > 40 || strings.ContainsAny(slug, " _./\\") {
		return nil, nil, fmt.Errorf("invalid slug: use 3-40 chars, lowercase letters, digits and hyphens")
	}
	if in.Plan == "" {
		in.Plan = "starter"
	}
	// Block duplicate law firms (same name, case-insensitive).
	if exists, err := repository.TenantNameExists(ctx, database.Pool, in.FirmName); err != nil {
		return nil, nil, fmt.Errorf("firm name check: %w", err)
	} else if exists {
		return nil, nil, fmt.Errorf("a firm named %q already exists", in.FirmName)
	}
	tenantID := uuid.New()
	schema := "tenant_" + strings.ReplaceAll(tenantID.String(), "-", "")
	tenant := &repository.Tenant{
		ID:              tenantID.String(),
		Name:            in.FirmName,
		Slug:            slug,
		SchemaName:      schema,
		Plan:            in.Plan,
		RegNumber:       in.RegNumber,
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

	owner := &repository.User{
		ID:           uuid.NewString(),
		Email:        strings.ToLower(in.OwnerEmail),
		FullName:     in.OwnerName,
		Status:       "active",
		AuthProvider: "password",
	}
	if google {
		sub := in.GoogleSub
		owner.GoogleSub = &sub
		owner.AuthProvider = "google"
	} else {
		hash, err := auth.HashPassword(in.OwnerPassword)
		if err != nil {
			cleanup()
			return nil, nil, err
		}
		owner.PasswordHash = hash
	}
	if err := database.WithTenant(ctx, tenant.ID, schema, func(tx pgx.Tx) error {
		// Migrations seed the protected top role (0005 creates it; 0010 renames
		// it to "Managing Partner"); assign the firm creator to it.
		ownerRole, err := repository.RoleByName(ctx, tx, "Managing Partner")
		if err != nil {
			return fmt.Errorf("managing partner role: %w", err)
		}
		owner.Role = ownerRole.Name
		owner.RoleID = &ownerRole.ID
		if err := repository.InsertUser(ctx, tx, owner); err != nil {
			return err
		}
		return seedClauseLibrary(ctx, tx, owner.ID)
	}); err != nil {
		cleanup()
		return nil, nil, fmt.Errorf("owner user: %w", err)
	}
	// Record the firm's owner pointer on the tenant control row.
	if err := repository.SetTenantOwner(ctx, database.Pool, tenant.ID, owner.ID); err != nil {
		logging.L(ctx).Error("provisioning: set tenant owner", "err", err)
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
