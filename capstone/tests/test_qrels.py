import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag_eval.build_qrels import pool_candidates
from rag_eval.retrievers import System


class PoolTests(unittest.TestCase):
    def test_pool_dedupes_unions_and_is_deterministic(self):
        s1 = System("a", lambda q, k: ["d1", "d2", "d3"][:k])
        s2 = System("b", lambda q, k: ["d2", "d4"][:k])
        p = pool_candidates([s1, s2], "q", 3, 0)
        self.assertEqual(sorted(p), ["d1", "d2", "d3", "d4"])
        self.assertEqual(p, pool_candidates([s1, s2], "q", 3, 0))


if __name__ == "__main__":
    unittest.main()
