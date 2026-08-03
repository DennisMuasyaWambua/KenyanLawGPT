"""Paragraph-aware text chunking for embeddings."""
from __future__ import annotations


def chunk_text(text: str, target: int = 1200, overlap: int = 150) -> list[str]:
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
        while len(para) > target:  # oversize paragraph: hard split with overlap
            chunks.append(para[:target])
            para = para[target - overlap:]
        current = para
    if current:
        chunks.append(current)
    return chunks
