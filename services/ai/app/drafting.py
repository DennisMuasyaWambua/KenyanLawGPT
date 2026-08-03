"""AI document drafting: Kenyan legal templates + tenant clause library +
retrieval-grounded context, streamed token-by-token over gRPC.
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

import asyncpg

from . import db as dbx
from .config import Config
from .llm import CONFIDENTIALITY_PREAMBLE, LLMProvider
from .logging_setup import log
from .retrieval import RankedChunk, RetrievalOrchestrator

# Skeletons follow common Kenyan practice formats; the LLM adapts them with
# matter facts, clause-library language, and retrieved authority.
TEMPLATES: dict[str, str] = {
    "pleading": """REPUBLIC OF KENYA
IN THE {court} AT {registry}
{case_type} NO. ____ OF {year}

{claimant_name} .......................................... CLAIMANT/PLAINTIFF
-VERSUS-
{respondent_name} ................................. RESPONDENT/DEFENDANT

{pleading_title}

1. The Claimant is an adult of sound mind residing and working for gain in {location}.
2. The Respondent is {respondent_description}.
[Set out numbered material facts chronologically.]
[Set out the legal foundation, citing the specific statutory provisions.]

REASONS WHEREFORE the Claimant prays for judgment against the Respondent for:
(a) ...
(b) Costs of this suit;
(c) Any other relief this Honourable Court may deem just to grant.

DATED at NAIROBI this ____ day of ________ {year}

DRAWN & FILED BY:
{firm_name}
Advocates for the Claimant""",

    "affidavit": """REPUBLIC OF KENYA
IN THE {court} AT {registry}
{case_type} NO. ____ OF {year}

AFFIDAVIT

I, {deponent_name}, of Post Office Box Number ____, {location}, do hereby
make oath and state as follows:

1. THAT I am the {deponent_capacity} and hence competent to swear this affidavit.
2. THAT [facts within the deponent's knowledge, one per paragraph].
3. THAT what is deponed to herein is true to the best of my knowledge save
   for matters based on information the sources whereof have been disclosed.

SWORN at NAIROBI by the said        )
{deponent_name}                     )    ________________
this ____ day of ________ {year}    )       DEPONENT

BEFORE ME
COMMISSIONER FOR OATHS""",

    "demand_letter": """{firm_name}
Advocates
{firm_address}

Our Ref: {reference}                                    Date: {date}

WITHOUT PREJUDICE — LETTER OF DEMAND

Dear Sir/Madam,

RE: {subject}

We act for {client_name}, on whose instructions we address you as follows.
[State the facts giving rise to the claim.]
[State the legal basis, citing the applicable Kenyan statutes.]

TAKE NOTICE that unless we receive {demand} within {days} days of the date
hereof, we hold firm instructions to institute legal proceedings against you
without further reference to you, at your own risk as to costs and interest.

Yours faithfully,

{advocate_name}
For: {firm_name}""",

    "contract": """AGREEMENT

THIS AGREEMENT is made this ____ day of ________ {year}

BETWEEN

{party_a} (hereinafter "the First Party") of the one part; and
{party_b} (hereinafter "the Second Party") of the other part.

WHEREAS:
(A) [Recitals.]

NOW THEREFORE IT IS AGREED as follows:
1. DEFINITIONS AND INTERPRETATION
2. [Operative clauses.]
3. GOVERNING LAW — This Agreement shall be governed by the laws of Kenya.
4. DISPUTE RESOLUTION
5. DATA PROTECTION — The parties shall comply with the Data Protection Act, 2019.

IN WITNESS WHEREOF the parties have executed this Agreement.

SIGNED by {party_a} ........................
SIGNED by {party_b} ........................""",

    "correspondence": """{firm_name}
Advocates
{firm_address}

Our Ref: {reference}                                    Date: {date}

{recipient}

Dear {salutation},

RE: {subject}

[Body.]

Yours faithfully,

