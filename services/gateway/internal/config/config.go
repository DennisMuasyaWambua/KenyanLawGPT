package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Port        string
	Env         string // "dev" | "prod"
	BaseDomain  string // e.g. "wakili.ai" — used for subdomain tenant resolution
	CORSOrigins []string

	DatabaseURL      string // app role (non-superuser, RLS enforced)
	AdminDatabaseURL string // migrations only
	MigrationsDir    string

	RedisAddr string

	JWTSecret  string
	AccessTTL  time.Duration
	RefreshTTL time.Duration

	GoogleClientID string // Google Identity Services OAuth client id (id-token audience)
	AppBaseURL     string // public frontend origin, used to build invite links

	// Bootstrap super-admin (platform control plane). Idempotently ensured on
	// startup when both are set; leave empty in envs that shouldn't seed one.
	PlatformAdminEmail    string
	PlatformAdminPassword string

	AIGRPCAddr       string
	AIGRPCServerName string // must match SAN in the AI service's server cert
	MTLSCACert       string
	MTLSClientCert   string
	MTLSClientKey    string

	S3Endpoint       string
	S3PublicEndpoint string // browser-reachable endpoint used only for presigning
	S3PublicUseSSL   bool   // TLS for the public endpoint (usually true, even when the internal endpoint is plaintext)
	S3AccessKey      string
	S3SecretKey      string
	S3Bucket         string
	S3Region         string
	S3UseSSL         bool

	ATUsername string
	ATAPIKey   string
	ATSenderID string
	ATBaseURL  string

	DarajaBaseURL        string
	DarajaConsumerKey    string
	DarajaConsumerSecret string
	DarajaShortCode      string
	DarajaPasskey        string
	DarajaCallbackURL    string

	JudiciaryBaseURL string

	SMTPHost  string
	SMTPPort  string
	SMTPUser  string
	SMTPPass  string
	EmailFrom string

	RateLimitPerMin   int
	RemindersInterval time.Duration
	ReconcileInterval time.Duration
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envDur(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}

func Load() *Config {
	return &Config{
		Port:        env("PORT", "8080"),
		Env:         env("APP_ENV", "dev"),
		BaseDomain:  env("BASE_DOMAIN", "localhost"),
		CORSOrigins: strings.Split(env("CORS_ORIGINS", "http://localhost:3000"), ","),

		DatabaseURL:      env("DATABASE_URL", "postgres://wakili_app:wakili_app_pw@localhost:5432/wakili?sslmode=disable"),
		AdminDatabaseURL: env("ADMIN_DATABASE_URL", "postgres://postgres:postgres@localhost:5432/wakili?sslmode=disable"),
		MigrationsDir:    env("MIGRATIONS_DIR", "/app/migrations"),

		RedisAddr: env("REDIS_ADDR", "localhost:6379"),

		JWTSecret:  env("JWT_SECRET", "dev-only-secret-change-me"),
		AccessTTL:  envDur("ACCESS_TOKEN_TTL", 15*time.Minute),
		RefreshTTL: envDur("REFRESH_TOKEN_TTL", 168*time.Hour),

		GoogleClientID: env("GOOGLE_CLIENT_ID", ""),
		AppBaseURL:     env("APP_BASE_URL", "http://localhost:3000"),

		PlatformAdminEmail:    env("PLATFORM_ADMIN_EMAIL", ""),
		PlatformAdminPassword: env("PLATFORM_ADMIN_PASSWORD", ""),

		AIGRPCAddr:       env("AI_GRPC_ADDR", "localhost:50051"),
		AIGRPCServerName: env("AI_GRPC_SERVER_NAME", "ai"),
		MTLSCACert:       env("MTLS_CA_CERT", "/certs/ca.crt"),
		MTLSClientCert:   env("MTLS_CLIENT_CERT", "/certs/gateway.crt"),
		MTLSClientKey:    env("MTLS_CLIENT_KEY", "/certs/gateway.key"),

		S3Endpoint:       env("S3_ENDPOINT", "localhost:9000"),
		S3PublicEndpoint: env("S3_PUBLIC_ENDPOINT", ""),
		S3PublicUseSSL:   env("S3_PUBLIC_USE_SSL", "true") == "true",
		S3AccessKey:      env("S3_ACCESS_KEY", "minioadmin"),
		S3SecretKey:      env("S3_SECRET_KEY", "minioadmin"),
		S3Bucket:         env("S3_BUCKET", "wakili-archives"),
		S3Region:         env("S3_REGION", "us-east-1"),
		S3UseSSL:         env("S3_USE_SSL", "false") == "true",

		ATUsername: env("AT_USERNAME", ""),
		ATAPIKey:   env("AT_API_KEY", ""),
		ATSenderID: env("AT_SENDER_ID", "WAKILI"),
		ATBaseURL:  env("AT_BASE_URL", "https://api.sandbox.africastalking.com"),

		DarajaBaseURL:        env("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke"),
		DarajaConsumerKey:    env("DARAJA_CONSUMER_KEY", ""),
		DarajaConsumerSecret: env("DARAJA_CONSUMER_SECRET", ""),
		DarajaShortCode:      env("DARAJA_SHORT_CODE", "174379"),
		DarajaPasskey:        env("DARAJA_PASSKEY", ""),
		DarajaCallbackURL:    env("DARAJA_CALLBACK_URL", "http://localhost:8080/webhooks/daraja/callback"),

		JudiciaryBaseURL: env("JUDICIARY_BASE_URL", ""),

		SMTPHost:  env("SMTP_HOST", ""),
		SMTPPort:  env("SMTP_PORT", "587"),
		SMTPUser:  env("SMTP_USER", ""),
		SMTPPass:  env("SMTP_PASS", ""),
		EmailFrom: env("EMAIL_FROM", "no-reply@wakili.ai"),

		RateLimitPerMin:   envInt("RATE_LIMIT_PER_MIN", 300),
		RemindersInterval: envDur("REMINDERS_INTERVAL", 10*time.Minute),
		ReconcileInterval: envDur("RECONCILE_INTERVAL", 15*time.Minute),
	}
}
