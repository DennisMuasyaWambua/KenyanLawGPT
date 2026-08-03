"""Per-source-type crawlers for the self-updating public corpus.

Live mode targets kenyalaw.org's public listings; every crawler also ships
deterministic sample documents (real Kenyan law excerpts) so an offline or
fresh deployment still gets a working corpus — including a judgment with a
dissent, and an amendment chain that exercises the AMENDS/OVERTURNS edges.
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx
from bs4 import BeautifulSoup

from .models import LegalDocument, Opinion, Relation
from .registry import BaseCrawler, register


async def _fetch_listing(http: httpx.AsyncClient, url: str, selector: str, limit: int = 10) -> list[tuple[str, str]]:
    """Return (title, href) pairs from a kenyalaw listing page."""
    resp = await http.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    out = []
    for a in soup.select(selector)[:limit]:
        href = a.get("href") or ""
        title = a.get_text(strip=True)
        if title and href:
            out.append((title, href))
    return out


async def _fetch_body(http: httpx.AsyncClient, url: str) -> str:
    resp = await http.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    main = soup.select_one("article") or soup.select_one("main") or soup.body
    return main.get_text("\n", strip=True) if main else ""


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")[:80]


@register
class ConstitutionCrawler(BaseCrawler):
    source_type = "constitution"
    schedule = "weekly"

    async def fetch(self, http: httpx.AsyncClient) -> AsyncIterator[LegalDocument]:
        url = f"{self.cfg.kenyalaw_base}/akn/ke/act/2010/constitution"
        text = await _fetch_body(http, url)
        if text:
            yield LegalDocument(
                doc_id="constitution-2010", title="The Constitution of Kenya, 2010",
                doc_type="constitution", source_url=url, full_text=text, year=2010,
                citation="Constitution of Kenya, 2010",
            )

    def samples(self) -> list[LegalDocument]:
        return [LegalDocument(
            doc_id="constitution-2010",
            title="The Constitution of Kenya, 2010",
            doc_type="constitution",
            source_url="http://kenyalaw.org/kl/index.php?id=398",
            citation="Constitution of Kenya, 2010",
            year=2010,
            full_text=(
                "Article 41. Labour relations.\n"
                "(1) Every person has the right to fair labour practices.\n"
                "(2) Every worker has the right— (a) to fair remuneration; (b) to reasonable "
                "working conditions; (c) to form, join or participate in the activities and "
                "programmes of a trade union; and (d) to go on strike.\n\n"
                "Article 47. Fair administrative action.\n"
                "(1) Every person has the right to administrative action that is expeditious, "
                "efficient, lawful, reasonable and procedurally fair.\n\n"
                "Article 50. Fair hearing.\n"
                "(1) Every person has the right to have any dispute that can be resolved by the "
                "application of law decided in a fair and public hearing before a court or, if "
                "appropriate, another independent and impartial tribunal or body.\n\n"
                "Article 159. Judicial authority.\n"
                "(2) In exercising judicial authority, the courts and tribunals shall be guided "
                "by the following principles— (a) justice shall be done to all, irrespective of "
                "status; (b) justice shall not be delayed; (c) alternative forms of dispute "
                "resolution including reconciliation, mediation, arbitration and traditional "
                "dispute resolution mechanisms shall be promoted."
            ),
        )]


@register
class LegislationCrawler(BaseCrawler):
    source_type = "legislation"
    schedule = "weekly"

    async def fetch(self, http: httpx.AsyncClient) -> AsyncIterator[LegalDocument]:
        listing = await _fetch_listing(
            http, f"{self.cfg.kenyalaw_base}/legislation/", "td.cell-title a", limit=15)
        for title, href in listing:
            url = href if href.startswith("http") else self.cfg.kenyalaw_base + href
            text = await _fetch_body(http, url)
            if len(text) < 200:
                continue
            yield LegalDocument(
                doc_id="act-" + _slug(title), title=title, doc_type="statute",
                source_url=url, full_text=text, citation=title,
            )

    def samples(self) -> list[LegalDocument]:
        employment_v1 = LegalDocument(
            doc_id="act-2007-11-employment",
            title="Employment Act, No. 11 of 2007",
            doc_type="statute",
            source_url="http://kenyalaw.org/kl/fileadmin/pdfdownloads/Acts/EmploymentAct_Cap226-No11of2007_01.pdf",
            citation="Employment Act, No. 11 of 2007",
            year=2007,
            full_text=(
                "Section 35. Termination notice.\n"
                "(1) A contract of service not being a contract to perform specific work, without "
                "reference to time or to undertake a journey shall, if made to be performed in "
                "Kenya, be deemed to be— (c) where the contract is to pay wages or salary "
                "periodically at intervals of or exceeding one month, a contract terminable by "
                "either party at the end of the period of twenty-eight days next following the "
                "giving of notice in writing.\n\n"
                "Section 41. Notification and hearing before termination on grounds of misconduct.\n"
                "(1) Subject to section 42(1), an employer shall, before terminating the employment "
                "of an employee, on the grounds of misconduct, poor performance or physical "
                "incapacity explain to the employee, in a language the employee understands, the "
                "reason for which the employer is considering termination and the employee shall be "
                "entitled to have another employee or a shop floor union representative of his "
                "choice present during this explanation.\n\n"
                "Section 45. Unfair termination.\n"
                "(1) No employer shall terminate the employment of an employee unfairly.\n"
                "(2) A termination of employment by an employer is unfair if the employer fails to "
                "prove— (a) that the reason for the termination is valid; (b) that the reason for "
                "the termination is a fair reason— (i) related to the employee's conduct, capacity "
                "or compatibility; or (ii) based on the operational requirements of the employer; "
                "and (c) that the employment was terminated in accordance with fair procedure.\n\n"
                "Section 49. Remedies for wrongful dismissal and unfair termination.\n"
                "(1) Where in the opinion of a labour officer summary dismissal or termination of a "
                "contract of an employee is unjustified, the labour officer may recommend to the "
                "employer to pay to the employee— (c) the equivalent of a number of months wages or "
                "salary not exceeding twelve months based on the gross monthly wage or salary of "
                "the employee at the time of dismissal."
            ),
        )
        dpa = LegalDocument(
            doc_id="act-2019-24-data-protection",
            title="Data Protection Act, No. 24 of 2019",
            doc_type="statute",
            source_url="http://kenyalaw.org/kl/fileadmin/pdfdownloads/Acts/2019/TheDataProtectionAct__No24of2019.pdf",
            citation="Data Protection Act, No. 24 of 2019",
            year=2019,
            full_text=(
                "Section 25. Principles of data protection.\n"
                "Every data controller or data processor shall ensure that personal data is— "
                "(a) processed in accordance with the right to privacy of the data subject; "
                "(b) processed lawfully, fairly and in a transparent manner in relation to any data "
                "subject; (c) collected for explicit, specified and legitimate purposes.\n\n"
                "Section 26. Rights of a data subject.\n"
                "A data subject has a right— (a) to be informed of the use to which their personal "
                "data is to be put; (b) to access their personal data in custody of data controller "
                "or data processor; (c) to object to the processing of all or part of their "
                "personal data; (d) to correction of false or misleading data; and (e) to deletion "
                "of false or misleading data about them.\n\n"
                "Section 40. Right to erasure... a data subject may request a data controller to "
                "erase or destroy personal data that the data controller is no longer authorised "
                "to retain, or that is irrelevant, excessive or obtained unlawfully."
            ),
        )
        # A superseded revision to exercise the AMENDS chain + status handling.
        employment_amendment = LegalDocument(
            doc_id="act-2022-employment-amendment",
            title="Employment (Amendment) Act, 2022",
            doc_type="statute",
            source_url="http://kenyalaw.org/kl/",
            citation="Employment (Amendment) Act, 2022",
            year=2022,
            full_text=(
                "Section 2. Amendment of section 29 of the Employment Act, 2007: an employee who "
                "has taken paternity leave... The Employment Act is amended to expand parental "
                "leave entitlements including pre-adoptive leave of one month with full pay."
            ),
            relations=[Relation(rel_type="AMENDS", target_doc_id="act-2007-11-employment")],
        )
        return [employment_v1, dpa, employment_amendment]


@register
class CaseLawCrawler(BaseCrawler):
    source_type = "case_law"
    schedule = "weekly"

    async def fetch(self, http: httpx.AsyncClient) -> AsyncIterator[LegalDocument]:
        listing = await _fetch_listing(
            http, f"{self.cfg.kenyalaw_base}/judgments/", "td.cell-title a", limit=15)
        for title, href in listing:
            url = href if href.startswith("http") else self.cfg.kenyalaw_base + href
            text = await _fetch_body(http, url)
            if len(text) < 300:
                continue
            yield LegalDocument(
                doc_id="case-" + _slug(title), title=title, doc_type="case_law",
                source_url=url, full_text=text, citation=title,
            )

    def samples(self) -> list[LegalDocument]:
        walter_ogal = LegalDocument(
            doc_id="case-2013-eklr-walter-ogal-anuro",
            title="Walter Ogal Anuro v Teachers Service Commission [2013] eKLR",
            doc_type="case_law",
            source_url="http://kenyalaw.org/caselaw/cases/view/91880",
            citation="[2013] eKLR",
            court="Employment and Labour Relations Court",
            year=2013,
            authored_by=["Maureen Onyango J"],
            full_text=(
                "The court held that for a termination of employment to pass the fairness test, "
                "there must be both substantive justification and procedural fairness. Substantive "
                "justification relates to the reasons for termination under section 45 of the "
                "Employment Act, while procedural fairness addresses the procedure adopted by the "
                "employer in effecting the termination, per section 41 of the Employment Act. "
                "Failure to subject the employee to due process before dismissal renders the "
                "termination unfair notwithstanding the existence of a valid reason."
            ),
            relations=[
                Relation(rel_type="INTERPRETS", target_doc_id="act-2007-11-employment"),
                Relation(rel_type="CITES", target_doc_id="constitution-2010"),
            ],
            opinions=[Opinion(
                judge="Maureen Onyango J", kind="majority",
                text="Both substantive justification and procedural fairness are required for a "
                     "termination to be fair under sections 41, 43 and 45 of the Employment Act.",
            )],
        )
        kenfreight = LegalDocument(
            doc_id="case-2016-sc-kenfreight",
            title="Kenfreight (E.A.) Limited v Benson K. Nguti [2016] eKLR (Supreme Court)",
            doc_type="case_law",
            source_url="http://kenyalaw.org/caselaw/cases/view/130269",
            citation="[2016] eKLR",
            court="Supreme Court of Kenya",
            year=2016,
            authored_by=["Maraga CJ", "Ibrahim SCJ", "Ojwang SCJ", "Wanjala SCJ", "Njoki SCJ"],
            full_text=(
                "MAJORITY: On the question of notice pay and the interplay between contractual "
                "notice and statutory minima, the Supreme Court affirmed that an employer may "
                "terminate by notice or pay in lieu, but where the reason for termination is "
                "contested, sections 41, 43 and 45 of the Employment Act impose mandatory "
                "procedural safeguards. The appeal was allowed in part.\n\n"
                "DISSENT (Njoki SCJ): I would have dismissed the appeal in its entirety. The "
                "constitutional right to fair labour practices under Article 41 elevates "
                "procedural fairness to a non-derogable minimum; pay in lieu of notice cannot "
                "cure a procedurally unfair dismissal."
            ),
            relations=[
                Relation(rel_type="INTERPRETS", target_doc_id="act-2007-11-employment"),
                Relation(rel_type="DISTINGUISHES", target_doc_id="case-2013-eklr-walter-ogal-anuro"),
            ],
            opinions=[
                Opinion(judge="Maraga CJ", kind="majority",
                        text="Termination by notice or pay in lieu remains lawful, subject to the "
                             "mandatory procedural safeguards of sections 41, 43 and 45 where the "
                             "reason is contested."),
                Opinion(judge="Njoki SCJ", kind="dissent",
                        text="Article 41 of the Constitution elevates procedural fairness to a "
                             "non-derogable minimum; pay in lieu of notice cannot cure a "
                             "procedurally unfair dismissal."),
            ],
        )
        return [walter_ogal, kenfreight]


@register
class GazetteCrawler(BaseCrawler):
    source_type = "gazette"
    schedule = "daily"

    async def fetch(self, http: httpx.AsyncClient) -> AsyncIterator[LegalDocument]:
        listing = await _fetch_listing(
            http, f"{self.cfg.kenyalaw_base}/gazettes/", "td.cell-title a", limit=8)
        for title, href in listing:
            url = href if href.startswith("http") else self.cfg.kenyalaw_base + href
            text = await _fetch_body(http, url)
            if len(text) < 100:
                continue
            yield LegalDocument(
                doc_id="gazette-" + _slug(title), title=title, doc_type="gazette",
                source_url=url, full_text=text, citation=title,
            )

    def samples(self) -> list[LegalDocument]:
        return [LegalDocument(
            doc_id="gazette-2026-vol-cxxviii-12",
            title="Kenya Gazette Vol. CXXVIII — No. 12 (sample notice)",
            doc_type="gazette",
            source_url="http://kenyalaw.org/kenya_gazette/",
            citation="Kenya Gazette Vol. CXXVIII No. 12",
            year=2026,
            full_text=(
                "GAZETTE NOTICE — THE LAND REGISTRATION ACT (No. 3 of 2012): issuance of a new "
                "certificate of lease for LR No. 209/1234, Nairobi, the original having been "
                "reported lost. Objections to be lodged within sixty (60) days.\n\n"
                "GAZETTE NOTICE — THE EMPLOYMENT AND LABOUR RELATIONS COURT: practice directions "
                "on electronic filing of pleadings and service of process through the Judiciary "
                "e-filing platform."
            ),
        )]


@register
class LSKGuidelinesCrawler(BaseCrawler):
    source_type = "lsk_guidelines"
    schedule = "weekly"

    async def fetch(self, http: httpx.AsyncClient) -> AsyncIterator[LegalDocument]:
        # LSK publishes guidance on lsk.or.ke; treat as best-effort scrape.
        listing = await _fetch_listing(http, "https://lsk.or.ke/resources/", "article a", limit=6)
        for title, href in listing:
            text = await _fetch_body(http, href)
            if len(text) < 200:
                continue
            yield LegalDocument(
                doc_id="lsk-" + _slug(title), title=title, doc_type="guideline",
                source_url=href, full_text=text, citation="LSK: " + title,
            )

    def samples(self) -> list[LegalDocument]:
        return [LegalDocument(
            doc_id="lsk-remuneration-guidance-2025",
            title="LSK Guidance Note: Advocates Remuneration Order and Fee Undercutting",
            doc_type="guideline",
            source_url="https://lsk.or.ke/",
            citation="LSK Guidance Note (2025)",
            year=2025,
            full_text=(
                "The Law Society of Kenya reminds members that charging below the minimum fees "
                "prescribed in the Advocates Remuneration Order constitutes professional "
                "misconduct. Members handling employment disputes before the ELRC should have "
                "regard to Schedule VI on contentious matters, and are reminded of the duty of "
                "candour to the court and the obligation of client confidentiality under the "
                "Advocates Act and the LSK Code of Standards of Professional Practice and "
                "Ethical Conduct."
            ),
        )]


@register
class CauseListCrawler(BaseCrawler):
    source_type = "cause_lists"
    schedule = "daily"

    async def fetch(self, http: httpx.AsyncClient) -> AsyncIterator[LegalDocument]:
        listing = await _fetch_listing(
            http, f"{self.cfg.kenyalaw_base}/causelists/", "td.cell-title a", limit=6)
        for title, href in listing:
            url = href if href.startswith("http") else self.cfg.kenyalaw_base + href
            text = await _fetch_body(http, url)
            if len(text) < 50:
                continue
            yield LegalDocument(
                doc_id="causelist-" + _slug(title), title=title, doc_type="cause_list",
                source_url=url, full_text=text, citation=title,
            )

    def samples(self) -> list[LegalDocument]:
        return [LegalDocument(
            doc_id="causelist-elrc-milimani-sample",
            title="ELRC Milimani — Daily Cause List (sample)",
            doc_type="cause_list",
            source_url="http://kenyalaw.org/causelist/",
            citation="ELRC Milimani Cause List",
            year=2026,
            full_text=(
                "EMPLOYMENT AND LABOUR RELATIONS COURT AT NAIROBI (MILIMANI) — COURT 3\n"
                "BEFORE HON. JUSTICE (SAMPLE)\n"
                "9:00 AM — ELRC E123 of 2026 — Mention — parties to confirm filing of witness "
                "statements.\n"
                "11:00 AM — ELRC E456 of 2025 — Hearing — claimant's case."
            ),
        )]
