package storage

import (
	"bytes"
	"context"
	"fmt"
	"mime"
	"net/url"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"github.com/wakiliai/gateway/internal/config"
)

// ObjectStore wraps an S3-compatible backend (Cloudflare R2 in production —
// S3_ENDPOINT=<account>.r2.cloudflarestorage.com, S3_REGION=auto — MinIO in dev). Isolation is prefix-per-tenant: every key is forced under
// tenants/<tenant_id>/ and presigned URLs are only ever issued by the gateway
// for the authenticated tenant's prefix.
//
// Two clients: `client` talks to the in-network endpoint for server-side ops;
// `presigner` is configured with the browser-reachable endpoint (presigning
// is offline signature computation, so it never dials out) — S3 signatures
// bind the Host header, so URLs must be minted for the host the browser uses.
type ObjectStore struct {
	client    *minio.Client
	presigner *minio.Client
	bucket    string
}

func New(cfg *config.Config) (*ObjectStore, error) {
	// Region is pinned so presigning is a pure offline signature computation
	// (no getBucketLocation round-trip to the endpoint at sign time).
	cli, err := minio.New(cfg.S3Endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(cfg.S3AccessKey, cfg.S3SecretKey, ""),
		Secure: cfg.S3UseSSL,
		Region: cfg.S3Region,
	})
	if err != nil {
		return nil, err
	}
	// The presigner signs browser-reachable URLs for the PUBLIC endpoint, which
	// is typically TLS-fronted even when the in-network endpoint is plaintext —
	// hence its own S3PublicUseSSL flag rather than sharing S3UseSSL.
	presigner := cli
	if cfg.S3PublicEndpoint != "" && cfg.S3PublicEndpoint != cfg.S3Endpoint {
		presigner, err = minio.New(cfg.S3PublicEndpoint, &minio.Options{
			Creds:  credentials.NewStaticV4(cfg.S3AccessKey, cfg.S3SecretKey, ""),
			Secure: cfg.S3PublicUseSSL,
			Region: cfg.S3Region,
		})
		if err != nil {
			return nil, err
		}
	}
	return &ObjectStore{client: cli, presigner: presigner, bucket: cfg.S3Bucket}, nil
}

func (s *ObjectStore) EnsureBucket(ctx context.Context) error {
	exists, err := s.client.BucketExists(ctx, s.bucket)
	if err != nil {
		return err
	}
	if !exists {
		return s.client.MakeBucket(ctx, s.bucket, minio.MakeBucketOptions{})
	}
	return nil
}

func Key(tenantID, archiveID, filename string) string {
	return fmt.Sprintf("tenants/%s/archives/%s/%s", tenantID, archiveID, filename)
}

func (s *ObjectStore) tenantGuard(tenantID, key string) error {
	prefix := "tenants/" + tenantID + "/"
	if len(key) < len(prefix) || key[:len(prefix)] != prefix {
		return fmt.Errorf("object key outside tenant prefix")
	}
	return nil
}

func (s *ObjectStore) PresignPut(ctx context.Context, tenantID, key string) (string, error) {
	if err := s.tenantGuard(tenantID, key); err != nil {
		return "", err
	}
	u, err := s.presigner.PresignedPutObject(ctx, s.bucket, key, 15*time.Minute)
	if err != nil {
		return "", err
	}
	return u.String(), nil
}

func (s *ObjectStore) PresignGet(ctx context.Context, tenantID, key string) (string, error) {
	if err := s.tenantGuard(tenantID, key); err != nil {
		return "", err
	}
	u, err := s.presigner.PresignedGetObject(ctx, s.bucket, key, 15*time.Minute, nil)
	if err != nil {
		return "", err
	}
	return u.String(), nil
}

// PresignDownload is PresignGet with the response served as an attachment
// named filename, so a browser saves the file instead of navigating to it.
func (s *ObjectStore) PresignDownload(ctx context.Context, tenantID, key, filename string) (string, error) {
	if err := s.tenantGuard(tenantID, key); err != nil {
		return "", err
	}
	params := url.Values{}
	params.Set("response-content-disposition", mime.FormatMediaType("attachment", map[string]string{"filename": filename}))
	u, err := s.presigner.PresignedGetObject(ctx, s.bucket, key, 15*time.Minute, params)
	if err != nil {
		return "", err
	}
	return u.String(), nil
}

// Exists reports whether an object is present under the tenant's prefix.
func (s *ObjectStore) Exists(ctx context.Context, tenantID, key string) (bool, error) {
	if err := s.tenantGuard(tenantID, key); err != nil {
		return false, err
	}
	_, err := s.client.StatObject(ctx, s.bucket, key, minio.StatObjectOptions{})
	if err != nil {
		if minio.ToErrorResponse(err).StatusCode == 404 {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (s *ObjectStore) Put(ctx context.Context, tenantID, key string, body []byte, contentType string) error {
	if err := s.tenantGuard(tenantID, key); err != nil {
		return err
	}
	_, err := s.client.PutObject(ctx, s.bucket, key, bytes.NewReader(body), int64(len(body)),
		minio.PutObjectOptions{ContentType: contentType})
	return err
}

func (s *ObjectStore) Delete(ctx context.Context, tenantID, key string) error {
	if err := s.tenantGuard(tenantID, key); err != nil {
		return err
	}
	return s.client.RemoveObject(ctx, s.bucket, key, minio.RemoveObjectOptions{})
}
