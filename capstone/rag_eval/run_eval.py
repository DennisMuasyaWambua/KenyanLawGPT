"""Run the retrieval evaluation and write results.

    python -m rag_eval.run_eval --corpus data/sample_corpus.jsonl \
        --qrels data/sample_qrels.jsonl --out results/ --noise 0.08

Ablations: every system is evaluated on (a) the corpus as given, and, if --noise>0,
(b) OCR-corrupted text *without* cleaning and (c) OCR-corrupted text *with* cleaning,
plus a chunk-size sweep. Outputs results.json, results.md and per_query.csv."""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from .corpus import build_chunks, load_corpus, load_qrels
from .metrics import bootstrap_ci, paired_bootstrap_diff, per_query_metrics
from .retrievers import build_systems


def evaluate(docs, queries, k, chunk_size, clean, noise, dense, seed):
    chunks, owners = build_chunks(docs, target=chunk_size, overlap=chunk_size // 8,
                                  clean=clean, noise=noise, seed=seed)
    cites = {d.doc_id: d.cites for d in docs}
    systems = build_systems(chunks, owners, cites, dense)
    results = {}
    for s in systems:
        t0 = time.perf_counter()
        per_q = {q.query_id: per_query_metrics(s.rank(q.text, k), q.relevant, k) for q in queries}
        results[s.name] = {"per_query": per_q, "ms_per_query": (time.perf_counter() - t0) / max(len(queries), 1) * 1000}
    return results, len(chunks)


def summarise(results, k, baseline="bm25"):
    keys = [f"recall@{k}", "recall@5", f"precision@{k}", f"hit@{k}", f"mrr@{k}", f"ndcg@{k}"]
    qids = list(next(iter(results.values()))["per_query"])
    rows = {}
    for name, r in results.items():
        row = {"ms/query": round(r["ms_per_query"], 2)}
        for m in keys:
            mean, lo, hi = bootstrap_ci([r["per_query"][q][m] for q in qids])
            row[m] = {"mean": mean, "lo": lo, "hi": hi}
        if baseline in results and name != baseline:
            d, lo, hi, p = paired_bootstrap_diff(
                [r["per_query"][q][f"ndcg@{k}"] for q in qids],
                [results[baseline]["per_query"][q][f"ndcg@{k}"] for q in qids])
            row[f"ndcg@{k} vs {baseline}"] = {"diff": d, "lo": lo, "hi": hi, "p": p}
        rows[name] = row
    return rows, keys


def md_table(title, rows, keys, k, n_q, n_chunks):
    out = [f"### {title}", f"_{n_q} queries, {n_chunks} chunks; mean [95% bootstrap CI]_", "",
           "| system | " + " | ".join(keys) + f" | Δ nDCG@{k} vs bm25 (p) | ms/q |",
           "|---|" + "---|" * (len(keys) + 2)]
    for name, row in rows.items():
        cells = [f"{row[m]['mean']:.3f} [{row[m]['lo']:.2f}, {row[m]['hi']:.2f}]" for m in keys]
        d = row.get(f"ndcg@{k} vs bm25")
        cells.append(f"{d['diff']:+.3f} (p={d['p']:.2f})" if d else "—")
        cells.append(str(row["ms/query"]))
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--qrels", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--chunk-size", type=int, default=1200)
    ap.add_argument("--chunk-sweep", default="400,800,1200", help="comma list; '' to skip")
    ap.add_argument("--noise", type=float, default=0.0, help="OCR corruption rate for the ablation")
    ap.add_argument("--dense", default="hashing", help="'hashing' or 'st:<sentence-transformers model>'")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)

    docs, queries = load_corpus(a.corpus), load_qrels(a.qrels)
    known = {d.doc_id for d in docs}
    missing = {d for q in queries for d in q.relevant} - known
    if missing:
        raise SystemExit(f"qrels reference doc_ids not in corpus: {sorted(missing)[:5]}")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    scenarios = [("Main (corpus as given, cleaned)", dict(chunk_size=a.chunk_size, clean=True, noise=0.0))]
    if a.noise > 0:
        scenarios += [(f"OCR noise {a.noise:.0%}, NO cleaning", dict(chunk_size=a.chunk_size, clean=False, noise=a.noise)),
                      (f"OCR noise {a.noise:.0%}, with cleaning", dict(chunk_size=a.chunk_size, clean=True, noise=a.noise))]
    for cs in [int(x) for x in a.chunk_sweep.split(",") if x]:
        if cs != a.chunk_size:
            scenarios.append((f"Chunk size {cs}", dict(chunk_size=cs, clean=True, noise=0.0)))

    report, md, csv_rows = {}, [f"# Retrieval evaluation (k={a.k}, dense={a.dense})\n"], []
    for title, kw in scenarios:
        res, n_chunks = evaluate(docs, queries, k=a.k, dense=a.dense, seed=a.seed, **kw)
        rows, keys = summarise(res, a.k)
        report[title] = rows
        md.append(md_table(title, rows, keys, a.k, len(queries), n_chunks))
        for sysname, r in res.items():
            for qid, m in r["per_query"].items():
                csv_rows.append({"scenario": title, "system": sysname, "query_id": qid, **m})
    (out / "results.json").write_text(json.dumps(report, indent=2))
    (out / "results.md").write_text("\n".join(md))
    with open(out / "per_query.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(csv_rows[0])); w.writeheader(); w.writerows(csv_rows)
    print("\n".join(md)); print(f"\nwrote {out}/results.json, results.md, per_query.csv")


if __name__ == "__main__":
    main()
