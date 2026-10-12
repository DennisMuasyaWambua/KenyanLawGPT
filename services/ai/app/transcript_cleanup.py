"""AI correction pass over a Whisper transcript, tuned for Kenyan English.

Whisper mishears Kenyan-accented English: names (Wanjiru → "one Jiru"), places
(Milimani → "mini many"), courts and agencies (ELRC, KRA, NTSA), legal terms
(plaint, chamber summons) and the Swahili/Sheng words that weave through
everyday Kenyan speech. A strong LLM reading the whole utterance in context can
fix most of these, so after transcription the TRANSCRIPT TEXT (never audio) is
sent, a batch of utterances at a time, to the same GMI Cloud model that writes
the meeting notes.

The pass is conservative by construction:

  * the model returns one corrected line per input line, by index, so speaker
    labels and timestamps never move;
  * any line the model drops, empties, translates or rewrites beyond a light
    correction (``_plausible``) keeps the original Whisper text;
  * any batch that fails keeps its original lines — the recording is never
    failed or delayed because of this step.

The original transcript is stored alongside (``transcript_raw``) and the audio
is kept, so every correction can be checked against what was actually said.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re

log = logging.getLogger("recordings")

SYSTEM = (
    "You proofread speech-recognition transcripts of meetings at a Kenyan law "
    "firm — advocates, clients, witnesses, court clerks. Speakers have Kenyan "
    "accents and code-switch between English, Swahili and Sheng.\n\n"
    "Fix words the recogniser misheard, using the surrounding conversation:\n"
    "- Kenyan names of people and places (e.g. Wanjiru, Otieno, Kamau, Chebet, "
    "Mwangi, Njeri, Milimani, Kibera, Kiambu, Eldoret, Kisumu, Mombasa, Machakos);\n"
    "- Kenyan courts, agencies and institutions (High Court, Court of Appeal, "
    "Supreme Court, ELRC, ELC, Magistrate's Court, Kadhi's Court, KRA, NTSA, NSSF, "
    "SHIF/NHIF, HELB, Ardhi House, Land Control Board, DCI, ODPP, LSK);\n"
    "- legal terms (advocate, plaint, affidavit, chamber summons, notice of "
    "motion, ex parte, injunction, decree, caveat, succession, grant of letters "
    "of administration, title deed, sale agreement, demand letter, mention, "
    "hearing, adjournment);\n"
    "- money and documents (Ksh, shillings, bob, M-Pesa, KRA PIN, ID number, "
    "logbook, chief's letter).\n\n"
    "Rules:\n"
    "- Change ONLY words you are confident were misheard. When unsure, keep the "
    "original wording.\n"
    "- Keep Swahili and Sheng exactly as spoken — never translate them. Fix only "
    "their spelling.\n"
    "- Keep the speaker's grammar, phrasing, fillers and Kenyan usage "
    "(\"I'm coming\", \"you've seen\", \"ati\", \"sasa\"). Do not polish style.\n"
    "- Never add, remove, merge, split or summarise content. Keep numbers, "
    "amounts, dates and case numbers as spoken.\n"
    "- Add sensible punctuation and capitalisation.\n\n"
    'You receive JSON {"lines": [{"i": 0, "text": "..."}, ...]}. Return ONLY JSON '
    '{"lines": [{"i": 0, "text": "..."}, ...]} with every input index exactly '
    "once, in order — no markdown, no commentary."
)

# Characters of transcript per model call: big enough for context, small enough
# that the corrected copy fits comfortably in the answer budget.
_BATCH_CHARS = 6000
_BATCH_LINES = 80
_MAX_TOKENS = 4000
# A typical meeting (≤ ~30k chars) goes out in a single round of requests.
_CONCURRENCY = 6
# Lines of plain (unsegmented) transcript are cut at sentence ends to about this size.
_PLAIN_LINE_CHARS = 400


def _plausible(original: str, corrected: str) -> bool:
    """Whether ``corrected`` looks like a light correction of ``original`` rather
    than a rewrite, translation or summary. Short lines get more latitude: one
    misheard name is a large share of a five-word utterance."""
    a, b = original.strip(), corrected.strip()
    if not b:
        return not a
    if a.lower() == b.lower():
        return True
    if len(b) > 2 * len(a) + 20 or len(b) < len(a) / 2 - 10:
        return False
    similarity = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return similarity >= (0.35 if len(a) < 40 else 0.55)


def _batches(lines: list[str]) -> list[list[int]]:
    out, cur, size = [], [], 0
    for i, line in enumerate(lines):
        if cur and (size + len(line) > _BATCH_CHARS or len(cur) >= _BATCH_LINES):
            out.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(line)
    if cur:
        out.append(cur)
    return out


def _parse(reply: str) -> dict[int, str]:
    t = (reply or "").strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    body = json.loads(t[start : end + 1])
    out = {}
    for item in body.get("lines") or []:
        if isinstance(item, dict) and isinstance(item.get("i"), int) and isinstance(item.get("text"), str):
            out[item["i"]] = item["text"]
    return out


async def correct_lines(llm, lines: list[str]) -> tuple[list[str], int, int]:
    """Correct each line in place. Returns (lines, changed, failed_batches); a
    line the model mishandles — or a whole failed batch — keeps its original."""
    result = list(lines)
    changed, failed = 0, 0
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def run(idx: list[int]) -> None:
        nonlocal changed, failed
        # Each batch is numbered from 0, so the model never sees global positions.
        payload = json.dumps({"lines": [{"i": n, "text": lines[k]} for n, k in enumerate(idx)]},
                             ensure_ascii=False)
        try:
            async with sem:
                fixed = _parse(await llm.complete(SYSTEM, payload, max_tokens=_MAX_TOKENS))
        except Exception as exc:  # noqa: BLE001 — a failed batch keeps Whisper's text
            log.warning("transcript correction batch failed (%d lines kept as-is): %s", len(idx), exc)
            failed += 1
            return
        for n, k in enumerate(idx):
            new = " ".join((fixed.get(n) or "").split())
            if new and new != lines[k] and _plausible(lines[k], new):
                result[k] = new
                changed += 1

    await asyncio.gather(*(run(b) for b in _batches(lines)))
    return result, changed, failed


async def correct_segments(llm, segments: list[dict]) -> tuple[list[dict], int, int]:
    """Correct diarized utterances ([{speaker, start, end, text}]); speakers and
    timings are untouched."""
    fixed, changed, failed = await correct_lines(llm, [s.get("text", "") for s in segments])
    return [{**s, "text": t} for s, t in zip(segments, fixed)], changed, failed


def split_plain(text: str) -> list[str]:
    """Cut an unsegmented transcript into sentence-aligned lines of roughly
    ``_PLAIN_LINE_CHARS`` so it can be corrected (and validated) piecewise."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) > _PLAIN_LINE_CHARS:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


async def correct_plain(llm, text: str) -> tuple[str, int, int]:
    fixed, changed, failed = await correct_lines(llm, split_plain(text))
    return " ".join(fixed), changed, failed
