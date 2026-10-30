"""Kenyan-English transcript correction: conservative, index-bound, never fatal."""
import json

import pytest

from app import transcript_cleanup as tc
from app.config import Config
from app.recordings import RecordingProcessor
from app.transcription import TranscriptResult


class _EchoLLM:
    """Replies with each line passed through ``fix`` (index-bound JSON)."""

    def __init__(self, fix=lambda s: s, exc=None, raw=None):
        self.fix, self.exc, self.raw, self.calls = fix, exc, raw, []

    async def complete(self, system, prompt, max_tokens=2048, fast=False):
        self.calls.append(json.loads(prompt))
        if self.exc:
            raise self.exc
        if self.raw is not None:
            return self.raw
        lines = json.loads(prompt)["lines"]
        return json.dumps({"lines": [{"i": ln["i"], "text": self.fix(ln["text"])} for ln in lines]})


@pytest.mark.asyncio
async def test_misheard_kenyan_words_are_corrected_and_speakers_kept():
    segs = [{"speaker": 1, "start": 0.0, "end": 3.0, "text": "file it at mini many law courts"},
            {"speaker": 2, "start": 3.5, "end": 5.0, "text": "sawa, one jiru will bring the title deed"}]
    llm = _EchoLLM(lambda s: s.replace("mini many", "Milimani").replace("one jiru", "Wanjiru"))
    out, changed, failed = await tc.correct_segments(llm, segs)
    assert [u["text"] for u in out] == ["file it at Milimani law courts", "sawa, Wanjiru will bring the title deed"]
    assert [(u["speaker"], u["start"], u["end"]) for u in out] == [(1, 0.0, 3.0), (2, 3.5, 5.0)]
    assert (changed, failed) == (2, 0)


@pytest.mark.asyncio
async def test_rewrites_translations_and_dropped_lines_keep_the_original():
    lines = ["Tutafile plaint kesho asubuhi na tutaenda Milimani pamoja", "ok", "the client paid fifty thousand"]
    replies = {
        lines[0]: "We will file the plaint tomorrow morning and go to Milimani together",  # translated
        lines[2]: "",  # emptied
    }
    llm = _EchoLLM(lambda s: replies.get(s, s))
    out, changed, _ = await tc.correct_lines(llm, lines)
    assert out == lines and changed == 0


@pytest.mark.asyncio
async def test_failed_batch_keeps_whisper_text_and_is_counted():
    out, changed, failed = await tc.correct_lines(_EchoLLM(exc=RuntimeError("402")), ["a b c", "d e f"])
    assert out == ["a b c", "d e f"] and (changed, failed) == (0, 1)
    out, _, failed = await tc.correct_lines(_EchoLLM(raw="sorry, I can't"), ["a b c"])
    assert out == ["a b c"] and failed == 1


@pytest.mark.asyncio
async def test_long_transcripts_are_batched_with_local_indices():
    lines = [f"line number {n} " + "x" * 200 for n in range(100)]
    llm = _EchoLLM()
    await tc.correct_lines(llm, lines)
    assert len(llm.calls) > 1
    for call in llm.calls:
        assert [ln["i"] for ln in call["lines"]] == list(range(len(call["lines"])))
    assert sum(len(c["lines"]) for c in llm.calls) == 100


def test_plain_transcripts_split_at_sentence_ends():
    text = " ".join(f"Sentence {n} is here." for n in range(60))
    parts = tc.split_plain(text)
    assert len(parts) > 1 and all(p.endswith(".") for p in parts)
    assert " ".join(parts) == text


def _processor(llm, cleanup=True):
    cfg = Config()
    cfg.recordings_summary_provider, cfg.gmi_cloud_api_key = "gmi", "k"
    cfg.recordings_transcript_cleanup = cleanup
    p = RecordingProcessor(pool=None, cfg=cfg)
    p._gmi_llm = llm
    updates = []

    class _T:
        async def transcribe(self, *a, **k):
            return TranscriptResult("mini many", "en", "faster-whisper",
                                    segments=[{"speaker": 1, "start": 0.0, "end": 1.0, "text": "at mini many"}])

    async def fake_update(tenant_id, rec_id, **fields):
        updates.append(fields)

    async def fake_fetch(tenant_id, key):
        return b"audio"

    async def fake_summarize(transcript, context=""):
        return "{}", ""

    async def fake_claim(tenant_id, rec_id):
        return 1

    p._transcriber = _T()
    p._update, p._fetch_object, p._summarize, p._claim_attempt = fake_update, fake_fetch, fake_summarize, fake_claim
    return p, updates


