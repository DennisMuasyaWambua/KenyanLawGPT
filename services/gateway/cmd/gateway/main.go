package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"

	"github.com/wakiliai/gateway/internal/config"
	"github.com/wakiliai/gateway/internal/db"
	"github.com/wakiliai/gateway/internal/grpcclient"
	"github.com/wakiliai/gateway/internal/handlers"
	"github.com/wakiliai/gateway/internal/integrations/africastalking"
	"github.com/wakiliai/gateway/internal/integrations/email"
	"github.com/wakiliai/gateway/internal/integrations/judiciary"
	"github.com/wakiliai/gateway/internal/integrations/mpesa"
	"github.com/wakiliai/gateway/internal/integrations/whatsapp"
	"github.com/wakiliai/gateway/internal/logging"
	"github.com/wakiliai/gateway/internal/services"
	"github.com/wakiliai/gateway/internal/storage"
)

func main() {
	cfg := config.Load()
	logging.Init(cfg.Env)
	log := logging.L(context.Background())

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	database, err := db.Connect(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Error("postgres connect failed", "err", err)
		os.Exit(1)
	}
	defer database.Pool.Close()

	rdb := redis.NewClient(&redis.Options{Addr: cfg.RedisAddr})
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Error("redis connect failed", "err", err)
		os.Exit(1)
	}

	store, err := storage.New(cfg)
	if err != nil {
		log.Error("object store init failed", "err", err)
		os.Exit(1)
	}
	if err := store.EnsureBucket(ctx); err != nil {
		log.Warn("ensure bucket failed (continuing)", "err", err)
	}

	ai, err := grpcclient.Dial(cfg)
	if err != nil {
		log.Error("ai grpc client init failed (check mTLS cert paths)", "err", err)
		os.Exit(1)
	}
	defer ai.Close()

	sms := africastalking.New(cfg)
	mail := email.New(cfg)
	daraja := mpesa.New(cfg)
	jud := judiciary.New(cfg, rdb)
	wa := whatsapp.New(cfg)

	if err := services.EnsurePlatformAdmin(ctx, database, cfg.PlatformAdminEmail, cfg.PlatformAdminPassword); err != nil {
		log.Warn("ensure platform admin failed", "err", err)
	}

	go services.RunReminderLoop(ctx, database, cfg, sms, mail, wa)
	go services.RunReconcileLoop(ctx, database, cfg, daraja)

	if cfg.Env == "prod" {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	r.Use(gin.Recovery())

	srv := &handlers.Server{
		DB: database, Cfg: cfg, RDB: rdb, AI: ai, Store: store,
		SMS: sms, Mail: mail, Daraja: daraja, Judiciary: jud,
	}
	srv.Register(r)

	log.Info("gateway listening", "port", cfg.Port, "env", cfg.Env)
	if err := r.Run(":" + cfg.Port); err != nil {
		log.Error("server exited", "err", err)
		os.Exit(1)
	}
}
