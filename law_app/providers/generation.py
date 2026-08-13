"""Generation orchestrator: GMI Cloud primary, Ollama fallback.

The live assistant and the ``compare_models`` A/B harness both call
:func:`generate_answer`. It tries the requested GMI model first; on ANY GMI
failure or policy refusal (disabled, budget, HTTP/network error) it falls back to
the caller-supplied Ollama callable, so a GMI outage or rate-limit never takes
generation down entirely. The provider that actually served the request is
recorded on the result (``served_by``) and logged, along with the fallback
reason when one occurred.
"""
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from django.conf import settings

from .gmi import GMICloudProvider, GMICloudDisabled, GMICloudError

logger = logging.getLogger(__name__)


class GenerationUnavailable(Exception):
    """Neither GMI nor a fallback could produce a response."""


@dataclass
class GenerationResult:
    text: str
    served_by: str            # "gmi:<model>" or "ollama"
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    fallback_reason: str = ""


def _short(model: str) -> str:
    return (model or "").split("/")[-1]


def generate_answer(prompt, *, model=None, system=None,
                    contains_client_data=True,
                    ollama_fallback: Optional[Callable[[], str]] = None):
    """Generate via GMI (primary) with automatic Ollama fallback.

    ``model`` defaults to ``GMI_CLOUD_MODEL``. ``ollama_fallback`` is a
    zero-arg callable returning the fallback text (kept as a callable so this
    module stays decoupled from the RAG engine's Ollama code).
    """
    model = model or getattr(settings, "GMI_CLOUD_MODEL", "")
    fallback_reason = ""

    if settings.GMI_CLOUD_API_KEY and model:
        try:
            res = GMICloudProvider(model=model).generate(
                prompt, system=system, contains_client_data=contains_client_data,
            )
            logger.info("Request served by gmi:%s (%dms)", _short(model), res.latency_ms)
            return GenerationResult(
                text=res.text, served_by=f"gmi:{_short(model)}",
                latency_ms=res.latency_ms, prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens, cost_usd=res.cost_usd,
            )
        except GMICloudDisabled as exc:
            fallback_reason = f"gmi-disabled: {exc}"
            logger.warning("GMI refused (%s); falling back to Ollama", exc)
        except GMICloudError as exc:
            fallback_reason = f"gmi-error: {exc}"
            logger.warning("GMI failed (%s); falling back to Ollama", exc)
    else:
        fallback_reason = "gmi-not-configured"
        logger.info("GMI not configured; using Ollama")

    if ollama_fallback is None:
        raise GenerationUnavailable(fallback_reason or "no fallback provided")

    t0 = time.monotonic()
    text = ollama_fallback()
    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info("Request served by ollama (%dms; reason: %s)", latency_ms, fallback_reason)
    return GenerationResult(text=text, served_by="ollama", latency_ms=latency_ms,
                            fallback_reason=fallback_reason)
