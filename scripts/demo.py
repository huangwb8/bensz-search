#!/usr/bin/env python3
"""End-to-end checks against the deployed synthetic demo, without commercial keys."""

import argparse
import json
import os

import httpx


def call(base, key, payload=None, path="/search", authorized=True):
    headers = {"Content-Type": "application/json"}
    if authorized:
        headers["Authorization"] = "Bearer " + key
    with httpx.Client(trust_env=False, timeout=25) as client:
        result = client.request(
            "POST" if payload is not None else "GET", base + path, json=payload, headers=headers
        )
    try:
        data = result.json()
    except ValueError:
        data = {"error": result.text[:200]}
    return result.status_code, data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8898")
    args = parser.parse_args()
    key = os.getenv("LITELLM_MASTER_KEY", "sk-bensz-search-local-demo")
    tests = [
        ("query-only", {"query": "capital of France"}, "/search", 1),
        ("explicit native adapter", {"query": "fixture", "search_tool_name": "exa"}, "/v1/search", None),
        ("path precedence", {"query": "fixture", "search_tool_name": "invalid"}, "/search/exa", None),
        (
            "academic parallel + dedup",
            {"query": "ctDNA clinical trial", "search_tool_name": "auto", "debug": True},
            "/search",
            2,
        ),
        ("news freshness", {"query": "OpenAI launched today", "debug": True}, "/search", 2),
        (
            "low-cost single",
            {"query": "ctDNA literature", "constraints": {"cost": "low"}, "debug": True},
            "/search",
            1,
        ),
        (
            "profile prompt",
            {
                "query": "ctDNA",
                "profile_prompt": "Biomedical research agent, primary literature and high recall",
                "debug": True,
            },
            "/search",
            2,
        ),
        (
            "timeout partial",
            {"query": "ctDNA demo-timeout", "constraints": {"latency_budget_ms": 300}, "debug": True},
            "/search/auto",
            2,
        ),
        (
            "empty fallback",
            {"query": "ctDNA demo-empty", "constraints": {"cost": "high"}, "debug": True},
            "/search",
            2,
        ),
        (
            "auth fallback",
            {"query": "ctDNA demo-auth", "constraints": {"cost": "high"}, "debug": True},
            "/search",
            2,
        ),
    ]
    report = []
    request_id = None
    for name, payload, path, provider_count in tests:
        status, result = call(args.base_url, key, payload, path)
        assert status == 200, (name, status, result)
        assert result["object"] == "search" and result["results"], (name, result)
        debug = result.get("debug")
        if payload.get("debug"):
            assert debug is not None
            assert len(debug["plan"]["providers"]) == provider_count
            request_id = debug["request_id"]
        else:
            assert "debug" not in result
        if name == "academic parallel + dedup":
            assert len(result["results"]) == 3
        if name == "auth fallback":
            assert any(a["status"] == "auth" for a in debug["attempts"])
            assert any(a["fallback"] for a in debug["attempts"])
        if name == "empty fallback":
            assert any(a["status"] == "empty" for a in debug["attempts"])
            assert any(a["fallback"] for a in debug["attempts"])
        if name == "timeout partial":
            assert debug["partial_success"]
            assert any(a["status"] == "timeout" for a in debug["attempts"])
        report.append(
            {
                "case": name,
                "status": status,
                "result_count": len(result["results"]),
                "providers": [p["name"] for p in debug["plan"]["providers"]] if debug else "native/default",
            }
        )
    status, _ = call(args.base_url, key, {"query": "fixture"}, authorized=False)
    assert status in {401, 403}
    report.append({"case": "missing authentication", "status": status})
    status, _ = call(args.base_url, key, {"query": "fixture", "api_base": "http://arbitrary"})
    assert status == 422
    report.append({"case": "credential/base override rejected", "status": status})
    status, metrics = call(args.base_url, key, path="/smart-search/metrics")
    assert status == 200 and metrics["counters"]["requests"] >= 1
    status, result = call(
        args.base_url, key, {"request_id": request_id, "event": "cited"}, "/smart-search/feedback"
    )
    assert status == 200 and result["accepted"]
    report.append({"case": "metrics and feedback", "status": status})
    print(json.dumps({"synthetic": True, "cases": report}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
