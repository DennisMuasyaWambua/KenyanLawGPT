"""Interactive relevance labelling with pooled candidates.

    python -m rag_eval.build_qrels --corpus data/corpus.jsonl --queries data/queries.txt \
        --out data/qrels.jsonl [--pool-depth 10] [--dense st:BAAI/bge-small-en-v1.5]

For each query (one per line in queries.txt) the top ``pool-depth`` documents of
EVERY system are merged into one de-duplicated pool, shuffled, and shown WITHOUT
telling you which system returned them (avoids bias towards any retriever, the
standard TREC pooling method). You grade each: 0 not relevant, 1 marginal,
2 relevant, 3 highly relevant, s = skip doc, q = save & quit. Re-running resumes:
queries already in --out are skipped. Document ids you never see are treated as
unjudged = not relevant, so report pool depth in the write-up."""
from __future__ import annotations

import argparse
import json
import random
import textwrap
from pathlib import Path

from .corpus import build_chunks, load_corpus
from .retrievers import build_systems


def pool_candidates(systems, query: str, depth: int, seed: int) -> list[str]:
    pooled: dict[str, None] = {}
    for s in systems:
        for d in s.rank(query, depth):
            pooled[d] = None
    docs = list(pooled)
    random.Random(f"{seed}:{query}").shuffle(docs)  # hide system order
    return docs


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(l)["query_id"] for l in path.read_text().splitlines() if l.strip()}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--queries", required=True, help="text file, one query per line")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pool-depth", type=int, default=10)
    ap.add_argument("--dense", default="hashing")
    ap.add_argument("--chunk-size", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--snippet", type=int, default=700, help="characters of text to show")
    a = ap.parse_args(argv)

    docs = load_corpus(a.corpus)
    by_id = {d.doc_id: d for d in docs}
    chunks, owners = build_chunks(docs, target=a.chunk_size, overlap=a.chunk_size // 8)
    systems = build_systems(chunks, owners, {d.doc_id: d.cites for d in docs}, a.dense)
    queries = [q.strip() for q in Path(a.queries).read_text().splitlines() if q.strip() and not q.startswith("#")]
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    finished = done_ids(out)

    for n, query in enumerate(queries, 1):
        qid = f"q{n}"
        if qid in finished:
            continue
        cands = pool_candidates(systems, query, a.pool_depth, a.seed)
        print(f"\n{'=' * 90}\n[{qid}] {query}\n{len(cands)} candidates to judge\n{'=' * 90}")
        grades: dict[str, int] = {}
        for i, did in enumerate(cands, 1):
            d = by_id[did]
            print(f"\n({i}/{len(cands)}) {d.title}  [{d.court} {d.year}]  id={did}")
            print(textwrap.indent(textwrap.fill(d.text[:a.snippet].replace("\n", " "), 88), "   "))
            while True:
                ans = input("grade 0-3 / s skip / q quit> ").strip().lower()
                if ans in {"0", "1", "2", "3"}:
                    grades[did] = int(ans); break
                if ans == "s":
                    break
                if ans == "q":
                    print("quit; this query was not saved."); return
        rel = {d: g for d, g in grades.items() if g > 0}
        if not rel:
            print("no relevant docs: query dropped (cannot score recall)."); continue
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"query_id": qid, "query": query, "relevant": rel,
                                 "judged": len(grades), "pool_depth": a.pool_depth}) + "\n")
        print(f"saved {qid}: {len(rel)} relevant of {len(grades)} judged")


if __name__ == "__main__":
    main()
