"""Deterministic labelled fixture benchmark, explicitly separate from real quality."""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from bensz_search.protocol import ProtocolLimits, search
from bensz_search.protocol_models import ProtocolSearch
from bensz_search.registry import Registry
from bensz_search.router import SmartRouter

SAMPLES = [
    ("academic", "colorectal cancer ctDNA"),
    ("academic", "结直肠癌 ctDNA"),
    ("coding", "Python async HTTP client"),
    ("coding", "Python 非同期 HTTP クライアント"),
    ("news", "AI research news"),
    ("news", "أخبار أبحاث الذكاء الاصطناعي"),
]


async def benchmark():
    async def call(**kwargs):
        await asyncio.sleep(0.02)
        provider = kwargs["search_tool_name"]
        return SearchResponse(
            results=[
                SearchResult(
                    title="Labelled relevant shared document",
                    url="https://evidence.example/shared?utm_source=" + provider,
                    snippet="Fixture external content. " * 200,
                ),
                SearchResult(
                    title="Labelled relevant unique document",
                    url=f"https://evidence.example/{provider}",
                    snippet="Fixture citation.",
                ),
                SearchResult(
                    title="Labelled distractor",
                    url=f"https://noise.example/{provider}",
                    snippet="Fixture distractor.",
                ),
            ]
        )

    data = {
        "synthetic": True,
        "scope": "labelled fixtures; no real provider quality or billing claim",
        "samples": len(SAMPLES),
        "repeats": 10,
        "modes": {},
    }
    for concurrency in (1, 3):
        latency, precision, bytes_used, votes, costs = [], [], [], [], []
        router = SmartRouter(Registry.load("config/capabilities.yaml"), call)
        limits = ProtocolLimits()
        limits.concurrency = concurrency
        for _ in range(10):
            for _task, query in SAMPLES:
                request = ProtocolSearch(
                    mode="planned",
                    calls=[
                        {"call_id": "one", "tool_id": "brave", "query": query},
                        {"call_id": "two", "tool_id": "serper", "query": query + " evidence"},
                    ],
                    constraints={"latency_budget_ms": 1000, "cost_budget_usd": 0.007},
                    max_results=10,
                )
                started = time.perf_counter()
                result = await search(router, request, {"brave", "serper"}, limits)
                latency.append((time.perf_counter() - started) * 1000)
                assert result.status == "success" and len(result.results) == 5
                assert max(len(r.snippet) for r in result.results) <= 2000
                relevant = sum(r.url.startswith("https://evidence.example/") for r in result.results)
                precision.append(relevant / len(result.results))
                votes.append(len({s.source_family for r in result.results for s in r.sources}))
                costs.append(result.estimated_cost_usd)
                bytes_used.append(len(result.model_dump_json().encode()))
        data["modes"][str(concurrency)] = {
            "requests": len(latency),
            "p50_ms": round(statistics.median(latency), 2),
            "p95_ms": round(statistics.quantiles(latency, n=100, method="inclusive")[94], 2),
            "labelled_precision": statistics.mean(precision),
            "independent_configured_families": statistics.mean(votes),
            "mean_response_bytes": round(statistics.mean(bytes_used)),
            "estimated_usd_per_request": statistics.mean(costs),
            "fixture_errors": 0,
            "billing_estimate_error": "not measurable without provider billing",
        }
    assert data["modes"]["1"]["labelled_precision"] == data["modes"]["3"]["labelled_precision"]
    assert data["modes"]["1"]["estimated_usd_per_request"] == data["modes"]["3"]["estimated_usd_per_request"]
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(benchmark())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
