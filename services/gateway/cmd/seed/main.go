package main

// seed provisions two demo law firms with deliberately DISTINGUISHABLE
// private data (unique marker strings per tenant) so cross-tenant isolation
// can be verified manually and by the automated leakage suite:
//
//	mwangi-advocates    -> secret marker "MWANGI-CONFIDENTIAL-ALPHA"
//	odhiambo-partners   -> secret marker "ODHIAMBO-CONFIDENTIAL-BRAVO"

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	wakiliv1 "github.com/wakiliai/gateway/gen/wakiliv1"
	"github.com/wakiliai/gateway/internal/auth"
	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/grpcclient"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/rbac"
	"github.com/wakiliai/gateway/internal/repository"
	"github.com/wakiliai/gateway/internal/services"
	"github.com/wakiliai/gateway/internal/storage"
)

const demoPassword = "DemoPass123!"

type firmSpec struct {
	Name, Slug, Marker string
	ClientA, ClientB   string
	PhoneA             string
}

var firms = []firmSpec{
	{
		Name: "Mwangi & Co. Advocates", Slug: "mwangi-advocates",
		Marker:  "MWANGI-CONFIDENTIAL-ALPHA",
		ClientA: "Wanjiku Kamau", ClientB: "Simba Logistics Ltd", PhoneA: "254700111222",
	},
	{
		Name: "Odhiambo Partners LLP", Slug: "odhiambo-partners",
		Marker:  "ODHIAMBO-CONFIDENTIAL-BRAVO",
		ClientA: "Otieno Ochieng", ClientB: "Baraka Farms Ltd", PhoneA: "254711333444",
	},
}

func main() {
	cfg := config.Load()
	logging.Init(cfg.Env)
	ctx := context.Background()

	database, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		fatal("postgres connect", err)
	}
	defer database.Pool.Close()

	store, err := storage.New(cfg)
	if err != nil {
		fatal("object store", err)
	}
	_ = store.EnsureBucket(ctx)

	var ai *grpcclient.AIClient
	if client, err := grpcclient.Dial(cfg); err == nil {
		ai = client
		defer ai.Close()
	} else {
		fmt.Println("warn: AI service unavailable — seeding without vector/graph ingestion:", err)
	}

	for _, f := range firms {
		if err := seedFirm(ctx, database, cfg, store, ai, f); err != nil {
			fatal("seed "+f.Slug, err)
		}
	}

	fmt.Println("\n=== Demo credentials (password for all: " + demoPassword + ") ===")
	for _, f := range firms {
		fmt.Printf("\n%s  (slug: %s)\n", f.Name, f.Slug)
		fmt.Printf("  owner:     owner@%s.demo\n", f.Slug)
		fmt.Printf("  partner:   partner@%s.demo\n", f.Slug)
		fmt.Printf("  associate: associate@%s.demo\n", f.Slug)
		fmt.Printf("  paralegal: paralegal@%s.demo\n", f.Slug)
		fmt.Printf("  client:    client@%s.demo (portal)\n", f.Slug)
	}
	fmt.Println("\nOpen http://localhost:3000 and pick a firm on the login screen.")
}

