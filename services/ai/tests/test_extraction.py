"""Deterministic entity/citation extraction for firm court filings (Task 3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.extraction import classify_doc_kind, extract_entities

SUBMISSION = """REPUBLIC OF KENYA
IN THE ENVIRONMENT AND LAND COURT AT NAIROBI
ELC Case No. 123 of 2019
CORAM: HON. JUSTICE JANE MWANGI
JANE DOE .......................... PLAINTIFF
VERSUS
ACME PROPERTIES LIMITED ........... DEFENDANT

WRITTEN SUBMISSIONS FOR THE PLAINTIFF

The Plaintiff relies on Section 26 of the Land Registration Act and on
Article 40 of the Constitution of Kenya. See also Kamau v Njoroge [2015] eKLR.

DATED at Nairobi this 10th March 2020
Filed by: Otieno & Co. Advocates
"""

RULING = """REPUBLIC OF KENYA
IN THE HIGH COURT AT NAIROBI
Civil Suit No. 45 of 2018
CORAM: HON. JUSTICE PETER OMONDI

RULING

Having considered the pleadings and the Land Act, the suit is hereby dismissed
with costs to the Defendant.

DATED this 5th June 2021
"""


def test_classify_doc_kind():
    assert classify_doc_kind("submissions.pdf", SUBMISSION) == "submission"
    assert classify_doc_kind("ruling.pdf", RULING) == "ruling"
    assert classify_doc_kind("lease_agreement.pdf", "This lease is made between...") == "document"


def test_submission_entities():
    e = extract_entities(SUBMISSION, "submissions.pdf")
    assert e.case_ref and "123 of 2019" in e.case_ref
    assert e.judge_name and "MWANGI" in e.judge_name.upper()
    assert any("Otieno" in a for a in e.advocates)
    assert "Land Registration Act" in e.act_citations
    assert "Constitution of Kenya" in e.act_citations
    assert any("eKLR" in c for c in e.case_citations)
    # A submission carries no outcome of its own.
    assert e.outcome is None


def test_ruling_outcome_extraction():
    e = extract_entities(RULING, "ruling.pdf")
    assert e.outcome is not None
    assert e.outcome["result"] == "lost"  # "suit is hereby dismissed"
    assert e.judge_name and "OMONDI" in e.judge_name.upper()


def test_no_false_positive_outcome_on_plain_contract():
    e = extract_entities("This Tenancy Agreement is made between the parties.", "lease.pdf")
    assert e.outcome is None
    assert e.case_ref is None
