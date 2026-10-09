"""RecordingProcessor state transitions, exercised with fakes (no DB / storage)."""
import pytest

from app.config import Config
from app.recordings import RecordingProcessor, _extract_json
from app.transcription import TranscriptResult


class _FakeTranscriber:
    def __init__(self, result=None, exc=None):
        self._result, self._exc = result, exc

    async def transcribe(self, audio, filename, mime_type=""):
        if self._exc:
            raise self._exc
        return self._result


def _processor(transcriber):
    p = RecordingProcessor(pool=None, cfg=Config())
    p._transcriber = transcriber
    updates = []

    async def fake_update(tenant_id, rec_id, **fields):
        updates.append(fields)

    async def fake_fetch(tenant_id, key):
        return b"audio"

    async def fake_summarize(transcript):
        return '{"executive_summary": "ok"}', ""

    async def fake_claim(tenant_id, rec_id):
        return p._attempt

    p._attempt = 1
    p._update, p._fetch_object, p._summarize, p._claim_attempt = fake_update, fake_fetch, fake_summarize, fake_claim
    return p, updates


@pytest.mark.asyncio
async def test_happy_path_ends_complete_with_transcript_and_summary():
    p, updates = _processor(_FakeTranscriber(TranscriptResult("hello world", "en", "faster-whisper")))
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert [u["status"] for u in updates] == ["summarizing", "complete"]
    assert updates[0]["transcript_text"] == "hello world"
    assert updates[1]["summary_text"] == '{"executive_summary": "ok"}'


@pytest.mark.asyncio
async def test_mock_transcript_fails_instead_of_fabricating_notes():
    p, updates = _processor(_FakeTranscriber(TranscriptResult("[offline mock transcript ...]", "und", "mock")))
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert len(updates) == 1 and updates[0]["status"] == "failed"
    assert "Speech-to-text is not available" in updates[0]["error"]


@pytest.mark.asyncio
async def test_transcriber_exception_marks_failed_with_message():
    p, updates = _processor(_FakeTranscriber(exc=RuntimeError("model download failed")))
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert updates[-1]["status"] == "failed"
    assert "model download failed" in updates[-1]["error"]


@pytest.mark.asyncio
async def test_summary_crash_still_completes_with_transcript():
    p, updates = _processor(None)

    async def boom(transcript):
        raise RuntimeError("ollama down")

    p._summarize = boom
    await p._finish_summary("t", "r", "some transcript")
    assert updates[-1]["status"] == "complete"
    assert "ollama down" in updates[-1]["error"]


def test_extract_json_strips_fences():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('Sure! {"a": 1} hope that helps') == '{"a": 1}'


@pytest.mark.asyncio
async def test_repeatedly_interrupted_recording_is_failed_not_retried_forever():
    p, updates = _processor(_FakeTranscriber(TranscriptResult("x", "en", "faster-whisper")))
    p._attempt = 4  # three earlier runs never finished
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert len(updates) == 1 and updates[0]["status"] == "failed"
    assert "interrupted 3 times" in updates[0]["error"]


@pytest.mark.asyncio
async def test_empty_transcript_fails_with_microphone_hint():
    p, updates = _processor(_FakeTranscriber(TranscriptResult("   ", "en", "faster-whisper")))
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert len(updates) == 1 and updates[0]["status"] == "failed"
    assert "No speech was detected" in updates[0]["error"]
