"""LLM provider abstraction.

Business logic never calls a vendor SDK inline — everything goes through
``LLMProvider``. The default is Claude (Anthropic API); ``MockProvider``
keeps the whole platform demoable offline and makes the isolation tests
independent of any external service.
"""
from __future__ import annotations

import re
from typing import AsyncIterator, Optional, Protocol

from .config import Config
from .logging_setup import log

# Reasoning models served through Ollama (e.g. DeepSeek-R1) prepend their chain
# of thought as a <think>...</think> block before the actual answer. The rest of
# the platform expects a clean, citable answer, so the block is stripped here —
# in the provider — rather than leaking into synthesized answers or drafts.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_reasoning(text: str) -> str:
    if "<think>" not in text and "</think>" in text:
        # opening tag was cut off (truncated budget / mid-stream): keep the tail
        text = text.rsplit("</think>", 1)[-1]
    else:
        text = _THINK_RE.sub("", text)
    return text.strip()

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
            return _strip_reasoning(resp.json().get("response", ""))

    async def stream(self, system: str, prompt: str, max_tokens: int = 8192) -> AsyncIterator[str]:
        import json as _json

        payload = {
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        # Reasoning models stream their <think>...</think> block first; suppress
        # it token-by-token (tags may split across chunks) so only the answer is
        # streamed to the client. "gate": deciding -> thinking -> passthrough.
        buf, gate = "", "deciding"
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
                    if not piece:
                        continue
                    if gate == "passthrough":
                        yield piece
                        continue
                    buf += piece
                    if gate == "deciding":
                        if "<think>" in buf.lstrip()[:8]:
                            gate = "thinking"
                        elif len(buf) >= 8:  # no think block opening — flush and pass through
                            gate, out, buf = "passthrough", buf, ""
                            yield out
                        continue
                    if gate == "thinking":
                        end = buf.find("</think>")
                        if end != -1:
                            rest = buf[end + len("</think>"):].lstrip()
                            gate, buf = "passthrough", ""
                            if rest:
                                yield rest
        if gate == "deciding" and buf:  # short response, never decided — emit it
            yield buf


class GMICloudProvider:
    """A GMI Cloud hosted model via its OpenAI-compatible chat API.

    One instance wraps exactly one model. The model is chosen at construction
    (defaulting to ``cfg.gmi_cloud_model``) so the same class serves both the
    DeepSeek-R1 distill and Qwen3-235B during evaluation — the A/B tooling
    spins up two instances with different ``model`` strings and the same config.

    Two model-specific behaviours are handled here so business logic stays
    provider-agnostic:
      * <think>-block stripping is applied *only* to chain-of-thought models
        (the DeepSeek distill), never to Qwen3-Instruct, whose answer is final.
      * per-request token usage + latency are logged, because Qwen3 is a paid
        endpoint and we want real cost signal during testing, not just latency.
    """

    def __init__(self, cfg: Config, model: Optional[str] = None) -> None:
        import httpx  # already a service dependency

        self._httpx = httpx
        self._cfg = cfg
        self._base = cfg.gmi_cloud_base_url.rstrip("/")
        self._api_key = cfg.gmi_cloud_api_key
        self._model = model or cfg.gmi_cloud_model
        self._reasoning = self._is_reasoning_model(self._model, cfg)
        # Populated after every complete() so callers (e.g. the A/B script) can
        # print cost alongside the answer without re-parsing the response.
        self.last_usage: dict = {}
        self.last_latency_ms: float = 0.0

    @staticmethod
    def _is_reasoning_model(model: str, cfg: Config) -> bool:
        """Whether this model emits a <think>...</think> chain of thought that
        must be stripped before the answer is used. True for the DeepSeek
        distill; false for Qwen3-Instruct and other instruct-tuned models."""
        if model == cfg.gmi_cloud_deepseek_model:
            return True
        m = model.lower()
        return "deepseek-r1" in m or "-r1-" in m or m.endswith("-r1")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _guard_synthetic(self) -> None:
        """Synthetic-data-only gate: outside prod, refuse to send anything to
        the external paid endpoint unless the operator has attested the corpus
        is synthetic. Applies to every GMI model (Qwen3 and DeepSeek alike)."""
        if self._cfg.env != "prod" and self._cfg.gmi_synthetic_only and not self._cfg.gmi_synthetic_data_ok:
            raise RuntimeError(
                "GMI Cloud call blocked in non-prod: the synthetic-data-only gate is on. "
                "Set GMI_SYNTHETIC_DATA_OK=true only when the loaded corpus is synthetic "
                "(no real client documents), or GMI_SYNTHETIC_ONLY=false to disable the gate."
            )

    def _log_usage(self, usage: dict, latency_ms: float) -> None:
        self.last_usage = usage or {}
        self.last_latency_ms = latency_ms
        log().info(
            "gmi_cloud call model=%s latency_ms=%.0f prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            self._model, latency_ms,
            (usage or {}).get("prompt_tokens"), (usage or {}).get("completion_tokens"),
            (usage or {}).get("total_tokens"),
        )

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048, fast: bool = False) -> str:
        import time

        self._guard_synthetic()
        payload = {
            "model": self._model,
            "max_tokens": self._answer_budget(max_tokens, fast),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        started = time.perf_counter()
        async with self._httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{self._base}/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        self._log_usage(data.get("usage") or {}, (time.perf_counter() - started) * 1000)
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content") or ""
        if not text.strip():
            # Some reasoning models (e.g. Nemotron) put their chain-of-thought in a
            # separate `reasoning`/`reasoning_content` field and, when the budget is
            # exhausted thinking, leave `content` empty. Salvage the reasoning text
            # so callers get an answer instead of a blank that renders as
            # "citations only". _strip_reasoning below also drops any <think> wrap.
            salvaged = msg.get("reasoning") or msg.get("reasoning_content") or ""
            if salvaged.strip():
                log().warning(
                    "gmi_cloud empty content, salvaging reasoning field (model=%s) — "
                    "consider raising GMI_CLOUD_REASONING_HEADROOM", self._model)
                text = salvaged
        # Only chain-of-thought models wrap the answer in <think>...</think>.
        return _strip_reasoning(text) if self._reasoning else text.strip()

    def _answer_budget(self, max_tokens: int, fast: bool) -> int:
        """Effective ``max_tokens`` for the request. Reasoning models bound
        reasoning+answer together, so add headroom on top of the caller's answer
        budget — otherwise the trace eats it all and ``content`` is empty. Cheap
        ``fast`` classification calls keep their tight budget; instruct models
        stop at EOS and simply ignore any unused room."""
        if fast:
            return max_tokens
        return max_tokens + max(0, self._cfg.gmi_cloud_reasoning_headroom)

    async def stream(self, system: str, prompt: str, max_tokens: int = 8192) -> AsyncIterator[str]:
        import json as _json

        self._guard_synthetic()
        payload = {
            "model": self._model,
            "max_tokens": self._answer_budget(max_tokens, fast=False),
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        # For reasoning models, suppress the leading <think>...</think> block
        # token-by-token (tags may split across chunks) exactly like Ollama; for
        # instruct models pass every delta straight through.
        buf, gate = "", ("deciding" if self._reasoning else "passthrough")
        async with self._httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self._base}/chat/completions", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data)
                    except ValueError:
                        continue
                    piece = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                    if not piece:
                        continue
                    if gate == "passthrough":
                        yield piece
                        continue
                    buf += piece
                    if gate == "deciding":
                        if "<think>" in buf.lstrip()[:8]:
                            gate = "thinking"
                        elif len(buf) >= 8:  # no think block — flush and pass through
                            gate, out, buf = "passthrough", buf, ""
                            yield out
                        continue
                    if gate == "thinking":
                        end = buf.find("</think>")
                        if end != -1:
                            rest = buf[end + len("</think>"):].lstrip()
                            gate, buf = "passthrough", ""
                            if rest:
                                yield rest
        if gate == "deciding" and buf:  # short response, never decided — emit it
            yield buf


class MockProvider:
    """Deterministic offline provider: answers by quoting the highest-ranked
    context, drafts by returning the grounded template. Clearly watermarked."""

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048, fast: bool = False) -> str:
        if "classify" in system.lower():
            p = prompt.lower()
            if any(w in p for w in ("draft", "prepare", "write a")):
                return "drafting"
            if any(w in p for w in ("file", "our client", "this case")):
                return "file_reasoning"
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


