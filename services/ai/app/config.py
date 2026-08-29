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


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None or not v.strip():
        return default
    try:
        return int(v)
    except ValueError:
        return default


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
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET", "wakili-archives"))
    s3_use_ssl: bool = field(default_factory=lambda: _env_bool("S3_USE_SSL", False))

    # Redis — backs the async firm-ingestion job queue. Unreachable => the queue
    # transparently falls back to an in-process worker (single-instance dev).
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379"))

    # LLM — swappable provider (never hardcoded inline in business logic).
    # auto|anthropic|ollama|mock. "auto" prefers Claude (if key), then a
    # reachable local Ollama, then the deterministic offline mock.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "auto"))
    # Optional secondary provider used when the primary fails (e.g. GMI Cloud
    # down/rate-limited => fall back to on-box Ollama). Empty => no fallback.
    llm_fallback_provider: str = field(default_factory=lambda: _env("LLM_FALLBACK_PROVIDER", ""))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    # Claude Opus 4.8 for drafting/reasoning; Haiku for cheap intent classification.
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-4-8"))
    anthropic_fast_model: str = field(default_factory=lambda: _env("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5"))

    # Local llama3 via Ollama (on-prem / data-residency deployments). Empty base
    # url or unreachable server => auto falls through to the mock.
    ollama_base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3"))
    ollama_fast_model: str = field(default_factory=lambda: _env("OLLAMA_FAST_MODEL", "llama3.2:1b"))

    # GMI Cloud — OpenAI-compatible hosted inference. Used to evaluate multiple
    # hosted models (DeepSeek-R1 distill vs Qwen3-235B) before picking one for
    # production. The model string is chosen per GMICloudProvider instance:
    # ``gmi_cloud_model`` is the default, but the A/B tooling instantiates the
    # provider with ``gmi_cloud_deepseek_model`` / ``gmi_cloud_qwen_model``.
    gmi_cloud_base_url: str = field(default_factory=lambda: _env("GMI_CLOUD_BASE_URL", "https://api.gmi-serving.com/v1"))
    gmi_cloud_api_key: str = field(default_factory=lambda: _env("GMI_CLOUD_API_KEY"))
    gmi_cloud_model: str = field(default_factory=lambda: _env(
        "GMI_CLOUD_MODEL", "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"))
    # DeepSeek distill is a chain-of-thought model (emits <think>...</think>);
    # Qwen3-235B-Instruct is not. The provider strips reasoning only for the
    # former — see GMICloudProvider._is_reasoning_model.
    gmi_cloud_deepseek_model: str = field(default_factory=lambda: _env(
        "GMI_CLOUD_DEEPSEEK_MODEL", "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"))
    gmi_cloud_qwen_model: str = field(default_factory=lambda: _env(
        "GMI_CLOUD_QWEN_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8"))
    # Guardrail: Qwen3 is a *paid* endpoint and GMI Cloud is external. Outside
    # prod, refuse GMI calls unless the operator attests (GMI_SYNTHETIC_DATA_OK)
    # that the loaded corpus is synthetic — no real client documents leave the
    # box to a paid third party during model evaluation.
    gmi_synthetic_only: bool = field(default_factory=lambda: _env_bool("GMI_SYNTHETIC_ONLY", True))
    gmi_synthetic_data_ok: bool = field(default_factory=lambda: _env_bool("GMI_SYNTHETIC_DATA_OK", False))
    # Chain-of-thought GMI models (DeepSeek-R1 distill, Nemotron) spend part of
    # their token budget *reasoning* before emitting the visible answer — either
    # inline in <think>...</think> or in a separate `reasoning` field. A request's
    # `max_tokens` bounds reasoning+answer combined, so a small answer budget
    # (research synthesis asks for 2048, graph reasoning 1024) gets fully consumed
    # by the reasoning trace and `content` comes back EMPTY — the research UI then
    # renders citations with no answer. This headroom is added on top of the
    # caller's requested answer budget so the answer always has room to land.
    gmi_cloud_reasoning_headroom: int = field(
        default_factory=lambda: _env_int("GMI_CLOUD_REASONING_HEADROOM", 6144))

    # Speech-to-text (multilingual) for client-conversation recordings. Audio is
    # privileged/KDPA-sensitive, so "auto" only ever picks a LOCAL Whisper or the
    # offline mock — the cloud provider must be selected explicitly.
    # auto|whisper|openai|mock.
    transcribe_provider: str = field(default_factory=lambda: _env("TRANSCRIBE_PROVIDER", "auto"))
    # 'small' balances Swahili/English code-switching against CPU cost (was 'base').
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    transcribe_language: str = field(default_factory=lambda: _env("TRANSCRIBE_LANGUAGE", "auto"))  # auto-detect
    transcribe_base_url: str = field(default_factory=lambda: _env("TRANSCRIBE_BASE_URL", "https://api.openai.com/v1"))
    transcribe_api_key: str = field(default_factory=lambda: _env("TRANSCRIBE_API_KEY"))
    transcribe_openai_model: str = field(default_factory=lambda: _env("TRANSCRIBE_OPENAI_MODEL", "whisper-1"))
    # Meeting-recording processor: how often to scan tenants for pending audio.
    recordings_poll_seconds: int = field(default_factory=lambda: int(_env("RECORDINGS_POLL_SECONDS", "20")))

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

    # Feature flags — each new capability ships dark and is enabled per pilot
    # firm incrementally rather than all at once.
    enable_firm_ingestion: bool = field(default_factory=lambda: _env_bool("ENABLE_FIRM_INGESTION", False))
    enable_judge_reasoning: bool = field(default_factory=lambda: _env_bool("ENABLE_JUDGE_REASONING", False))
    enable_auto_update: bool = field(default_factory=lambda: _env_bool("ENABLE_AUTO_UPDATE", False))

    env: str = field(default_factory=lambda: _env("APP_ENV", "dev"))


def load() -> Config:
    return Config()
