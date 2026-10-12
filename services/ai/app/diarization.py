"""On-box speaker diarization ("who spoke when") for meeting recordings.

Runs entirely on the host with sherpa-onnx — pyannote-3.0 segmentation plus a
wespeaker voxceleb speaker embedding, ~35 MB of ONNX and no PyTorch — so, like
transcription, client audio never leaves the box. The diarizer only answers
*when* each voice spoke; Whisper's word timestamps are then attributed to those
turns by ``assign_speakers``, giving a transcript of the form
``[01:12] Speaker 2: …``.

Diarization is best-effort: any failure (package or model files missing, a
decoder error) yields an unlabelled transcript rather than a failed recording.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional

from .config import Config
from .logging_setup import log


@dataclass
class Turn:
    start: float
    end: float
    speaker: int  # raw cluster id from the diarizer


@dataclass
class Word:
    start: float
    end: float
    text: str


class Diarizer:
    def __init__(self, cfg: Config) -> None:
        import sherpa_onnx  # imported lazily; optional dependency

        self._sherpa = sherpa_onnx
        self._cfg = cfg
        self._threads = os.cpu_count() or 4
        self._sd = sherpa_onnx.OfflineSpeakerDiarization(self._config(0))
        # set_config + process must not interleave across threads.
        self._lock = threading.Lock()

    def _config(self, num_speakers: int):
        s = self._sherpa
        config = s.OfflineSpeakerDiarizationConfig(
            segmentation=s.OfflineSpeakerSegmentationModelConfig(
                pyannote=s.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=self._cfg.diarization_segmentation_model,
                    window_shift_ratio=self._cfg.diarization_window_shift),
                num_threads=self._threads),
            embedding=s.SpeakerEmbeddingExtractorConfig(
                model=self._cfg.diarization_embedding_model, num_threads=self._threads),
            # A known count is far more reliable than threshold clustering (see
            # Config.diarization_threshold); -1 means "estimate it".
            clustering=s.FastClusteringConfig(
                num_clusters=num_speakers if num_speakers > 0 else -1,
                threshold=self._cfg.diarization_threshold),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise RuntimeError("invalid speaker-diarization config (check the model paths)")
        return config

    def diarize(self, samples, num_speakers: int = 0) -> list[Turn]:
        """``samples``: 16 kHz mono float32. ``num_speakers`` <= 0 => estimate."""
        with self._lock:
            self._sd.set_config(self._config(num_speakers))
            result = self._sd.process(samples).sort_by_start_time()
        return [Turn(float(r.start), float(r.end), int(r.speaker)) for r in result]


def make_diarizer(cfg: Config) -> Optional[Diarizer]:
    if not cfg.diarization_enabled:
        return None
    missing = [p for p in (cfg.diarization_segmentation_model, cfg.diarization_embedding_model)
               if not os.path.isfile(p)]
    if missing:
        log().warning("speaker diarization disabled: model file(s) not found: %s", ", ".join(missing))
        return None
    try:
        return Diarizer(cfg)
    except Exception as exc:  # noqa: BLE001 — speakers are an enhancement, never a blocker
        log().warning("speaker diarization disabled: %s", exc)
        return None


def assign_speakers(words: list[Word], turns: list[Turn]) -> list[dict]:
    """Attribute each word to the turn it overlaps most (or, in a gap between
    turns, the nearer one) and merge consecutive same-speaker words into
    utterances. Speakers are renumbered 1..N in order of first appearance.

    Returns ``[{"speaker": 1, "start": 0.0, "end": 2.6, "text": "…"}, …]``, or
    ``[]`` when there is nothing to attribute."""
    if not words or not turns:
        return []
    turns = sorted(turns, key=lambda t: t.start)
    order: dict[int, int] = {}  # raw cluster id -> 1-based label
    utterances: list[dict] = []
    lo = 0  # turns before lo ended before the current word starts
    ended: Turn | None = None  # the latest-ending of those turns
    for w in sorted(words, key=lambda x: x.start):
        if not w.text.strip():
            continue
        while lo < len(turns) and turns[lo].end <= w.start:
            if ended is None or turns[lo].end > ended.end:
                ended = turns[lo]
            lo += 1
        best, best_overlap = None, 0.0
        k = lo
        while k < len(turns) and turns[k].start < w.end:
            overlap = min(w.end, turns[k].end) - max(w.start, turns[k].start)
            # ">= 0" on the first hit catches zero-length words inside a turn.
            if overlap > best_overlap or (best is None and overlap >= 0):
                best, best_overlap = turns[k], overlap
            k += 1
        if best is None:
            # In a gap (VAD and the diarizer disagree slightly at turn edges):
            # take whichever neighbouring turn is closer in time.
            after = turns[k] if k < len(turns) else None
            if ended is None or (after is not None and after.start - w.end < w.start - ended.end):
                best = after
            else:
                best = ended
            best = best or turns[0]
        speaker = order.setdefault(best.speaker, len(order) + 1)
        if utterances and utterances[-1]["speaker"] == speaker:
            u = utterances[-1]
            u["text"] += w.text
            u["end"] = round(w.end, 2)
        else:
            utterances.append({"speaker": speaker, "start": round(w.start, 2),
                               "end": round(w.end, 2), "text": w.text})
    for u in utterances:
        u["text"] = u["text"].strip()
    return _rejoin_split_sentences(utterances)


def _rejoin_split_sentences(utterances: list[dict]) -> list[dict]:
    """A turn boundary a few hundred ms early strands the first word or two of a
    sentence on the previous speaker ("Speaker 1: You" / "Speaker 2: can put it
    on a chip now."). When a short fragment has no sentence-ending punctuation
    and runs straight into a lowercase continuation, give it to the next speaker."""
    out: list[dict] = []
    i = 0
    while i < len(utterances):
        u = utterances[i]
        nxt = utterances[i + 1] if i + 1 < len(utterances) else None
        if (nxt and len(u["text"].split()) <= 3 and not u["text"].endswith((".", "?", "!", "…"))
                and nxt["text"][:1].islower() and nxt["start"] - u["end"] < 0.5):
            nxt["text"] = f"{u['text']} {nxt['text']}"
            nxt["start"] = u["start"]
        else:
            out.append(u)
        i += 1
    # Rejoining can leave two neighbours from the same speaker; merge them.
    merged: list[dict] = []
    for u in out:
        if merged and merged[-1]["speaker"] == u["speaker"]:
            merged[-1]["text"] += " " + u["text"]
            merged[-1]["end"] = u["end"]
        else:
            merged.append(u)
    order: dict[int, int] = {}
    for u in merged:
        u["speaker"] = order.setdefault(u["speaker"], len(order) + 1)
    return merged


def _clock(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def format_transcript(utterances: list[dict]) -> str:
    """Plain-text, speaker-labelled transcript (stored as transcript_text and fed
    to the notes model, which attributes action items by these labels)."""
    return "\n".join(f"[{_clock(u['start'])}] Speaker {u['speaker']}: {u['text']}" for u in utterances)
