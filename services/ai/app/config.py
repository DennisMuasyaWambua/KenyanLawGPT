"""Environment-driven configuration for the AI/RAG service."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes")


@dataclass
class Config:
    # Postgres (same cluster the gateway uses; app role, tenant schemas + public corpus)
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL", "postgresql://wakili_app:wakili_app_pw@localhost:5432/wakili"))

    # Neo4j graph
    neo4j_uri: str = field(default_factory=lambda: _env("NEO4J_URI", "bolt://localhost:7687"))
    neo4j_user: str = field(default_factory=lambda: _env("NEO4J_USER", "neo4j"))
    neo4j_password: str = field(default_factory=lambda: _env("NEO4J_PASSWORD", "wakili-neo4j"))

    # Object storage (tenant documents; read-only from this service)
    s3_endpoint: str = field(default_factory=lambda: _env("S3_ENDPOINT", "localhost:9000"))
    s3_access_key: str = field(default_factory=lambda: _env("S3_ACCESS_KEY", "minioadmin"))
    s3_secret_key: str = field(default_factory=lambda: _env("S3_SECRET_KEY", "minioadmin"))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET", "wakili-documents"))
    s3_use_ssl: bool = field(default_factory=lambda: _env_bool("S3_USE_SSL", False))

    # LLM — swappable provider (never hardcoded inline in business logic).
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "auto"))  # auto|anthropic|mock
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    # Claude Opus 4.8 for drafting/reasoning; Haiku for cheap intent classification.
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-4-8"))
    anthropic_fast_model: str = field(default_factory=lambda: _env("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5"))

    # Embeddings — voyage-law-2 (legal-domain, 1024-dim) when a key is present,
    # otherwise a deterministic hashing embedder so dev/tests run offline.
    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "auto"))  # auto|voyage|hash
    voyage_api_key: str = field(default_factory=lambda: _env("VOYAGE_API_KEY"))
    voyage_model: str = field(default_factory=lambda: _env("VOYAGE_MODEL", "voyage-law-2"))
    embedding_dim: int = field(default_factory=lambda: int(_env("EMBEDDING_DIM", "1024")))

    # gRPC server + mTLS
    grpc_port: int = field(default_factory=lambda: int(_env("GRPC_PORT", "50051")))
    mtls_ca_cert: str = field(default_factory=lambda: _env("MTLS_CA_CERT", "/certs/ca.crt"))
    mtls_server_cert: str = field(default_factory=lambda: _env("MTLS_SERVER_CERT", "/certs/ai.crt"))
    mtls_server_key: str = field(default_factory=lambda: _env("MTLS_SERVER_KEY", "/certs/ai.key"))
    mtls_disabled: bool = field(default_factory=lambda: _env_bool("MTLS_DISABLED", False))  # tests only

    # Health/metrics sidecar port (internal only)
    health_port: int = field(default_factory=lambda: int(_env("HEALTH_PORT", "8081")))

    # Public corpus ingestion pipeline
    kenyalaw_base: str = field(default_factory=lambda: _env("KENYALAW_BASE", "https://new.kenyalaw.org"))
    ingest_on_start: bool = field(default_factory=lambda: _env_bool("PUBLIC_INGEST_ON_START", True))
    ingest_offline_samples: bool = field(default_factory=lambda: _env_bool("INGEST_OFFLINE_SAMPLES", True))
    ingest_daily_seconds: int = field(default_factory=lambda: int(_env("INGEST_DAILY_SECONDS", str(24 * 3600))))
    ingest_weekly_seconds: int = field(default_factory=lambda: int(_env("INGEST_WEEKLY_SECONDS", str(7 * 24 * 3600))))

    env: str = field(default_factory=lambda: _env("APP_ENV", "dev"))


def load() -> Config:
    return Config()
