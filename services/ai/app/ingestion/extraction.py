"""Deterministic entity/citation extraction for firm court filings.

Pulls the advocate(s), the case reference/parties, the presiding judge, the
outcome, and the public authorities cited out of a pleading/submission/ruling
so the ingestion pipeline can build the judge-reasoning subgraph
(Advocate-AUTHORED->Submission-FILED_IN->Matter-DECIDED_BY->Judge,
Matter-RESULTED_IN->Outcome).

Regex-first so it is deterministic and works offline (tests + the mock LLM).
An LLM refinement hook can be layered on later for messy documents; it must
never be the *only* path, or extraction stops being testable offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# --- citation patterns (shared shape with tenant_ingest needles) --------------
_ACT_RE = re.compile(r"\b([A-Z][A-Za-z' ]{2,40} Act)(?:[, ]+(?:No\.? ?\d+ of )?(\d{4}))?", re.M)
_SECTION_RE = re.compile(r"\bSection\s+\d+[A-Za-z]?\s+of\s+the\s+([A-Z][A-Za-z' ]{2,40} Act)", re.I)
_EKLR_RE = re.compile(r"([A-Z][A-Za-z .,'&]+?\s+v(?:s|ersus)?\.?\s+[A-Z][A-Za-z .,'&]+?\s*\[\d{4}\]\s*eKLR)")
_CONSTITUTION_RE = re.compile(r"\bArticle\s+\d+\b|\bConstitution of Kenya\b", re.I)

# --- structural patterns ------------------------------------------------------
_CASE_REF_RE = re.compile(
    r"\b((?:Constitutional\s+)?Petition|Civil\s+(?:Suit|Case|Appeal|Application)|"
    r"Criminal\s+(?:Case|Appeal|Revision)|Misc(?:ellaneous)?\.?\s+(?:Civil\s+)?Application|"
    r"Cause|ELC\s+(?:Case|Suit|Petition)|Succession\s+Cause|Judicial\s+Review)\s+"
    r"(?:No\.?\s*)?(\d+)\s+of\s+(\d{4})", re.I)
_PARTIES_RE = re.compile(
    r"\b([A-Z][A-Za-z.,'&() ]{2,60}?)\s+v(?:s|ersus)?\.?\s+([A-Z][A-Za-z.,'&() ]{2,60})")
_JUDGE_RE = re.compile(
    r"(?:CORAM|BEFORE)\s*[:\-]?\s*(?:THE\s+)?(?:HON\.?(?:OURABLE)?\.?\s+)?"
    r"(?:(?:MR|MRS|MS|LADY|LORD)\.?\s+)?(?:JUSTICE|JUDGE|J\.?)\s+"
    r"([A-Z][A-Za-z.\- ]{2,40}?)(?:\s+(?:J|JA|SCJ|CJ|DCJ)\.?)?\s*(?:\n|,|$)", re.I)
_JUDGE_SUFFIX_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(J|JA|SCJ|CJ|DCJ)\b")
_ADVOCATE_RE = re.compile(
    r"(?:filed|drawn|lodged)\s+by\s*[:\-]?\s*([A-Z][A-Za-z.&' ]{3,60})|"
    r"([A-Z][A-Za-z.&' ]{3,50}(?:Advocates|& Co\.? Advocates|& Company Advocates|LLP))",
)

# Outcome keyword → normalized result.
_OUTCOME_PATTERNS = [
    ("won", re.compile(r"\b(?:judg(?:e)?ment\s+(?:is\s+)?entered\s+for\s+the\s+(?:plaintiff|petitioner|applicant|claimant)|"
                       r"(?:suit|petition|application|appeal|claim)\s+(?:is\s+)?(?:hereby\s+)?allowed|"
                       r"in\s+favou?r\s+of\s+the\s+(?:plaintiff|petitioner|applicant|claimant))\b", re.I)),
    ("lost", re.compile(r"\b(?:(?:suit|petition|application|appeal|claim)\s+(?:is\s+)?(?:hereby\s+)?dismissed|"
                        r"struck\s+out|judg(?:e)?ment\s+(?:is\s+)?entered\s+for\s+the\s+(?:defendant|respondent))\b", re.I)),
    ("settled", re.compile(r"\b(?:recorded\s+as\s+a\s+consent|by\s+consent|settled\s+out\s+of\s+court|"
                           r"consent\s+judg(?:e)?ment|terms\s+of\s+settlement)\b", re.I)),
]
_DATE_RE = re.compile(r"\b(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})\b")

_SUBMISSION_HINTS = ("submission", "pleading", "plaint", "petition", "affidavit",
                     "written submission", "grounds of", "notice of motion")
_RULING_HINTS = ("ruling", "judgment", "judgement", "decree", "decision")


@dataclass
class ExtractedEntities:
    advocates: list[str] = field(default_factory=list)
    case_ref: Optional[str] = None
    parties: Optional[str] = None
    judge_name: Optional[str] = None
    outcome: Optional[dict] = None  # {"result","date","notes"}
    act_citations: list[str] = field(default_factory=list)
    case_citations: list[str] = field(default_factory=list)


def classify_doc_kind(filename: str, text: str) -> str:
    """Coarse document classification (no proto field yet): submission | ruling
    | document. Only submissions/rulings get the judge-reasoning subgraph."""
    hay = f"{filename}\n{text[:2000]}".lower()
    if any(h in hay for h in _RULING_HINTS):
        return "ruling"
    if any(h in hay for h in _SUBMISSION_HINTS):
        return "submission"
    return "document"


def _clean(s: str) -> str:
    s = re.sub(r"\.{2,}", " ", s or "")   # collapse the dotted leaders pleadings use
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,-")


def extract_entities(text: str, filename: str = "") -> ExtractedEntities:
    e = ExtractedEntities()
    head = text[:6000]  # case/judge/advocate metadata lives at the top
    tail = text[-6000:]  # outcome lives at the end of a ruling

    m = _CASE_REF_RE.search(head)
    if m:
        e.case_ref = _clean(m.group(0))
    p = _PARTIES_RE.search(head)
    if p:
        e.parties = f"{_clean(p.group(1))} v {_clean(p.group(2))}"

    j = _JUDGE_RE.search(head) or _JUDGE_SUFFIX_RE.search(head)
    if j:
        e.judge_name = _clean(j.group(1))

    advs: list[str] = []
    for am in _ADVOCATE_RE.finditer(text):
        name = _clean(am.group(1) or am.group(2) or "")
        if name and name not in advs:
            advs.append(name)
    e.advocates = advs[:5]

    for result, pat in _OUTCOME_PATTERNS:
        om = pat.search(tail) or pat.search(text)
        if om:
            dm = _DATE_RE.search(tail)
            e.outcome = {
                "result": result,
                "date": _clean(dm.group(1)) if dm else "",
                "notes": _clean(om.group(0)),
            }
            break

    acts = {_clean(m.group(1)) for m in _ACT_RE.finditer(text)}
    acts |= {_clean(m.group(1)) for m in _SECTION_RE.finditer(text)}
    if _CONSTITUTION_RE.search(text):
        acts.add("Constitution of Kenya")
    e.act_citations = sorted(acts)[:12]
    e.case_citations = list({_clean(m.group(1)) for m in _EKLR_RE.finditer(text)})[:12]
    return e
