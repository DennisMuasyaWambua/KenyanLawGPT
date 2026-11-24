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
import threading
from dataclasses import dataclass, field
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
    # Speaker-attributed utterances ([{speaker, start, end, text}]) when
    # diarization was requested and succeeded; empty otherwise.
    segments: list[dict] = field(default_factory=list)


def _join_hotwords(*parts: str) -> str:
    """Per-recording hotwords first: Whisper keeps only the first ~220 tokens
    of the prompt, and the case's own names matter most."""
    return ", ".join(p.strip() for p in parts if p and p.strip())


class TranscriptionProvider(Protocol):
    # ``hotwords``: names and terms likely to be spoken in this recording (the
    # client, the case, the court), added to the TRANSCRIBE_HOTWORDS vocabulary.
    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "", *,
                         diarize: bool = False, num_speakers: int = 0,
                         hotwords: str = "") -> TranscriptResult: ...


class MockTranscriptionProvider:
    """Deterministic offline transcriber: no real ASR, clearly watermarked so a
    mock transcript is never mistaken for a real client conversation."""

    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "", *,
                         diarize: bool = False, num_speakers: int = 0,
                         hotwords: str = "") -> TranscriptResult:
        return TranscriptResult(
            text=(f"[offline mock transcript for {filename} — configure a transcription "
                  f"provider (TRANSCRIBE_PROVIDER=whisper|openai) for real speech-to-text; "
                  f"received {len(audio)} bytes of audio]"),
            language="und", provider="mock",
        )


class _AllowedLanguages:
    """Wraps the CTranslate2 Whisper model so every language detection —
    whole-file and per-window (faster-whisper's ``multilingual`` mode) — only
    chooses among the firm's languages. faster-whisper's per-window detection
    takes the top language out of ~100; on Kenyan accents that is regularly an
    unrelated one, after which the window is transcribed in that language.
    Whisper's own ranking is kept, renormalised over the allowed languages."""

    def __init__(self, model, allowed: list[str]) -> None:
        self._model = model
        self._allowed = {f"<|{c}|>" for c in allowed}
        self._seen = threading.local()

    def detect_language(self, *args, **kwargs):
        out = []
        for langs in self._model.detect_language(*args, **kwargs):
            kept = [(tok, p) for tok, p in langs if tok in self._allowed] or langs
            total = sum(p for _, p in kept) or 1.0
            out.append([(tok, p / total) for tok, p in kept])
            seen = getattr(self._seen, "langs", None)
            if seen is not None:
                seen.add(out[-1][0][0][2:-2])
        return out

    def track(self) -> set[str]:
        """Start recording the languages chosen on this thread; returns the set."""
        self._seen.langs = set()
        return self._seen.langs

    def __getattr__(self, name):
        return getattr(self._model, name)