class FallbackProvider:
    """Tries a primary provider and, on failure, transparently falls back to a
    secondary one (e.g. GMI Cloud primary, on-box Ollama fallback).

    For streaming, the fallback only applies when the primary fails *before*
    emitting its first token — a mid-stream failure can't be replayed without
    duplicating output, so it propagates."""

    def __init__(self, primary: LLMProvider, secondary: LLMProvider,
                 primary_name: str = "primary", secondary_name: str = "fallback") -> None:
        self._primary = primary
        self._secondary = secondary
        self._pn = primary_name
        self._sn = secondary_name

    async def complete(self, system: str, prompt: str, max_tokens: int = 2048, fast: bool = False) -> str:
        try:
            return await self._primary.complete(system, prompt, max_tokens, fast=fast)
        except Exception as e:
            log().warning("LLM primary (%s) complete failed, falling back to %s: %s", self._pn, self._sn, e)
            return await self._secondary.complete(system, prompt, max_tokens, fast=fast)

    async def stream(self, system: str, prompt: str, max_tokens: int = 8192) -> AsyncIterator[str]:
        agen = self._primary.stream(system, prompt, max_tokens)
        try:
            first = await agen.__anext__()
        except StopAsyncIteration:
            return
        except Exception as e:
            log().warning("LLM primary (%s) stream failed before first token, falling back to %s: %s",
                          self._pn, self._sn, e)
            async for tok in self._secondary.stream(system, prompt, max_tokens):
                yield tok
            return
        yield first
        async for tok in agen:
            yield tok


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


