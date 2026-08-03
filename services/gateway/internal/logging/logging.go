package logging

import (
	"context"
	"log/slog"
	"os"
)

type ctxKey string

const TraceIDKey ctxKey = "trace_id"

var base *slog.Logger

func Init(env string) {
	level := slog.LevelInfo
	if env == "dev" {
		level = slog.LevelDebug
	}
	base = slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})).
		With("service", "gateway")
	slog.SetDefault(base)
}

// L returns a logger carrying the request's trace id, if present.
func L(ctx context.Context) *slog.Logger {
	if base == nil {
		Init("dev")
	}
	if tid, ok := ctx.Value(TraceIDKey).(string); ok && tid != "" {
		return base.With("trace_id", tid)
	}
	return base
}

func WithTrace(ctx context.Context, traceID string) context.Context {
	return context.WithValue(ctx, TraceIDKey, traceID)
}