{advocate_name}
For: {firm_name}""",
}


class DraftingEngine:
    def __init__(self, pool: asyncpg.Pool, retriever: RetrievalOrchestrator,
                 llm: LLMProvider, cfg: Config) -> None:
        self.pool = pool
        self.retriever = retriever
        self.llm = llm
        self.cfg = cfg

    async def _matter_facts(self, tenant_id: str, matter_id: str) -> str:
        try:
            async with dbx.tenant_tx(self.pool, tenant_id) as conn:
                row = await conn.fetchrow(
                    """SELECT m.reference, m.title, m.description, m.practice_area, m.court,
                              m.court_case_number, COALESCE(c.name,'') AS client_name
                       FROM matters m LEFT JOIN clients c ON c.id = m.client_id
                       WHERE m.id = $1""", matter_id)
            if not row:
                return ""
            return (f"Matter reference: {row['reference']}\nMatter: {row['title']}\n"
                    f"Client: {row['client_name']}\nPractice area: {row['practice_area']}\n"
                    f"Court: {row['court']} {row['court_case_number']}\n"
                    f"Background: {row['description']}")
        except Exception as exc:
            log().warning("matter facts lookup failed: %s", exc)
            return ""

    async def _clauses(self, tenant_id: str, template_id: Optional[str]) -> str:
        try:
            async with dbx.tenant_tx(self.pool, tenant_id) as conn:
                if template_id:
                    rows = await conn.fetch(
                        "SELECT title, body FROM clause_library WHERE id::text = $1", template_id)
                else:
                    rows = await conn.fetch(
                        "SELECT title, body FROM clause_library ORDER BY created_at LIMIT 6")
            return "\n\n".join(f"[{r['title']}]\n{r['body']}" for r in rows)
        except Exception as exc:
            log().warning("clause library lookup failed: %s", exc)
            return ""

    async def draft(
        self,
        tenant_id: str,
        doc_type: str,
        instructions: str,
        matter_id: Optional[str] = None,
        template_id: Optional[str] = None,
        context_query: Optional[str] = None,
    ) -> tuple[AsyncIterator[str], list[RankedChunk]]:
        """Returns (token stream, provenance-tagged citations used)."""
        template = TEMPLATES.get(doc_type, TEMPLATES["correspondence"])
        facts = await self._matter_facts(tenant_id, matter_id) if matter_id else ""
        clauses = await self._clauses(tenant_id, template_id)

        citations: list[RankedChunk] = []
        law_context = ""
        query = context_query or instructions
        try:
            chunks, _ = await self.retriever.retrieve(tenant_id, query, top_k=6, matter_id=matter_id)
            citations = chunks
            law_context = "\n\n".join(
                f"[{i}] ({c.source_type}) {c.citation or c.source_id}\n{c.text}"
                for i, c in enumerate(chunks, 1)
            )
        except Exception as exc:
            log().warning("draft grounding retrieval failed: %s", exc)

        system = (
            "You are WakiliAI's drafting engine for Kenyan legal documents. Produce a "
            "complete, professional draft in the house style of Kenyan practice. Use the "
            "provided template as the structural skeleton, fill in what the instructions "
            "and matter facts support, and leave square-bracket placeholders for anything "
            "unknown. Ground legal assertions in the provided authorities and cite them "
            "inline as [n]. Do not invent citations. "
            + CONFIDENTIALITY_PREAMBLE
        )
        prompt = (
            f"Document type: {doc_type}\n\nInstructions from the advocate:\n{instructions}\n\n"
            + (f"Matter facts:\n{facts}\n\n" if facts else "")
            + (f"Firm clause library (prefer this language):\n{clauses}\n\n" if clauses else "")
            + (f"--- CONTEXT ---\n{law_context}\n--- END CONTEXT ---\n\n" if law_context else "")
            + f"Template skeleton:\n{template}\n"
        )
        return self.llm.stream(system=system, prompt=prompt, max_tokens=8192), citations
