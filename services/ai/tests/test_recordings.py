"""RecordingProcessor state transitions, exercised with fakes (no DB / storage)."""
import pytest

import json

from app.config import Config
from app.recordings import RecordingProcessor, _clip_transcript, _extract_json
from app.transcription import TranscriptResult


class _FakeTranscriber:
    def __init__(self, result=None, exc=None):
        self._result, self._exc = result, exc
        self.kwargs = {}

    async def transcribe(self, audio, filename, mime_type="", **kwargs):
        self.kwargs = kwargs
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

    async def fake_summarize(transcript, context=""):
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

    async def boom(transcript, context=""):
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


@pytest.mark.asyncio
async def test_speaker_segments_become_labelled_transcript():
    segs = [{"speaker": 1, "start": 0.0, "end": 2.0, "text": "Tutafile plaint kesho."},
            {"speaker": 2, "start": 2.5, "end": 4.0, "text": "Sawa, nitaleta ID."}]
    t = _FakeTranscriber(TranscriptResult("Tutafile plaint kesho. Sawa, nitaleta ID.", "sw",
                                          "faster-whisper", segments=segs))
    p, updates = _processor(t)
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm", num_speakers=2)
    assert t.kwargs == {"diarize": True, "num_speakers": 2, "hotwords": ""}
    assert updates[0]["transcript_text"] == (
        "[00:00] Speaker 1: Tutafile plaint kesho.\n[00:02] Speaker 2: Sawa, nitaleta ID.")
    assert json.loads(updates[0]["transcript_segments"]) == segs
    assert updates[-1]["status"] == "complete"


class _FakeLLM:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.prompts = reply, exc, []

    async def complete(self, system, prompt, max_tokens=2048, fast=False):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return self.reply


def _summarizer(provider="gmi", key="k"):
    cfg = Config()
    cfg.recordings_summary_provider, cfg.gmi_cloud_api_key = provider, key
    return RecordingProcessor(pool=None, cfg=cfg)


@pytest.mark.asyncio
async def test_notes_use_gmi_when_configured():
    p = _summarizer()
    p._gmi_llm, p._local_llm = _FakeLLM('{"action_items": []}'), _FakeLLM(exc=AssertionError("local used"))
    assert await p._summarize("Speaker 1: hi") == ('{"action_items": []}', "")


@pytest.mark.asyncio
async def test_notes_fall_back_to_local_with_a_note_when_gmi_fails():
    p = _summarizer()
    p._gmi_llm, p._local_llm = _FakeLLM(exc=RuntimeError("402 credits")), _FakeLLM('{"a": 1}')
    summary, note = await p._summarize("Speaker 1: hi")
    assert summary == '{"a": 1}'
    assert "on-box model" in note and "402 credits" in note


@pytest.mark.asyncio
async def test_notes_stay_local_when_configured_or_no_key():
    for provider, key in (("local", "k"), ("gmi", "")):
        p = _summarizer(provider, key)
        p._gmi_llm, p._local_llm = _FakeLLM(exc=AssertionError("gmi used")), _FakeLLM('{"a": 1}')
        assert await p._summarize("x") == ('{"a": 1}', "")


def test_clipping_keeps_the_end_of_the_meeting():
    t = "start " + "x" * 50000 + " AGREED: client to bring title deed by Friday"
    out = _clip_transcript(t, 12000)
    assert len(out) < 12100
    assert out.startswith("start ") and out.endswith("title deed by Friday")
    assert _clip_transcript("short", 12000) == "short"


@pytest.mark.asyncio
async def test_notes_say_plainly_when_no_model_is_available(monkeypatch):
    """No GMI key and no reachable Ollama: the transcript is still delivered and
    the note is readable, not a raw socket error."""
    monkeypatch.setattr("app.recordings._ollama_reachable", lambda cfg: False)
    p = _summarizer("local", "")
    summary, note = await p._summarize("Speaker 1: habari")
    assert summary == ""
    assert "no AI model is available" in note and "Errno" not in note


def test_storage_errors_are_reported_in_plain_language():
    from minio.error import S3Error

    from app.recordings import _user_error

    missing = S3Error(response=None, code="NoSuchKey", message="The specified key does not exist.",
                      resource="/wakili-archives/tenants/x/a.wav", request_id="req-1", host_id="host-1",
                      bucket_name="wakili-archives", object_name="tenants/x/a.wav")
    msg = _user_error(missing)
    assert "not found in storage" in msg and "wakili-archives" not in msg and "req-1" not in msg
    assert _user_error(RuntimeError("boom")) == "boom"
