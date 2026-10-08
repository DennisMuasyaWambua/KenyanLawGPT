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
