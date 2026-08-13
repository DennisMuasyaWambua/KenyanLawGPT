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
from typing import Callable, Iterator, Optional

from django.conf import settings

from .gmi import GMICloudProvider, GMICloudDisabled, GMICloudError, StreamChunk

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


@dataclass
class StreamResult:
    """A resolved streaming response: which backend served it plus its tokens.

    ``chunks`` is an iterator of text pieces. The backend is already decided by
    the time this is returned (GMI's gates and HTTP status were checked up
    front), so ``served_by`` is authoritative even though generation is lazy.
    """
    served_by: str            # "gmi:<model>" or "ollama"
    chunks: Iterator[str]
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


def generate_answer_stream(prompt, *, model=None, system=None,
                           contains_client_data=True,
                           ollama_stream_fallback: Optional[Callable[[], Iterator[str]]] = None):
    """Streaming counterpart of :func:`generate_answer`.

    Tries GMI streaming first. Because GMI's gates and HTTP status are validated
    before the first token, a failure there is caught here and — provided GMI has
    not yet emitted anything — falls back to ``ollama_stream_fallback`` (a
    zero-arg callable returning an iterator of plain text strings). Returns a
    :class:`StreamResult` whose ``chunks`` yield :class:`StreamChunk` objects
    (``kind`` = "content"/"reasoning") and whose ``served_by`` names the backend
    actually chosen. Ollama has no reasoning phase, so its output is wrapped as
    ``content`` chunks for a uniform contract.

    A failure *after* streaming has started cannot fall back; it propagates out
    of the ``chunks`` iterator as ``GMICloudError`` for the caller to handle.
    """
    model = model or getattr(settings, "GMI_CLOUD_MODEL", "")
    fallback_reason = ""

    if settings.GMI_CLOUD_API_KEY and model:
        try:
            gen = GMICloudProvider(model=model).generate_stream(
                prompt, system=system, contains_client_data=contains_client_data,
            )
            # Pull the first chunk now: this runs the gates + HTTP status check,
            # so any refusal/error is raised here (before we commit to GMI) and
            # we can still fall back. next(gen, None) tolerates an empty stream.
            first = next(gen, None)
            logger.info("Stream served by gmi:%s", _short(model))

            def _gmi_chunks():
                if first is not None:
                    yield first
                yield from gen

            return StreamResult(served_by=f"gmi:{_short(model)}", chunks=_gmi_chunks())
        except GMICloudDisabled as exc:
            fallback_reason = f"gmi-disabled: {exc}"
            logger.warning("GMI refused stream (%s); falling back to Ollama", exc)
        except GMICloudError as exc:
            fallback_reason = f"gmi-error: {exc}"
            logger.warning("GMI stream failed (%s); falling back to Ollama", exc)
    else:
        fallback_reason = "gmi-not-configured"
        logger.info("GMI not configured; using Ollama stream")

    if ollama_stream_fallback is None:
        raise GenerationUnavailable(fallback_reason or "no fallback provided")

    logger.warning("Stream served by ollama (reason: %s)", fallback_reason)
    ollama_chunks = (StreamChunk("content", s) for s in ollama_stream_fallback())
    return StreamResult(served_by="ollama", chunks=ollama_chunks,
                        fallback_reason=fallback_reason)
