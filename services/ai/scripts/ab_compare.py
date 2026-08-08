#!/usr/bin/env python3
"""A/B compare two GMI Cloud models over identical retrieval + prompt.

Runs the same query through the real retrieval pipeline once, then sends the
*identical* system+prompt (built by the production prompt builder) to both the
DeepSeek-R1 distill and Qwen3-235B via GMI Cloud, printing latency, token
usage, and full output side by side. Retrieval, citation-graph querying, and
prompt construction are untouched — this only fans the generation call out to
two models so you can eyeball both answers against the same retrieved citations
before picking a production model.

Usage:
    python services/ai/scripts/ab_compare.py --tenant <tenant_id> --query "..."

Requires a GMI_CLOUD_API_KEY in the environment (services/ai/.env). The
synthetic-data-only gate still applies: outside prod set GMI_SYNTHETIC_DATA_OK=true
only when the loaded corpus is synthetic.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make ``app`` importable when run as a standalone script (mirrors conftest).
ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "gen")):
    if p not in sys.path:
        sys.path.insert(0, p)

from app import db as dbx  # noqa: E402
from app.config import load  # noqa: E402
from app.embeddings import make_embedder  # noqa: E402
from app.graph import Graph  # noqa: E402
from app.llm import GMICloudProvider, make_llm  # noqa: E402
from app.retrieval import RetrievalOrchestrator  # noqa: E402


def _fmt_usage(usage: dict) -> str:
    return (f"input={usage.get('prompt_tokens', '?')} "
            f"output={usage.get('completion_tokens', '?')} "
            f"total={usage.get('total_tokens', '?')}")


async def run(tenant: str, query: str, top_k: int) -> None:
    cfg = load()
    if not cfg.gmi_cloud_api_key:
        print("ERROR: GMI_CLOUD_API_KEY is not set — cannot call GMI Cloud.", file=sys.stderr)
        raise SystemExit(2)

    pool = await dbx.init_pool(cfg.database_url)
    graph = Graph(cfg)
    embedder = make_embedder(cfg)
    # The orchestrator's llm is used by retrieve() only for intent
    # classification; generation is done explicitly below with each GMI model.
    retriever = RetrievalOrchestrator(pool, graph, embedder, make_llm(cfg), cfg)

    try:
        chunks, intent = await retriever.retrieve(tenant, query, top_k=top_k)
        system, prompt = RetrievalOrchestrator.build_answer_prompt(query, chunks, intent)

        print("=" * 100)
        print(f"QUERY   : {query}")
        print(f"TENANT  : {tenant}")
        print(f"INTENT  : {intent}")
        print(f"RETRIEVED {len(chunks)} chunks (identical context sent to both models):")
        for i, c in enumerate(chunks, 1):
            print(f"  [{i}] ({c.source_type}) {c.citation or c.source_id}")
        print("=" * 100)

        variants = [
            ("DeepSeek-R1-Distill (CoT, free)", cfg.gmi_cloud_deepseek_model),
            ("Qwen3-235B-A22B-Instruct (paid)", cfg.gmi_cloud_qwen_model),
        ]
        for label, model in variants:
            provider = GMICloudProvider(cfg, model=model)
            try:
                answer = await provider.complete(system=system, prompt=prompt, max_tokens=2048)
            except Exception as exc:  # keep the other variant's result usable
                print(f"\n### {label}\nmodel : {model}\nERROR : {exc}\n")
                continue
            print(f"\n{'#' * 100}")
            print(f"### {label}")
            print(f"model      : {model}")
            print(f"latency_ms : {provider.last_latency_ms:.0f}")
            print(f"tokens     : {_fmt_usage(provider.last_usage)}")
            print(f"{'-' * 100}")
            print(answer)
        print(f"\n{'#' * 100}")
    finally:
        await pool.close()
        await graph.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="A/B compare GMI Cloud models over identical retrieval.")
    ap.add_argument("--tenant", required=True, help="tenant id to run retrieval against")
    ap.add_argument("--query", required=True, help="the legal research query")
    ap.add_argument("--top-k", type=int, default=12, help="retrieved chunks (default 12)")
    args = ap.parse_args()
    asyncio.run(run(args.tenant, args.query, args.top_k))


if __name__ == "__main__":
    main()
