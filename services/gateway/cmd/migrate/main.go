package main

import (
	"context"
	"fmt"
	"os"

	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/repository"
)

// migrate applies public-schema migrations with the admin role, then brings
// every existing tenant schema up to date with the app role (which owns the
// tenant schemas it provisioned).
func main() {
	cfg := config.Load()
	logging.Init(cfg.Env)
	ctx := context.Background()
	log := logging.L(ctx)

	admin, err := db.Connect(ctx, cfg.AdminDatabaseURL)
	if err != nil {
		log.Error("admin connect failed", "err", err)
		os.Exit(1)
	}
	n, err := admin.ApplyPublic(ctx, cfg.MigrationsDir)
	if err != nil {
		log.Error("public migrations failed", "err", err)
		os.Exit(1)
	}
	fmt.Printf("public schema: %d migration(s) applied\n", n)
	admin.Pool.Close()

	app, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Error("app connect failed", "err", err)
		os.Exit(1)
	}
	defer app.Pool.Close()

	tenants, err := repository.ListActiveTenants(ctx, app.Pool)
	if err != nil {
		log.Error("list tenants failed", "err", err)
		os.Exit(1)
	}
	for _, t := range tenants {
		n, err := app.ApplyTenant(ctx, cfg.MigrationsDir, t.SchemaName)
		if err != nil {
			log.Error("tenant migrations failed", "tenant", t.Slug, "err", err)
			os.Exit(1)
		}
		fmt.Printf("tenant %-24s %d migration(s) applied\n", t.Slug+":", n)
	}
	fmt.Println("migrations complete")
}
