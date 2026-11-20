# Capstone: retrieval evaluation harness (DSA 8401)

Standalone (numpy only) harness that compares retrieval strategies for Kenyan
precedent search. It does not need Postgres/Neo4j, so a reviewer can run it.

```bash
python -m unittest discover -s tests          # metric/pipeline unit tests
python -m rag_eval.run_eval --corpus data/sample_corpus.jsonl \
    --qrels data/sample_qrels.jsonl --out results --noise 0.1
# learned embeddings (optional): pip install sentence-transformers, then
#   --dense st:BAAI/bge-small-en-v1.5
```

Systems: `bm25`, `dense_*`, `hybrid_rrf` (BM25 + dense, reciprocal-rank fusion),
`hybrid_rrf+graph` (adds citation-graph expansion). Metrics: recall@k, precision@k,
hit@k, MRR, nDCG@k with bootstrap CIs and paired-bootstrap significance vs BM25.
Ablations: OCR noise with/without cleaning, and chunk size.

## Exporting the real corpus from Postgres
```bash
pip install asyncpg neo4j
export DATABASE_URL=postgresql://wakili_app:<pw>@localhost:55432/wakili
python -m rag_eval.export_pg --out data/corpus.jsonl --doc-types case_law,judgment \
    --neo4j-uri bolt://localhost:7687 --neo4j-password <pw> --mine-text-citations
```
Reads the shared `public` schema only (never tenant data). Writes the corpus plus
`corpus.manifest.json` (counts, filters, edge sources) for the report's data section.

**Data formats** (JSONL): corpus `{doc_id,title,text,court,year,cites[]}`;
qrels `{query_id,query,relevant:{doc_id:grade}}`.

`data/sample_*` is a 12-document SYNTHETIC fixture for smoke-testing only; its
numbers are saturated and must not be reported as results.