class FasterWhisperProvider:
    """Local Whisper via faster-whisper (CTranslate2). Audio never leaves the
    host — the right default for privileged client recordings. Language is
    auto-detected unless TRANSCRIBE_LANGUAGE pins one."""

    def __init__(self, cfg: Config) -> None:
        from faster_whisper import WhisperModel  # imported lazily; heavy dep

        self._cfg = cfg
        # Use every core explicitly (CTranslate2's default can under-subscribe).
        self._model = WhisperModel(cfg.whisper_model, device="cpu", compute_type="int8",
                                   cpu_threads=os.cpu_count() or 4)
        self._langs: _AllowedLanguages | None = None
        inner = getattr(self._model, "model", None)  # the CTranslate2 Whisper model
        if inner is not None and len(cfg.transcribe_languages) > 1:
            self._langs = _AllowedLanguages(inner, cfg.transcribe_languages)
            self._model.model = self._langs
        self._diarizer = None
        self._diarizer_built = False

    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "", *,
                         diarize: bool = False, num_speakers: int = 0,
                         hotwords: str = "") -> TranscriptResult:
        return await asyncio.to_thread(self._run, audio, filename, diarize, num_speakers, hotwords)

    def _get_diarizer(self):
        # Built on first use (only meeting recordings ask for speakers), once:
        # a missing model is logged a single time, not on every recording.
        if not self._diarizer_built:
            from .diarization import make_diarizer

            self._diarizer = make_diarizer(self._cfg)
            self._diarizer_built = True
        return self._diarizer

    def _pick_language(self, samples) -> str | None:
        """The language to transcribe in. A pinned TRANSCRIBE_LANGUAGE wins.
        Otherwise detect, but only among TRANSCRIBE_LANGUAGES (default en,sw):
        free detection over ~100 languages misfires on Kenyan accents and
        code-switching (e.g. labelling a meeting Yoruba), and Whisper then
        transcribes — or translates — into the wrong language."""
        pinned = self._cfg.transcribe_language
        if pinned not in ("", "auto"):
            return pinned
        allowed = self._cfg.transcribe_languages
        if not allowed:
            return None  # unrestricted auto-detect
        if len(allowed) == 1:
            return allowed[0]
        try:
            # One 30 s window of speech is enough to choose between the allowed
            # languages; each extra window is another full encoder pass.
            _, _, probs = self._model.detect_language(
                samples, vad_filter=True, language_detection_segments=1)
            ranked = [p for p in probs if p[0] in allowed]
            return max(ranked, key=lambda p: p[1])[0] if ranked else allowed[0]
        except Exception as exc:  # noqa: BLE001 — detection is best-effort
            log().warning("language detection failed (%s); using %s", exc, allowed[0])
            return allowed[0]

    def _run(self, audio: bytes, filename: str, diarize: bool = False,
             num_speakers: int = 0, hotwords: str = "") -> TranscriptResult:
        from faster_whisper.audio import decode_audio

        suffix = os.path.splitext(filename)[1] or ".audio"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(audio)
            tmp.flush()
            samples = decode_audio(tmp.name, sampling_rate=16000)  # decode once
        if len(samples) == 0:
            return TranscriptResult(text="", language="", provider="faster-whisper")
        language = self._pick_language(samples)
        code_switch = (self._langs is not None and self._cfg.transcribe_code_switch
                       and self._cfg.transcribe_language in ("", "auto"))
        opts = dict(
            language=language,
            # Code-switched meetings (English <-> Swahili): each window gets its
            # own language, chosen among TRANSCRIBE_LANGUAGES (see _AllowedLanguages).
            multilingual=code_switch,
            vad_filter=True,  # never off: see below
            beam_size=max(1, self._cfg.whisper_beam_size),
            # Conditioning on the previous window is what lets Whisper fall
            # into repetition loops; independent windows are faster and safer.
            condition_on_previous_text=False,
        )
        vocabulary = _join_hotwords(hotwords, self._cfg.transcribe_hotwords)
        if vocabulary:
            # Domain vocabulary biases every 30 s window (unlike initial_prompt,
            # which only primes the first): Kenyan names, courts and legal
            # terms are spelt as the firm spells them instead of misheard.
            opts["hotwords"] = vocabulary
        if diarize:
            # Word timings let each word be attributed to a speaker turn. They
            # also enable skipping silent stretches where Whisper hallucinates
            # (phantom "Thank you." etc. during pauses in a meeting).
            opts["word_timestamps"] = True
            opts["hallucination_silence_threshold"] = 2.0
        seen = self._langs.track() if code_switch else set()
        segments, info = self._model.transcribe(samples, **opts)
        segments = list(segments)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if not text:
            # Quiet speech (distant/low-gain mic) can fall under the default
            # VAD threshold. Retry with a more sensitive VAD — but never with
            # VAD disabled: on silence Whisper then hallucinates text and its
            # temperature fallback can grind for many minutes per recording.
            segments, info = self._model.transcribe(
                samples, **opts, vad_parameters={"threshold": 0.25})
            segments = list(segments)
            text = " ".join(seg.text.strip() for seg in segments).strip()
        utterances = self._speakers(samples, segments, num_speakers) if diarize and text else []
        if len(seen) > 1:
            # e.g. "en+sw": the meeting switched languages.
            language = "+".join(sorted(seen, key=lambda c: c != language))
        return TranscriptResult(text=text, language=language or getattr(info, "language", "") or "",
                                provider="faster-whisper", segments=utterances)

    def _speakers(self, samples, segments, num_speakers: int) -> list[dict]:
        """Who said what. Best-effort: on any failure the transcript is kept
        without speaker labels rather than failing the recording."""
        from .diarization import Turn, Word, assign_speakers

        words = [Word(w.start, w.end, w.word) for seg in segments for w in (getattr(seg, "words", None) or [])]
        if num_speakers == 1:
            # One voice: nothing to tell apart, so skip the diarizer (the
            # costliest stage of processing a meeting).
            return assign_speakers(words, [Turn(0.0, float("inf"), 0)])
        diarizer = self._get_diarizer()
        if diarizer is None:
            return []
        try:
            turns = diarizer.diarize(samples, num_speakers)
        except Exception as exc:  # noqa: BLE001
            log().warning("speaker diarization failed (%s); transcript kept without speakers", exc)
            return []
        return assign_speakers(words, turns)


