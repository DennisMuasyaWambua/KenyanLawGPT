"""Corpus/qrels loading, OCR-noise simulation, cleaning and chunking."""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Doc:
    doc_id: str
    title: str
    text: str
    court: str = ""
    year: int = 0
    cites: list[str] = field(default_factory=list)


@dataclass
class Query:
    query_id: str
    text: str
    relevant: dict[str, int]  # doc_id -> grade (1..3)


def load_corpus(path: str | Path) -> list[Doc]:
    docs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                docs.append(Doc(r["doc_id"], r.get("title", ""), r["text"], r.get("court", ""),
                                int(r.get("year", 0)), r.get("cites", [])))
    return docs


def load_qrels(path: str | Path) -> list[Query]:
    qs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rel = r["relevant"]
                if isinstance(rel, list):  # allow plain id list = grade 1
                    rel = {d: 1 for d in rel}
                qs.append(Query(r["query_id"], r["query"], {d: int(g) for d, g in rel.items()}))
    return qs


# --- OCR noise: the "realistic complication" the brief asks for -----------------------
_OCR_CONFUSIONS = {"l": "1", "I": "l", "O": "0", "rn": "m", "m": "rn", "e": "c", "c": "e",
                   "h": "b", "u": "v", "fi": "ﬁ", "a": "o"}


def inject_ocr_noise(text: str, rate: float, seed: int = 0) -> str:
    """Simulate scanned-judgment OCR damage: character confusions, broken
    hyphenation across lines, and stray page headers. ``rate`` is the per-word
    probability that a word is corrupted."""
    rng = random.Random(seed)
    out = []
    for i, w in enumerate(text.split(" ")):
        if len(w) > 3 and rng.random() < rate:
            keys = [k for k in _OCR_CONFUSIONS if k in w]
            if keys:
                k = rng.choice(keys)
                w = w.replace(k, _OCR_CONFUSIONS[k], 1)
            elif rng.random() < 0.5:
                cut = rng.randrange(2, len(w) - 1)
                w = w[:cut] + "-\n" + w[cut:]
        out.append(w)
        if i and i % 180 == 0:
            out.append("\nREPUBLIC OF KENYA - Page %d\n" % (i // 180))
    return " ".join(out)


# --- cleaning (what the production pipeline should do before indexing) -----------------
_HEADER_RE = re.compile(r"^\s*(REPUBLIC OF KENYA\b.*|Page \d+( of \d+)?|Kenya Law Reports.*)\s*$",
                        re.IGNORECASE | re.MULTILINE)
_LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "’": "'", "“": '"', "”": '"', " ": " "})


def clean_text(text: str) -> str:
    text = text.translate(_LIGATURES)
    text = re.sub(r"-\n(\w)", r"\1", text)          # de-hyphenate line breaks
    text = _HEADER_RE.sub("", text)                  # drop running page headers
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, target: int = 1200, overlap: int = 150) -> list[str]:
    """Paragraph-aware chunker; mirrors services/ai/app/chunking.py so results
    transfer to the production pipeline."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= target:
        return [text]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= target:
            current = (current + "\n\n" + para).strip()
            continue
        if current:
            chunks.append(current)
        while len(para) > target:
            chunks.append(para[:target])
            para = para[target - overlap:]
        current = para
    if current:
        chunks.append(current)
    return chunks


def build_chunks(docs: list[Doc], target: int = 1200, overlap: int = 150,
                 clean: bool = True, noise: float = 0.0, seed: int = 0
                 ) -> tuple[list[str], list[str]]:
    """Returns (chunk_texts, chunk_doc_ids). Title is prepended to every chunk so a
    chunk is self-describing (a common, cheap retrieval win worth ablating)."""
    texts, owners = [], []
    for d in docs:
        body = inject_ocr_noise(d.text, noise, seed) if noise > 0 else d.text
        if clean:
            body = clean_text(body)
        for c in chunk_text(body, target, overlap):
            texts.append(f"{d.title}\n{c}" if d.title else c)
            owners.append(d.doc_id)
    return texts, owners
