"""Transcription provider selection, audio detection, and the KDPA-safe rule
that cloud STT is never auto-selected."""
import pytest

from app.config import Config
from app.transcription import (
    MockTranscriptionProvider,
    is_audio,
    make_transcriber,
)


@pytest.mark.parametrize("filename,mime,expected", [
    ("call.mp3", "", True),
    ("meeting.wav", "audio/wav", True),
    ("note.m4a", "", True),
    ("clip.webm", "video/webm", True),
    ("contract.pdf", "application/pdf", False),
    ("brief.docx", "", False),
    ("recording", "audio/ogg", True),
])
def test_is_audio(filename, mime, expected):
    assert is_audio(filename, mime) is expected


@pytest.mark.asyncio
async def test_mock_transcriber_is_watermarked_and_nonempty():
    result = await MockTranscriptionProvider().transcribe(b"\x00\x01\x02", "call.mp3", "audio/mpeg")
    assert result.text.strip()
    assert "mock transcript" in result.text.lower()
    assert result.provider == "mock"


def test_auto_never_selects_cloud(monkeypatch):
    # With no local Whisper installed, auto must fall back to the offline mock,
    # never the cloud provider — audio must not leave the box implicitly.
    monkeypatch.setattr("app.transcription._faster_whisper_available", lambda: False)
    cfg = Config()
    cfg.transcribe_provider = "auto"
    assert isinstance(make_transcriber(cfg), MockTranscriptionProvider)


def test_explicit_mock_selection():
    cfg = Config()
    cfg.transcribe_provider = "mock"
    assert isinstance(make_transcriber(cfg), MockTranscriptionProvider)


@pytest.mark.asyncio
async def test_lazy_transcriber_builds_once_and_retries_failed_builds(monkeypatch):
    import asyncio

    from app.transcription import LazyTranscriber

    calls = {"n": 0}

    def flaky_factory(cfg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model download failed")
        return MockTranscriptionProvider()

    monkeypatch.setattr("app.transcription.make_transcriber", flaky_factory)
    lazy = LazyTranscriber(Config())
    with pytest.raises(RuntimeError):
        await lazy.transcribe(b"x", "a.wav")
    # Failure isn't cached; concurrent callers then share a single build.
    results = await asyncio.gather(*(lazy.transcribe(b"x", "a.wav") for _ in range(5)))
    assert all(r.provider == "mock" for r in results)
    assert calls["n"] == 2


def test_whisper_never_disables_vad(monkeypatch):
    """Regression: running Whisper with vad_filter=False on silent audio makes it
    hallucinate and grind for minutes. The empty-result retry must only make the
    VAD more sensitive."""
    import sys
    import types

    calls = []

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, path, **kw):
            calls.append(kw)
            return iter(()), types.SimpleNamespace(language="en")

        def detect_language(self, samples, **kw):
            return "yo", 0.6, [("yo", 0.6), ("sw", 0.3), ("en", 0.1)]

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setitem(sys.modules, "faster_whisper.audio",
                        types.SimpleNamespace(decode_audio=lambda *a, **k: [0.0] * 16000))
    from app.transcription import FasterWhisperProvider

    result = FasterWhisperProvider(Config())._run(b"\x00" * 10, "silence.webm")
    assert result.text == ""
    assert len(calls) == 2
    assert all(kw["vad_filter"] is True for kw in calls)
    assert all(kw["condition_on_previous_text"] is False for kw in calls)
    assert calls[1]["vad_parameters"]["threshold"] < 0.5
    # Detection is restricted to the allowed languages: "yo" wins overall, but
    # the best allowed language (sw) is what gets used.
    assert all(kw["language"] == "sw" for kw in calls)


def test_pinned_language_skips_detection(monkeypatch):
    import types

    from app.transcription import FasterWhisperProvider

    p = FasterWhisperProvider.__new__(FasterWhisperProvider)
    cfg = Config()
    cfg.transcribe_language = "sw"
    p._cfg = cfg
    p._model = types.SimpleNamespace(detect_language=lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert p._pick_language(None) == "sw"
    cfg.transcribe_language, cfg.transcribe_languages = "auto", ["en"]
    assert p._pick_language(None) == "en"
