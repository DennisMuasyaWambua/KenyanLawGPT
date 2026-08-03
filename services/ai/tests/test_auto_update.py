"""Auto-update change classification (Task 5). DB-backed temporal + watermark
behaviour is exercised in the integration suite; this covers the pure logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.auto_update import classify_change
from app.ingestion.models import LegalDocument, Relation


def _doc(text="body", relations=None):
    return LegalDocument(
        doc_id="act-x", title="Some Act", doc_type="statute", source_url="",
        full_text=text, relations=relations or [])


def test_brand_new_instrument():
    assert classify_change(_doc(), existing_hash=None) == "new"


def test_unchanged_when_hash_matches():
    d = _doc()
    assert classify_change(d, existing_hash=d.content_hash) == "unchanged"


def test_changed_content_is_amends():
    d = _doc("new text")
    assert classify_change(d, existing_hash="an-old-different-hash") == "amends"


def test_explicit_repeals_relation():
    d = _doc(relations=[Relation("REPEALS", "act-old")])
    assert classify_change(d, existing_hash=None) == "repeals"


def test_explicit_amends_relation_on_new_doc():
    d = _doc(relations=[Relation("AMENDS", "act-old")])
    assert classify_change(d, existing_hash=None) == "amends"
