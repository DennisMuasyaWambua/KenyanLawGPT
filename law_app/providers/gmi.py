"""GMI Cloud generation provider (OpenAI-compatible chat completions).

Wraps GMI Cloud's OpenAI-compatible API so WakiliAI can run generation through
GMI-hosted models (DeepSeek-R1-Distill, Qwen3-235B, ...). One provider instance
is bound to one model, chosen at construction time via ``model=`` (defaulting to
``GMI_CLOUD_MODEL``), so both models can be referenced without editing code.

Every call passes through policy gates, all of which **fail closed** so the
orchestrator can fall back to Ollama rather than erroring the user out:

* **Data-sensitivity** — real client/case-document prompts are refused unless
  ``GMI_CLOUD_ALLOW_REAL_DATA`` is true. Synthetic / public-corpus prompts always
  flow. Sensitivity is *declared by the caller* (``contains_client_data``); it is
  never inferred from prompt text (that would be unreliable and could leak).
* **Daily spend cap** — once the day's accrued USD reaches
  ``GMI_CLOUD_DAILY_USD_CAP`` further calls are refused until the next UTC day.
* **Per-request output cap** — every call bounds output with ``max_tokens``.

Chain-of-thought models (the DeepSeek R1 distill) emit ``<think>...</think>``
scratchpads, which are stripped. Instruct models (Qwen3) are not, so stripping is
decided per active model — never applied blanket to every GMI response.
"""
import json
import logging
import re
import time
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Non-greedy, dot-matches-newline: remove chain-of-thought scratchpads.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _partial_suffix_len(text, tag):
    """Length of the longest suffix of ``text`` that is a prefix of ``tag``.

    Used by the streaming <think> filter to hold back a few trailing chars that
    might be the start of a tag split across chunk boundaries (e.g. ``"<thi"``),
    so a tag straddling two SSE deltas is still recognised.
    """
    lo = (text or "").lower()
    for n in range(min(len(tag), len(lo)), 0, -1):
        if lo.endswith(tag[:n]):
            return n
    return 0


class _ThinkStreamFilter:
    """Stateful removal of ``<think>...</think>`` spans from a token stream.

    Chain-of-thought models emit the scratchpad as ordinary streamed tokens, so
    it must be stripped incrementally — the tags can land in the middle of a
    delta or straddle two of them. ``feed`` returns the emittable text seen so
    far; ``flush`` returns anything still buffered once the stream ends.
    """

    def __init__(self):
        self._buf = ""
        self._in_think = False

    def feed(self, chunk):
        self._buf += chunk
        out = []
        while self._buf:
            if not self._in_think:
                idx = self._buf.lower().find(_THINK_OPEN)
                if idx == -1:
                    # Emit everything except a possible partial opening tag.
                    hold = _partial_suffix_len(self._buf, _THINK_OPEN)
                    cut = len(self._buf) - hold
                    out.append(self._buf[:cut])
                    self._buf = self._buf[cut:]
                    break
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(_THINK_OPEN):]
                self._in_think = True
            else:
                idx = self._buf.lower().find(_THINK_CLOSE)
                if idx == -1:
                    # Drop everything except a possible partial closing tag.
                    hold = _partial_suffix_len(self._buf, _THINK_CLOSE)
                    self._buf = self._buf[len(self._buf) - hold:]
                    break
                self._buf = self._buf[idx + len(_THINK_CLOSE):]
                self._in_think = False
        return "".join(out)

    def flush(self):
        # Outside a think block, whatever remains is real output; inside one,
        # an unclosed block is discarded.
        if not self._in_think:
            out, self._buf = self._buf, ""
            return out
        self._buf = ""
        return ""


class GMICloudError(Exception):
    """Transient/remote failure (HTTP, network, timeout, malformed payload)."""


class GMICloudDisabled(Exception):
    """Call refused by a policy gate (data-sensitivity or budget)."""


class GMICloudBudgetExceeded(GMICloudDisabled):
    """The daily spend cap has been reached."""


