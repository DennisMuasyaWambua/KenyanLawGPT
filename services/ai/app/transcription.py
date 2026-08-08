"""Speech-to-text provider abstraction (multilingual).

Client-conversation audio is privileged, KDPA-sensitive material, so this
follows the same swappable-provider pattern as ``make_llm``/``make_embedder``
with one hard rule: the cloud provider is **never** selected automatically.
``auto`` prefers a locally-run Whisper (no audio leaves the box) and otherwise
falls back to the deterministic offline mock. Sending audio to an external ASR
requires an explicit ``TRANSCRIBE_PROVIDER=openai`` opt-in.

Whisper auto-detects the spoken language, which covers the multilingual case
(English, Swahili, Sheng-inflected mixes, etc.) without per-call configuration.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from typing import Protocol

from .config import Config
from .logging_setup import log

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".oga", ".flac", ".webm", ".mp4", ".aac", ".amr")


def is_audio(filename: str, mime_type: str = "") -> bool:
    if mime_type.startswith("audio/"):
        return True
    if mime_type in ("video/webm", "video/mp4"):  # common recorder containers
        return True
    return filename.lower().endswith(AUDIO_EXTS)


@dataclass
class TranscriptResult:
    text: str
    language: str = ""
    provider: str = ""


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "") -> TranscriptResult: ...


class MockTranscriptionProvider:
    """Deterministic offline transcriber: no real ASR, clearly watermarked so a
    mock transcript is never mistaken for a real client conversation."""

    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "") -> TranscriptResult:
        return TranscriptResult(
            text=(f"[offline mock transcript for {filename} — configure a transcription "
                  f"provider (TRANSCRIBE_PROVIDER=whisper|openai) for real speech-to-text; "
                  f"received {len(audio)} bytes of audio]"),
            language="und", provider="mock",
        )


class FasterWhisperProvider:
    """Local Whisper via faster-whisper (CTranslate2). Audio never leaves the
    host — the right default for privileged client recordings. Language is
    auto-detected unless TRANSCRIBE_LANGUAGE pins one."""

    def __init__(self, cfg: Config) -> None:
        from faster_whisper import WhisperModel  # imported lazily; heavy dep

        self._cfg = cfg
        self._model = WhisperModel(cfg.whisper_model, device="cpu", compute_type="int8")

    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "") -> TranscriptResult:
        return await asyncio.to_thread(self._run, audio, filename)

    def _run(self, audio: bytes, filename: str) -> TranscriptResult:
        suffix = os.path.splitext(filename)[1] or ".audio"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(audio)
            tmp.flush()
            language = None if self._cfg.transcribe_language in ("", "auto") else self._cfg.transcribe_language
            segments, info = self._model.transcribe(tmp.name, language=language, vad_filter=True)
            text = " ".join(seg.text.strip() for seg in segments).strip()
        return TranscriptResult(text=text, language=getattr(info, "language", "") or "", provider="faster-whisper")


class OpenAITranscriptionProvider:
    """Cloud Whisper via an OpenAI-compatible /audio/transcriptions endpoint.
    Opt-in only (TRANSCRIBE_PROVIDER=openai): this sends audio off-box, so it is
    never auto-selected for potentially-privileged material."""

    def __init__(self, cfg: Config) -> None:
        import httpx

        self._httpx = httpx
        self._cfg = cfg
        self._base = cfg.transcribe_base_url.rstrip("/")

    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "") -> TranscriptResult:
        files = {"file": (filename, audio, mime_type or "application/octet-stream")}
        data = {"model": self._cfg.transcribe_openai_model, "response_format": "verbose_json"}
        if self._cfg.transcribe_language not in ("", "auto"):
            data["language"] = self._cfg.transcribe_language
        headers = {"Authorization": f"Bearer {self._cfg.transcribe_api_key}"}
        async with self._httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(f"{self._base}/audio/transcriptions",
                                     data=data, files=files, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        return TranscriptResult(text=body.get("text", ""), language=body.get("language", ""),
                                provider="openai")


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def make_transcriber(cfg: Config) -> TranscriptionProvider:
    provider = (cfg.transcribe_provider or "auto").lower()
    if provider == "mock":
        return MockTranscriptionProvider()
    if provider == "whisper":
        return FasterWhisperProvider(cfg)
    if provider == "openai":
        return OpenAITranscriptionProvider(cfg)
    # auto: local Whisper if installed, else offline mock. Cloud is never auto.
    if _faster_whisper_available():
        log().info("auto transcription: local faster-whisper (model %s)", cfg.whisper_model)
        return FasterWhisperProvider(cfg)
    log().warning("No local Whisper available — using MockTranscriptionProvider (offline). "
                  "Install faster-whisper or set TRANSCRIBE_PROVIDER=openai for real STT.")
    return MockTranscriptionProvider()
