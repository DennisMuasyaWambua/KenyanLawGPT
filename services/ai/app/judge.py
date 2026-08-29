"""Judge-aware reasoning (Task 4).

Assembles a "what has worked before Judge X" pattern summary from two strictly
separated sources and merges them in Python:

  * PUBLIC  — the shared judge profile + RULED_ON history (read via
    PublicGraphQuery; visible to every tenant).
  * TENANT  — this firm's own files before that judge, the submissions that
    led to favourable outcomes, and the authorities they cited (read via
    TenantScopedGraphQuery only; invisible to any other tenant).

The result is handed to the LLM clearly labelled as firm-internal historical
pattern, NOT settled law.

LEGAL/ETHICS NOTE: statistical profiling of individual judges is common legal
tech but some jurisdictions restrict it. This is a firm-internal tool; the
disclaimer below travels with every summary, and it must be reviewed against
Law Society of Kenya / Judiciary of Kenya guidance before any external-facing
use. Gated behind ENABLE_JUDGE_REASONING.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .graph import Graph, PublicGraphQuery, TenantScopedGraphQuery
from .logging_setup import log

JUDICIAL_ANALYTICS_DISCLAIMER = (
    "FIRM-INTERNAL HISTORICAL PATTERN — summarises this firm's own past files "
    "and public case records before this judge. It is NOT settled law and NOT a "
    "prediction of how the judge will rule; treat it as background experience only."
)

# "before Justice Mwangi", "Judge Peter Omondi", "coram Hon. Lady Justice Aoko".
# 'before/coram' is an optional lead-in; 'justice|judge' is the real trigger so
# "before Judge X" captures X, not "Judge X".
_JUDGE_Q_RE = re.compile(
    r"\b(?:(?:before|coram)\s+)?(?:hon\.?\s+)?(?:the\s+)?"
    r"(?:(?:mr|mrs|ms|lady|lord)\.?\s+)?(?:justice|judge)\s+"
    r"([A-Z][A-Za-z.\-]+(?:\s+[A-Z][A-Za-z.\-]+){0,2})",
    re.I,
)
_FAVORABLE = {"won", "settled"}


@dataclass
class JudgePattern:
    judge_name: str
    tenant_cases: int = 0
    tenant_favorable: int = 0
    winning_authorities: list[tuple[str, int]] = field(default_factory=list)
    public: dict = field(default_factory=dict)

    @property
    def has_signal(self) -> bool:
        return self.tenant_cases > 0 or bool(self.public.get("rulings_count"))


class JudgeReasoner:
    def __init__(self, pool, graph: Graph, cfg) -> None:
        self.pool = pool
        self.graph = graph
        self.cfg = cfg

    @staticmethod
    def detect_judge_name(query: str) -> Optional[str]:
        m = _JUDGE_Q_RE.search(query or "")
        if not m:
            return None
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        # Drop a trailing rank token the query might include ("Mwangi J").
        name = re.sub(r"\b(J|JA|SCJ|CJ|DCJ)\.?$", "", name).strip()
        return name or None

    async def public_profile(self, judge_name: str) -> dict:
        try:
            rows = await self.graph.read(
                PublicGraphQuery().match("j", "Judge", name=judge_name)
                .returns("j.rulings_count AS rulings_count",
                         "j.favored_plaintiff AS favored_plaintiff",
                         "j.favored_defendant AS favored_defendant")
                .limit(1).build())
            return rows[0] if rows else {}
        except Exception as exc:
            log().warning("public judge profile read failed: %s", exc)
            return {}

    async def tenant_pattern(self, tenant_id: str, judge_name: str) -> tuple[int, int, list]:
        """Aggregate THIS tenant's history before the judge. Every query is
        tenant-scoped; a competitor's files can never appear here."""
        rows = await self.graph.read(
            TenantScopedGraphQuery(tenant_id)
            .match("m", "File")
            .where_prop("m", "judge_name", "=", judge_name)
            .match_rel("m", ["RESULTED_IN"], "o", "Outcome", direction="any")
            .returns("m.id AS file_id", "o.result AS result")
            .limit(300).build())
        total = len(rows)
        winning_ids = [r["file_id"] for r in rows if (r.get("result") or "") in _FAVORABLE]

        authorities: Counter[str] = Counter()
        if winning_ids:
            for public_label in ("Statute", "CaseLaw"):
                try:
                    cited = await self.graph.read(
                        TenantScopedGraphQuery(tenant_id)
                        .match("m", "File")
                        .where_in("m", "id", winning_ids)
                        .match_rel("m", ["FILED_IN"], "s", "Submission", direction="any")
                        .match_rel("s", ["CITES"], "x", public_label, to_public=True, direction="any")
                        .returns("x.title AS title")
                        .limit(300).build())
                    authorities.update(r["title"] for r in cited if r.get("title"))
                except Exception as exc:
                    log().warning("winning-authority read (%s) failed: %s", public_label, exc)
        return total, len(winning_ids), authorities.most_common(5)

    async def build(self, tenant_id: str, judge_name: str) -> JudgePattern:
        total, favorable, authorities = await self.tenant_pattern(tenant_id, judge_name)
        public = await self.public_profile(judge_name)
        return JudgePattern(
            judge_name=judge_name, tenant_cases=total, tenant_favorable=favorable,
            winning_authorities=authorities, public=public,
        )

    async def context_block(self, tenant_id: str, judge_name: str) -> str:
        """Labelled context to append to the LLM prompt, or "" if no signal."""
        p = await self.build(tenant_id, judge_name)
        if not p.has_signal:
            return ""
        lines = [f"[{JUDICIAL_ANALYTICS_DISCLAIMER}]", f"Judge: {p.judge_name}"]
        if p.tenant_cases:
            lines.append(
                f"This firm has {p.tenant_cases} prior file(s) before this judge; "
                f"{p.tenant_favorable} had a favourable outcome.")
            if p.winning_authorities:
                cites = ", ".join(f"{t} (x{c})" for t, c in p.winning_authorities)
                lines.append(f"Authorities most cited in the firm's favourable submissions: {cites}.")
        rc = p.public.get("rulings_count")
        if rc:
            lines.append(
                f"Public record: {rc} ruling(s) attributed to this judge "
                f"({p.public.get('favored_plaintiff') or 0} favoured the plaintiff/"
                f"petitioner, {p.public.get('favored_defendant') or 0} the defendant/respondent).")
        return "\n".join(lines)
