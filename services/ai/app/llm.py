"""LLM provider abstraction.

Business logic never calls a vendor SDK inline — everything goes through
``LLMProvider``. The default is Claude (Anthropic API); ``MockProvider``
keeps the whole platform demoable offline and makes the isolation tests
independent of any external service.
"""
from __future__ import annotations

from typing import AsyncIterator, Optional, Protocol

from .config import Config
from .logging_setup import log

# System instruction attached to every call that sees tenant-private context:
# confidential material must never leak into cross-tenant caches, logs, or
# training data, and provenance labels must be respected.
CONFIDENTIALITY_PREAMBLE = (
    "Some context chunks are labeled TENANT_PRIVATE: they are confidential "
    "attorney work product belonging to a single law firm. Never reveal that "
    "material except in this answer for this firm, never attribute it to a "
    "public source, and clearly distinguish citations of public law from "
    "firm-internal documents. Content labeled PUBLIC is Kenyan public law."
)


class LLMProvider(Protocol):
    async def complete(self, system: str, prompt: str, max_tokens: int = 2048, fast: bool = False) -> str: ...

    def stream(self, system: str, prompt: str, max_tokens: int = 8192) -> AsyncIterator[str]: ...


class AnthropicProvider:
    """Claude via the official Anthropic SDK. Opus 4.8 with adaptive thinking
    for reasoning/drafting; Haiku 4.5 for cheap classification calls."""

    def __init__(self, cfg: Config) -> None:
        import anthropic  # imported here so mock-mode deployments don't need the key

        self._client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)
        self._model = cfg.anthropic_model
        self._fast_model = cfg.anthropic_fast_model

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048, fast: bool = False) -> str:
        kwargs: dict = {}
        model = self._fast_model if fast else self._model
        if not fast:
            kwargs["thinking"] = {"type": "adaptive"}
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    async def stream(self, system: str, prompt: str, max_tokens: int = 8192) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OllamaProvider:
    """Local llama3 via Ollama's native HTTP API. Used for on-prem / strict
    data-residency deployments where prompts must not leave the box. Same
    interface as AnthropicProvider so business logic is provider-agnostic."""

    def __init__(self, cfg: Config) -> None:
        import httpx  # already a service dependency

        self._httpx = httpx
        self._base = cfg.ollama_base_url.rstrip("/")
        self._model = cfg.ollama_model
        self._fast_model = cfg.ollama_fast_model

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048, fast: bool = False) -> str:
        model = self._fast_model if fast else self._model
        payload = {
            "model": model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        async with self._httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{self._base}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")

    async def stream(self, system: str, prompt: str, max_tokens: int = 8192) -> AsyncIterator[str]:
        import json as _json

        payload = {
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        async with self._httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self._base}/api/generate", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = _json.loads(line)
                    except ValueError:
                        continue
                    piece = chunk.get("response", "")
                    if piece:
                        yield piece


class MockProvider:
    """Deterministic offline provider: answers by quoting the highest-ranked
    context, drafts by returning the grounded template. Clearly watermarked."""

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048, fast: bool = False) -> str:
        if "classify" in system.lower():
            p = prompt.lower()
            if any(w in p for w in ("draft", "prepare", "write a")):
                return "drafting"
            if any(w in p for w in ("matter", "our client", "this case")):
                return "matter_reasoning"
            if any(w in p for w in ("case law", "precedent", "decided", "ruling", "judgment")):
                return "case_law_research"
            return "statute_lookup"
        # Answer synthesis: echo the context section (between CONTEXT markers).
        body = prompt
        if "--- CONTEXT ---" in prompt:
            body = prompt.split("--- CONTEXT ---", 1)[1]
        lines = [ln for ln in body.splitlines() if ln.strip()][:12]
        return (
            "[offline mock answer — set ANTHROPIC_API_KEY for grounded LLM output]\n"
            + "\n".join(lines[:8])
        )

    async def stream(self, system: str, prompt: str, max_tokens: int = 8192) -> AsyncIterator[str]:
        text = await self.complete(system, prompt, max_tokens)
        for i in range(0, len(text), 24):
            yield text[i : i + 24]


def _ollama_reachable(cfg: Config) -> bool:
    """Best-effort liveness probe so 'auto' only picks Ollama when it answers."""
    import httpx

    if not cfg.ollama_base_url:
        return False
    try:
        r = httpx.get(f"{cfg.ollama_base_url.rstrip('/')}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def make_llm(cfg: Config) -> LLMProvider:
    # Explicit selection wins.
    if cfg.llm_provider == "anthropic":
        return AnthropicProvider(cfg)
    if cfg.llm_provider == "ollama":
        return OllamaProvider(cfg)
    if cfg.llm_provider == "mock":
        return MockProvider()
    # auto: Claude if a key is present, else a reachable local Ollama, else mock.
    if cfg.anthropic_api_key:
        return AnthropicProvider(cfg)
    if _ollama_reachable(cfg):
        log().info("auto LLM: using local Ollama at %s (model %s)", cfg.ollama_base_url, cfg.ollama_model)
        return OllamaProvider(cfg)
    log().warning("No ANTHROPIC_API_KEY and no reachable Ollama — using MockProvider (offline demo mode)")
    return MockProvider()


def make_optional_llm(cfg: Config) -> Optional[LLMProvider]:
    provider = make_llm(cfg)
    return provider