def _build_named(cfg: Config, name: str) -> LLMProvider:
    """Construct a provider by explicit name (no 'auto' resolution)."""
    if name == "anthropic":
        return AnthropicProvider(cfg)
    if name == "ollama":
        return OllamaProvider(cfg)
    if name == "gmi":
        return GMICloudProvider(cfg)
    if name == "mock":
        return MockProvider()
    raise ValueError(f"unknown LLM provider: {name!r}")


def _make_primary(cfg: Config) -> LLMProvider:
    # Explicit selection wins.
    if cfg.llm_provider in ("anthropic", "ollama", "gmi", "mock"):
        return _build_named(cfg, cfg.llm_provider)
    # auto: Claude if a key is present, else a reachable local Ollama, else mock.
    if cfg.anthropic_api_key:
        return AnthropicProvider(cfg)
    if _ollama_reachable(cfg):
        log().info("auto LLM: using local Ollama at %s (model %s)", cfg.ollama_base_url, cfg.ollama_model)
        return OllamaProvider(cfg)
    log().warning("No ANTHROPIC_API_KEY and no reachable Ollama — using MockProvider (offline demo mode)")
    return MockProvider()


def make_llm(cfg: Config) -> LLMProvider:
    primary = _make_primary(cfg)
    fb = (cfg.llm_fallback_provider or "").strip()
    if fb and fb != cfg.llm_provider:
        try:
            secondary = _build_named(cfg, fb)
        except ValueError:
            log().warning("ignoring unknown LLM_FALLBACK_PROVIDER=%r", fb)
            return primary
        log().info("LLM fallback enabled: primary=%s secondary=%s", cfg.llm_provider, fb)
        return FallbackProvider(primary, secondary, cfg.llm_provider or "primary", fb)
    return primary


def make_optional_llm(cfg: Config) -> Optional[LLMProvider]:
    provider = make_llm(cfg)
    return provider
