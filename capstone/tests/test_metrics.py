import math, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag_eval import metrics as m
from rag_eval.corpus import clean_text, inject_ocr_noise, chunk_text
from rag_eval.retrievers import BM25, rrf, graph_expand, to_doc_ranking
import numpy as np


class MetricTests(unittest.TestCase):
    rel = {"a": 3, "b": 1}

    def test_recall_precision_hit(self):
        r = ["x", "a", "y", "b"]
        self.assertEqual(m.recall_at_k(r, self.rel, 2), 0.5)
        self.assertEqual(m.recall_at_k(r, self.rel, 4), 1.0)
        self.assertEqual(m.precision_at_k(r, self.rel, 4), 0.5)
        self.assertEqual(m.hit_at_k(r, self.rel, 1), 0.0)

    def test_mrr(self):
        self.assertEqual(m.mrr(["x", "a"], self.rel), 0.5)
        self.assertEqual(m.mrr(["x", "y"], self.rel), 0.0)

    def test_ndcg_perfect_and_worse(self):
        self.assertAlmostEqual(m.ndcg_at_k(["a", "b"], self.rel, 2), 1.0)
        self.assertLess(m.ndcg_at_k(["b", "a"], self.rel, 2), 1.0)
        exp = (2**1 - 1) / math.log2(2) + (2**3 - 1) / math.log2(3)
        ideal = (2**3 - 1) / math.log2(2) + (2**1 - 1) / math.log2(3)
        self.assertAlmostEqual(m.ndcg_at_k(["b", "a"], self.rel, 2), exp / ideal)

    def test_paired_bootstrap_detects_gain(self):
        a, b = [0.9] * 20, [0.1] * 20
        d, lo, hi, p = m.paired_bootstrap_diff(a, b)
        self.assertAlmostEqual(d, 0.8); self.assertGreater(lo, 0); self.assertLess(p, 0.05)


class PipelineTests(unittest.TestCase):
    def test_clean_undoes_hyphenation_and_headers(self):
        t = "the judg-\nment\nREPUBLIC OF KENYA - Page 3\nends"
        c = clean_text(t)
        self.assertIn("judgment", c); self.assertNotIn("REPUBLIC", c)

    def test_noise_is_deterministic_and_changes_text(self):
        t = " ".join(["judgment of the court"] * 100)
        self.assertEqual(inject_ocr_noise(t, 0.3, 1), inject_ocr_noise(t, 0.3, 1))
        self.assertNotEqual(inject_ocr_noise(t, 0.3, 1), t)

    def test_chunking_respects_target(self):
        t = "\n\n".join(["word " * 50] * 20)
        self.assertTrue(all(len(c) <= 1200 for c in chunk_text(t)))

    def test_bm25_ranks_matching_chunk_first(self):
        b = BM25(["land title fraud", "bail bond criminal", "employment dismissal"])
        self.assertEqual(int(np.argmax(b.scores("fraud title"))), 0)

    def test_doc_ranking_uses_best_chunk(self):
        self.assertEqual(to_doc_ranking(np.array([0.1, 0.9, 0.5]), ["d1", "d2", "d1"], 2), ["d2", "d1"])

    def test_rrf_and_graph_expand(self):
        f = rrf([["a", "b"], ["a", "c"]])
        self.assertEqual(max(f, key=f.get), "a")
        g = graph_expand({"a": 1.0}, {"a": ["z"]})
        self.assertIn("z", g)


if __name__ == "__main__":
    unittest.main()