func seedFirm(ctx context.Context, database *db.DB, cfg *config.Config, store *storage.ObjectStore, ai *grpcclient.AIClient, f firmSpec) error {
	if t, err := repository.TenantBySlug(ctx, database.Pool, f.Slug); err == nil {
		fmt.Printf("tenant %s already exists (%s) — skipping\n", f.Slug, t.ID)
		return nil
	}
	tenant, owner, err := services.ProvisionTenant(ctx, database, cfg, &services.ProvisionInput{
		FirmName: f.Name, Slug: f.Slug, Plan: "chambers", DataResidencyKE: true,
		OwnerName: "Firm Owner", OwnerEmail: "owner@" + f.Slug + ".demo", OwnerPassword: demoPassword,
	})
	if err != nil {
		return err
	}
	fmt.Printf("provisioned %s (%s)\n", f.Slug, tenant.ID)

	hash, err := auth.HashPassword(demoPassword)
	if err != nil {
		return err
	}

	var docID, objectKey, matterID string
	clientAID := uuid.NewString()

	err = database.WithTenant(ctx, tenant.ID, tenant.SchemaName, func(tx pgx.Tx) error {
		// Create the default non-owner roles (Owner already exists from the 0005
		// migration) so demo staff have real, permissioned roles.
		roleIDByName := map[string]string{}
		for _, tpl := range rbac.DefaultTemplates {
			if tpl.Protected {
				continue
			}
			id := uuid.NewString()
			if err := repository.CreateRole(ctx, tx,
				&repository.Role{ID: id, Name: tpl.Name, Description: tpl.Description}, tpl.Permissions); err != nil {
				return err
			}
			roleIDByName[strings.ToLower(tpl.Name)] = id
		}
		// Staff, each assigned to the matching role.
		for _, r := range []string{rbac.RolePartner, rbac.RoleAssociate, rbac.RoleParalegal} {
			rid := roleIDByName[r] // rbac.Role* constants are lowercase, matching lower(name)
			if err := repository.InsertUser(ctx, tx, &repository.User{
				ID: uuid.NewString(), Email: r + "@" + f.Slug + ".demo",
				FullName: "Demo " + r, Role: r, RoleID: &rid, Status: "active", PasswordHash: hash,
			}); err != nil {
				return err
			}
		}
		// Clients + portal user.
		if err := repository.InsertClient(ctx, tx, &repository.Client{
			ID: clientAID, Name: f.ClientA, Email: "clienta@" + f.Slug + ".demo",
			Phone: f.PhoneA, IDNumber: "12345678", KDPAConsent: true,
		}); err != nil {
			return err
		}
		if err := repository.InsertClient(ctx, tx, &repository.Client{
			ID: uuid.NewString(), Name: f.ClientB, Email: "clientb@" + f.Slug + ".demo", KDPAConsent: true,
		}); err != nil {
			return err
		}
		if err := repository.InsertUser(ctx, tx, &repository.User{
			ID: uuid.NewString(), Email: "client@" + f.Slug + ".demo", FullName: f.ClientA,
			Role: rbac.RoleClient, Status: "active", ClientID: &clientAID, PasswordHash: hash,
		}); err != nil {
			return err
		}
		if err := repository.InsertConsent(ctx, tx, &repository.Consent{
			ID: uuid.NewString(), SubjectType: "client", SubjectID: clientAID,
			Purpose: "sms_reminders", Granted: true, GrantedBy: owner.ID, Source: "web",
		}); err != nil {
			return err
		}

		// Matters.
		matterID = uuid.NewString()
		if err := repository.InsertMatter(ctx, tx, &repository.Matter{
			ID: matterID, Reference: "EMP/" + time.Now().Format("2006") + "/001",
			Title: "Unfair termination claim — " + f.ClientA, Description: "Employment dispute; client dismissed without notice.",
			ClientID: &clientAID, Status: "active", PracticeArea: "Employment",
			Court: "Employment and Labour Relations Court", CourtCaseNumber: "ELRC E123 of 2026",
			CreatedBy: owner.ID,
		}); err != nil {
			return err
		}
		if err := repository.InsertMatter(ctx, tx, &repository.Matter{
			ID: uuid.NewString(), Reference: "CONV/" + time.Now().Format("2006") + "/002",
			Title: "Land transfer — " + f.ClientB, Description: "Conveyancing for LR No. 209/1234.",
			Status: "intake", PracticeArea: "Conveyancing", CreatedBy: owner.ID,
		}); err != nil {
			return err
		}
		if err := repository.InsertCourtDate(ctx, tx, &repository.CourtDate{
			ID: uuid.NewString(), MatterID: matterID, Date: time.Now().AddDate(0, 0, 10),
			Courtroom: "ELRC Court 3, Milimani", Judge: "Hon. Justice Demo", Purpose: "Mention",
		}); err != nil {
			return err
		}
		if err := repository.InsertDeadline(ctx, tx, &repository.Deadline{
			ID: uuid.NewString(), MatterID: matterID, Title: "File witness statements",
			DueAt: time.Now().AddDate(0, 0, 7), RemindAt: time.Now().AddDate(0, 0, 6), CreatedBy: owner.ID,
		}); err != nil {
			return err
		}
		if err := repository.InsertTimeEntry(ctx, tx, &repository.TimeEntry{
			ID: uuid.NewString(), MatterID: matterID, UserID: owner.ID,
			Description: "Initial client interview and case assessment", Minutes: 90, RateKES: 12000, EntryDate: time.Now(),
		}); err != nil {
			return err
		}

		// Tenant-private precedent note carrying the DISTINGUISHING marker.
		docID = uuid.NewString()
		objectKey = storage.Key(tenant.ID, docID, "internal-precedent-note.txt")
		return repository.InsertDocument(ctx, tx, &repository.Document{
			ID: docID, MatterID: &matterID, Filename: "internal-precedent-note.txt",
			ObjectKey: objectKey, MimeType: "text/plain", SizeBytes: 0, DocKind: "precedent_note",
			UploadedBy: owner.ID, IngestStatus: "pending",
		})
	})
	if err != nil {
		return err
	}

	noteBody := fmt.Sprintf(`INTERNAL PRECEDENT NOTE — %s — STRICTLY CONFIDENTIAL
Marker: %s

Matter: Unfair termination claim for %s.
Strategy note: rely on Section 45 of the Employment Act (No. 11 of 2007) —
termination is unfair if not for a valid reason related to conduct, capacity
or operational requirements, and without fair procedure. Our internal
assessment values the claim at the 12-month gross salary ceiling under
Section 49(1)(c). Settlement floor agreed with client: KES 1,400,000.
Comparable outcome: our 2024 matter (settled, confidential) on near-identical
facts before the ELRC.`, f.Name, f.Marker, f.ClientA)

	if err := store.Put(ctx, tenant.ID, objectKey, []byte(noteBody), "text/plain"); err != nil {
		return fmt.Errorf("upload seed doc: %w", err)
	}

	if ai != nil {
		gctx := grpcclient.Ctx(ctx, tenant.ID, "seed-"+tenant.Slug)
		stream, err := ai.Ingestion.IngestDocument(gctx, &wakiliv1.IngestRequest{
			Tenant:     grpcclient.TC(tenant.ID, tenant.Plan, tenant.DataResidencyKE),
			DocumentId: docID, ObjectKey: objectKey,
			Filename: "internal-precedent-note.txt", MimeType: "text/plain",
			MatterId: matterID, TraceId: "seed-" + tenant.Slug,
		})
		if err != nil {
			fmt.Println("warn: ingest RPC failed:", err)
		} else {
			for {
				if _, err := stream.Recv(); err != nil {
					break
				}
			}
			_ = database.WithTenant(ctx, tenant.ID, tenant.SchemaName, func(tx pgx.Tx) error {
				return repository.SetIngestStatus(ctx, tx, docID, "ingested")
			})
			fmt.Printf("  ingested private note for %s\n", f.Slug)
		}
	}
	return nil
}

func fatal(what string, err error) {
	fmt.Fprintf(os.Stderr, "seed: %s: %v\n", what, err)
	os.Exit(1)
}