@dataclass
class GMIResult:
    text: str            # post-processing (think-stripped for CoT models)
    raw_text: str        # exactly what the model returned
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


@dataclass
class StreamChunk:
    """One streamed piece, tagged by role.

    ``kind`` is ``"content"`` (part of the answer) or ``"reasoning"`` (the
    model's chain-of-thought, emitted by reasoning models in a separate field).
    Splitting them lets the transport render reasoning as a "thinking…" indicator
    without polluting the answer text.
    """
    kind: str            # "content" | "reasoning"
    text: str


def _is_cot_model(model: str) -> bool:
    """True for chain-of-thought models that emit <think> scratchpads."""
    m = (model or "").lower()
    return "r1" in m or "distill" in m or "-o1" in m or "reasoner" in m


class GMICloudProvider:
    def __init__(self, model=None, base_url=None, api_key=None,
                 strip_think=None, timeout=None):
        self.model = model or getattr(settings, "GMI_CLOUD_MODEL", "") or ""
        if not self.model:
            raise GMICloudError("No GMI model configured (set GMI_CLOUD_MODEL).")
        self.base_url = (base_url or settings.GMI_CLOUD_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.GMI_CLOUD_API_KEY
        # Conditional on the active model unless explicitly overridden.
        self.strip_think = _is_cot_model(self.model) if strip_think is None else strip_think
        self.timeout = timeout or getattr(settings, "GMI_CLOUD_TIMEOUT", 120)

    # -- pricing / spend ----------------------------------------------------
    def _price_per_1m(self):
        """(input, output) USD per 1M tokens for the active model."""
        if self.model == settings.GMI_CLOUD_QWEN_MODEL:
            return (settings.GMI_CLOUD_QWEN_PRICE_INPUT_PER_1M,
                    settings.GMI_CLOUD_QWEN_PRICE_OUTPUT_PER_1M)
        if self.model == settings.GMI_CLOUD_DEEPSEEK_MODEL:
            return (settings.GMI_CLOUD_DEEPSEEK_PRICE_INPUT_PER_1M,
                    settings.GMI_CLOUD_DEEPSEEK_PRICE_OUTPUT_PER_1M)
        return (0.0, 0.0)

    def _cost_usd(self, prompt_tokens, completion_tokens):
        in_price, out_price = self._price_per_1m()
        return (prompt_tokens / 1_000_000.0) * in_price + \
               (completion_tokens / 1_000_000.0) * out_price

    # -- gates --------------------------------------------------------------
    def _check_data_gate(self, contains_client_data):
        if contains_client_data and not settings.GMI_CLOUD_ALLOW_REAL_DATA:
            raise GMICloudDisabled(
                "GMI Cloud is not permitted for real client/case data "
                "(set GMI_CLOUD_ALLOW_REAL_DATA=true to allow)."
            )

    def _check_budget(self):
        from law_app.models import GmiSpend

        cap = settings.GMI_CLOUD_DAILY_USD_CAP
        spent = GmiSpend.today_spend_usd()
        if cap and spent >= cap:
            raise GMICloudBudgetExceeded(
                f"GMI daily spend cap reached (${spent:.4f} >= ${cap:.2f})."
            )

    # -- generation ---------------------------------------------------------
    def generate(self, prompt, *, system=None, contains_client_data=True,
                 temperature=0.1, max_tokens=None):
        """Run one chat completion. Raises GMICloudDisabled / GMICloudError."""
        self._check_data_gate(contains_client_data)
        self._check_budget()
        if not self.api_key:
            raise GMICloudError("GMI_CLOUD_API_KEY is not set.")

        max_tokens = max_tokens or settings.GMI_CLOUD_MAX_OUTPUT_TOKENS
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        t0 = time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GMICloudError(f"GMI request failed: {exc}") from exc
        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            raise GMICloudError(
                f"GMI returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
            # Reasoning models return content=null when the token budget is fully
            # consumed by the (separate) reasoning field; coerce to "" so callers
            # never receive None. Raise the output cap if answers come back empty.
            raw_text = payload["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GMICloudError(f"Unexpected GMI response shape: {exc}") from exc

        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)

        text = _THINK_RE.sub("", raw_text).strip() if self.strip_think else raw_text
        cost = self._cost_usd(prompt_tokens, completion_tokens)

        # Record spend + log per-request usage/cost (req: track actual cost).
        from law_app.models import GmiSpend
        GmiSpend.record(prompt_tokens, completion_tokens, cost)
        logger.info(
            "GMI usage model=%s input=%d output=%d total=%d cost=$%.5f latency=%dms",
            self.model, prompt_tokens, completion_tokens, total_tokens, cost, latency_ms,
        )
        return GMIResult(
            text=text, raw_text=raw_text, model=self.model, latency_ms=latency_ms,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=total_tokens, cost_usd=cost,
        )

    def generate_stream(self, prompt, *, system=None, contains_client_data=True,
                        temperature=0.1, max_tokens=None):
        """Yield answer text incrementally as GMI produces it.

        A generator over content deltas. All policy gates and the HTTP status
        check run **before the first yield**, so a caller that pulls the first
        chunk (``next(...)``) surfaces any ``GMICloudDisabled`` / ``GMICloudError``
        up front and can still fall back to another backend. Once the first token
        has been yielded, fallback is no longer possible — a mid-stream failure
        raises ``GMICloudError`` to the consumer.

        ``<think>`` scratchpads are stripped on the fly for CoT models. Spend is
        recorded from the final usage chunk (``stream_options.include_usage``).
        """
        self._check_data_gate(contains_client_data)
        self._check_budget()
        if not self.api_key:
            raise GMICloudError("GMI_CLOUD_API_KEY is not set.")

        max_tokens = max_tokens or settings.GMI_CLOUD_MAX_OUTPUT_TOKENS
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            # Ask the server to emit a final usage chunk so we can bill accurately.
            "stream_options": {"include_usage": True},
        }

        t0 = time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=body,
                stream=True,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GMICloudError(f"GMI request failed: {exc}") from exc

        if resp.status_code != 200:
            body_preview = resp.text[:200]
            resp.close()
            raise GMICloudError(f"GMI returned HTTP {resp.status_code}: {body_preview}")

        tfilter = _ThinkStreamFilter() if self.strip_think else None
        prompt_tokens = completion_tokens = total_tokens = 0
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = line[6:] if line.startswith("data: ") else line
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                usage = chunk.get("usage")
                if usage:
                    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                    total_tokens = int(
                        usage.get("total_tokens", prompt_tokens + completion_tokens) or 0
                    )
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                # Reasoning models expose chain-of-thought in a separate field
                # (`reasoning` / `reasoning_content`); surface it as its own kind.
                rpiece = delta.get("reasoning") or delta.get("reasoning_content") or ""
                if rpiece:
                    yield StreamChunk("reasoning", rpiece)
                cpiece = delta.get("content") or ""
                if cpiece:
                    if tfilter is not None:
                        cpiece = tfilter.feed(cpiece)
                    if cpiece:
                        yield StreamChunk("content", cpiece)
        except requests.RequestException as exc:
            raise GMICloudError(f"GMI stream interrupted: {exc}") from exc
        finally:
            resp.close()

        if tfilter is not None:
            tail = tfilter.flush()
            if tail:
                yield StreamChunk("content", tail)

        latency_ms = int((time.monotonic() - t0) * 1000)
        cost = self._cost_usd(prompt_tokens, completion_tokens)
        from law_app.models import GmiSpend
        GmiSpend.record(prompt_tokens, completion_tokens, cost)
        logger.info(
            "GMI stream usage model=%s input=%d output=%d total=%d cost=$%.5f latency=%dms",
            self.model, prompt_tokens, completion_tokens, total_tokens, cost, latency_ms,
        )
