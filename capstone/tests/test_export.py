import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag_eval.export_pg import build_record, mine_text_citations, merge_edges, select


class ExportTests(unittest.TestCase):
    def row(self, i, text="x" * 600, cite=""):
        return {"doc_id": i, "title": "T" + i, "court": "HC", "year": 2020, "citation": cite,
                "doc_type": "case_law", "source_url": "", "full_text": text}

    def test_prefers_full_text_else_chunks(self):
        self.assertEqual(build_record(self.row("a", "full"), ["c1"])["text"], "full")
        self.assertEqual(build_record(self.row("a", ""), ["c1", "c2"])["text"], "c1\n\nc2")
        self.assertIsNone(build_record(self.row("a", ""), []))

    def test_text_citation_mining(self):
        a = build_record(self.row("a", "as held in Civil Appeal No. 12 of 2016 the court"), [])
        b = build_record(self.row("b", "other text", cite="Civil Appeal No. 12 of 2016"), [])
        self.assertEqual(mine_text_citations([a, b]), 1)
        self.assertEqual(a["cites"], ["b"]); self.assertEqual(b["cites"], [])

    def test_merge_edges_ignores_unknown_and_self(self):
        a, b = build_record(self.row("a"), []), build_record(self.row("b"), [])
        self.assertEqual(merge_edges([a, b], [("a", "b"), ("a", "a"), ("a", "zzz"), ("a", "b")]), 1)

    def test_select_is_reproducible_and_filters_stubs(self):
        recs = [build_record(self.row(str(i)), []) for i in range(20)] + [build_record(self.row("s", "tiny"), [])]
        s1, s2 = select(recs, 500, 5, 1), select(recs, 500, 5, 1)
        self.assertEqual([r["doc_id"] for r in s1], [r["doc_id"] for r in s2])
        self.assertEqual(len(s1), 5); self.assertNotIn("s", [r["doc_id"] for r in s1])


if __name__ == "__main__":
    unittest.main()
