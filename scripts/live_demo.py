#!/usr/bin/env python3
"""Verify actual retrieval separately from synthetic fixture checks."""

import argparse
import json
import os

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8899")
    args = parser.parse_args()
    key = os.getenv("LITELLM_MASTER_KEY", "sk-bensz-search-local-demo")
    report = []
    with httpx.Client(trust_env=False, timeout=30) as client:
        for query, payload in [
            (
                "python",
                {"search_tool_name": "auto", "debug": True, "constraints": {"latency_budget_ms": 15000}},
            ),
            ("colorectal cancer ctDNA", {"search_tool_name": "searxng", "engines": "pubmed", "timeout": 15}),
        ]:
            response = client.post(
                args.base_url + "/search",
                headers={"Authorization": "Bearer " + key},
                json={"query": query, "max_results": 5, **payload},
            )
            response.raise_for_status()
            result = response.json()
            assert result["results"], "Live provider returned no results"
            assert all("DEMO FIXTURE" not in r["snippet"] for r in result["results"])
            report.append(
                {
                    "query": query,
                    "result_count": len(result["results"]),
                    "sample": [{"title": r["title"], "url": r["url"]} for r in result["results"][:3]],
                    "providers": result.get("debug", {}).get("providers", ["searxng"]),
                }
            )
    print(json.dumps({"synthetic": False, "cases": report}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
