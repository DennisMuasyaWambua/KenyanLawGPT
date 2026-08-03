package grpcclient

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"os"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"

	wakiliv1 "github.com/wakiliai/gateway/gen/wakiliv1"
	"github.com/wakiliai/gateway/internal/config"
)

// AIClient is the SOLE caller of the Python AI service, always over gRPC with
// mutual TLS. The frontend never reaches the AI service directly.
type AIClient struct {
	Retrieval wakiliv1.RetrievalServiceClient
	Reasoning wakiliv1.ReasoningServiceClient
	Drafting  wakiliv1.DraftingServiceClient
	Ingestion wakiliv1.IngestionServiceClient
	conn      *grpc.ClientConn
}

func Dial(cfg *config.Config) (*AIClient, error) {
	cert, err := tls.LoadX509KeyPair(cfg.MTLSClientCert, cfg.MTLSClientKey)
	if err != nil {
		return nil, fmt.Errorf("load client cert: %w", err)
	}
	caPEM, err := os.ReadFile(cfg.MTLSCACert)
	if err != nil {
		return nil, fmt.Errorf("read CA cert: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("invalid CA cert")
	}
	creds := credentials.NewTLS(&tls.Config{
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
		ServerName:   cfg.AIGRPCServerName,
		MinVersion:   tls.VersionTLS12,
	})
	conn, err := grpc.NewClient(cfg.AIGRPCAddr, grpc.WithTransportCredentials(creds))
	if err != nil {
		return nil, err
	}
	return &AIClient{
		Retrieval: wakiliv1.NewRetrievalServiceClient(conn),
		Reasoning: wakiliv1.NewReasoningServiceClient(conn),
		Drafting:  wakiliv1.NewDraftingServiceClient(conn),
		Ingestion: wakiliv1.NewIngestionServiceClient(conn),
		conn:      conn,
	}, nil
}

func (c *AIClient) Close() error { return c.conn.Close() }

// Ctx attaches the authenticated tenant id and the trace id as gRPC metadata.
// The Python interceptor rejects any request whose TenantContext message does
// not match this metadata — the belt to the message's braces.
func Ctx(ctx context.Context, tenantID, traceID string) context.Context {
	return metadata.AppendToOutgoingContext(ctx,
		"x-tenant-id", tenantID,
		"x-trace-id", traceID,
	)
}

// TC builds the TenantContext message from the authenticated tenant record.
func TC(tenantID, plan string, residencyKE bool) *wakiliv1.TenantContext {
	return &wakiliv1.TenantContext{
		TenantId:        tenantID,
		PlanTier:        plan,
		DataResidencyKe: residencyKE,
	}
}