class OpenAITranscriptionProvider:
    """Cloud Whisper via an OpenAI-compatible /audio/transcriptions endpoint.
    Opt-in only (TRANSCRIBE_PROVIDER=openai): this sends audio off-box, so it is
    never auto-selected for potentially-privileged material."""

    def __init__(self, cfg: Config) -> None:
        import httpx

        self._httpx = httpx
        self._cfg = cfg
        self._base = cfg.transcribe_base_url.rstrip("/")

    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "", *,
                         diarize: bool = False, num_speakers: int = 0,
                         hotwords: str = "") -> TranscriptResult:
        # No speaker labels from the cloud endpoint; diarize is accepted and ignored.
        files = {"file": (filename, audio, mime_type or "application/octet-stream")}
        data = {"model": self._cfg.transcribe_openai_model, "response_format": "verbose_json"}
        if self._cfg.transcribe_language not in ("", "auto"):
            data["language"] = self._cfg.transcribe_language
        vocabulary = _join_hotwords(hotwords, self._cfg.transcribe_hotwords)
        if vocabulary:
            data["prompt"] = vocabulary  # the Whisper API's vocabulary hint
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


class LazyTranscriber:
    """One transcriber shared by archive ingestion and the meeting-recording
    worker, built on first use.

    Building a Whisper model loads (and on first run downloads) hundreds of MB.
    Doing that eagerly blocked AI-service startup (and crashed it outright when
    the download failed), and building one per consumer held two copies in RAM.
    The build runs in a thread so the event loop stays responsive; a failed build
    is retried on the next call rather than cached.
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._inner: TranscriptionProvider | None = None
        self._lock = asyncio.Lock()

    async def _get(self) -> TranscriptionProvider:
        if self._inner is None:
            async with self._lock:
                if self._inner is None:
                    self._inner = await asyncio.to_thread(make_transcriber, self._cfg)
        return self._inner

    async def transcribe(self, audio: bytes, filename: str, mime_type: str = "", *,
                         diarize: bool = False, num_speakers: int = 0,
                         hotwords: str = "") -> TranscriptResult:
        return await (await self._get()).transcribe(
            audio, filename, mime_type, diarize=diarize, num_speakers=num_speakers, hotwords=hotwords)

    async def warm(self) -> None:
        """Load the model ahead of the first recording (a cold Whisper load takes
        tens of seconds, plus a one-off download on a fresh cache)."""
        try:
            await self._get()
            log().info("transcriber warmed up")
        except Exception as exc:  # noqa: BLE001 — retried lazily on first use
            log().warning("transcriber warm-up failed (will retry on first use): %s", exc)