@pytest.mark.asyncio
async def test_worker_stores_corrected_and_original_transcripts():
    p, updates = _processor(_EchoLLM(lambda s: s.replace("mini many", "Milimani")))
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    # Whisper's transcript is visible first, then replaced by the corrected one.
    assert updates[0]["status"] == "summarizing"
    assert updates[0]["transcript_text"] == "[00:00] Speaker 1: at mini many"
    assert updates[1]["transcript_text"] == "[00:00] Speaker 1: at Milimani"
    assert updates[1]["transcript_raw"] == "[00:00] Speaker 1: at mini many"
    assert json.loads(updates[1]["transcript_segments"])[0]["text"] == "at Milimani"
    assert updates[-1]["status"] == "complete" and updates[-1]["error"] == ""


@pytest.mark.asyncio
async def test_worker_completes_with_a_note_when_correction_fails():
    p, updates = _processor(_EchoLLM(exc=RuntimeError("GMI down")))
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert updates[0]["transcript_text"] == "[00:00] Speaker 1: at mini many"
    assert len(updates) == 2 and "transcript_raw" not in updates[0]
    assert updates[-1]["status"] == "complete" and "could not be AI-corrected" in updates[-1]["error"]


@pytest.mark.asyncio
async def test_worker_skips_correction_when_disabled():
    llm = _EchoLLM(lambda s: "changed")
    p, updates = _processor(llm, cleanup=False)
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert llm.calls == [] and len(updates) == 2


@pytest.mark.asyncio
async def test_case_context_reaches_whisper_proofreader_and_notes():
    from app.recordings import MeetingContext

    llm = _EchoLLM(lambda s: s.replace("one jiru", "Wanjiru"))
    p, updates = _processor(llm)
    ctx = MeetingContext(firm="Karwitha & Co. Advocates", file="ELC E045/2024 — Wanjiru v Kamau",
                         client="Grace Wanjiru", court="Milimani ELC", people=["Otieno Ouma"],
                         staff=["Chebet Kiprop"])

    async def fake_context(tenant_id, rec_id):
        return ctx

    seen = {}

    class _T:
        async def transcribe(self, *a, **k):
            seen["hotwords"] = k.get("hotwords")
            return TranscriptResult("x", "en", "faster-whisper",
                                    segments=[{"speaker": 1, "start": 0.0, "end": 1.0, "text": "for one jiru"}])

    async def fake_summarize(transcript, context=""):
        seen["notes_context"] = context
        return "{}", ""

    p._meeting_context, p._transcriber, p._summarize = fake_context, _T(), fake_summarize
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")

    # Whisper gets only this meeting's names; colleagues not on the file stay out.
    assert seen["hotwords"].startswith("Grace Wanjiru, ELC E045/2024 — Wanjiru v Kamau, Milimani ELC")
    assert "Otieno Ouma" in seen["hotwords"] and "Chebet" not in seen["hotwords"]
    # The proofreader and the notes model see the full context.
    assert "Client: Grace Wanjiru" in llm.calls[0]["context"]
    assert "Other people at the firm: Chebet Kiprop" in llm.calls[0]["context"]
    assert "Client: Grace Wanjiru" in seen["notes_context"]
    assert updates[1]["transcript_text"] == "[00:00] Speaker 1: for Wanjiru"


@pytest.mark.asyncio
async def test_without_case_context_the_payload_is_unchanged():
    llm = _EchoLLM()
    await tc.correct_lines(llm, ["hello"])
    assert llm.calls == [{"lines": [{"i": 0, "text": "hello"}]}]


@pytest.mark.asyncio
async def test_unavailable_case_context_does_not_block_processing():
    p, updates = _processor(_EchoLLM())
    # pool=None: the context query fails, the recording still completes.
    await p._process_one("t", "r", "tenants/t/x", "a.webm", "audio/webm")
    assert updates[-1]["status"] == "complete"
