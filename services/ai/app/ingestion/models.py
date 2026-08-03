"""Normalized schema every ingested public legal source passes through."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Opinion:
    """An individual judge's opinion within a judgment — modeled as its own
    graph node so a dissent/concurrence is retrievable separately from the
    majority holding."""
    judge: str
    kind: str  # "majority" | "concurrence" | "dissent"
    text: str


@dataclass
class Relation:
    """Explicit treatment edge to another public document."""
    rel_type: str  # AMENDS | REPEALS | OVERTURNS | DISTINGUISHES | CITES | INTERPRETS
    target_doc_id: str


@dataclass
class LegalDocument:
    doc_id: str            # stable id, e.g. "act-2007-11" or "case-elrc-e123-2026"
    title: str
    doc_type: str          # constitution|statute|case_law|judgment|gazette|guideline|cause_list|bill|treaty|tribunal
    source_url: str
    full_text: str
    court: str = ""
    citation: str = ""
    year: int = 0
    status: str = "current"      # current|amended|superseded|overturned|distinguished|repealed
    version: int = 1
    authored_by: list[str] = field(default_factory=list)  # bench composition
    opinions: list[Opinion] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # Temporal validity (ISO 'YYYY-MM-DD'); repealed_date is set when the
    # instrument is later repealed/superseded — the node is date-stamped, never
    # deleted, so historical "as of <date>" queries stay accurate.
    effective_date: Optional[str] = None
    repealed_date: Optional[str] = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.full_text.encode()).hexdigest()


@dataclass
class RunReport:
    source_type: str
    new_docs: int = 0
    amended_docs: int = 0
    superseded_docs: int = 0
    unchanged_docs: int = 0
    errors: list[str] = field(default_factory=list)
