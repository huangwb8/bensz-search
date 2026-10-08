"""Fixed-delay HTTP load, accounting reconciliation and bounded resource samples.

Use only with tests/performance_app.py in an isolated local container.
"""

import argparse
import asyncio
import json
import time
from collections import Counter, deque
from pathlib import Path

import httpx


def stats(rows):
    rows = sorted(rows)
    return {
        "samples": len(rows),
        "p50_ms": round(rows[int((len(rows) - 1) * 0.50)], 2) if rows else None,
        "p95_ms": round(rows[int((len(rows) - 1) * 0.95)], 2) if rows else None,
        "max_ms": round(max(rows, default=0), 2),
    }


async def run(args):
    timeout = httpx.Timeout(15)
    limits = httpx.Limits(max_connections=48, max_keepalive_connections=48)
    report = {"provider": "mock", "provider_delay_ms": 100, "workers": 1, "stages": [], "resources": []}
    async with httpx.AsyncClient(
        base_url=args.url, timeout=timeout, limits=limits, trust_env=False
    ) as client:
        session = await client.post(
            "/admin/api/login", json={"username": "admin", "password": "synthetic-performance-password"}
        )
        session.raise_for_status()
        csrf = {"X-CSRF-Token": session.json()["csrf_token"]}
        key = await client.post("/admin/api/keys", headers=csrf, json={"name": "synthetic-capacity"})
        key.raise_for_status()
        auth = {"Authorization": "Bearer " + key.json()["key"]}
        baseline = (await client.get("/admin/api/usage")).json()["summary"]["requests"]
        for concurrency in [1, 8, 16, 32]:
            durations, management, statuses = [], [], Counter()

            async def worker(statuses=statuses, durations=durations):
                for _ in range(args.requests):
                    started = time.monotonic()
                    result = await client.post(
                        "/search", headers=auth, json={"query": "Synthetic Example", "max_results": 3}
                    )
                    statuses[result.status_code] += 1
                    durations.append((time.monotonic() - started) * 1000)
                    await asyncio.sleep(0.005)

            jobs = [asyncio.create_task(worker()) for _ in range(concurrency)]
            while any(not task.done() for task in jobs):
                for path in ["/admin/api/overview?compact=true", "/admin/api/workspace", "/ready"]:
                    started = time.monotonic()
                    result = await client.get(path)
                    result.raise_for_status()
                    management.append((time.monotonic() - started) * 1000)
                await asyncio.sleep(0.005)
            await asyncio.gather(*jobs)
            report["stages"].append(
                {
                    "concurrency": concurrency,
                    "search": stats(durations),
                    "management": stats(management),
                    "statuses": dict(statuses),
                }
            )
            report["resources"].append((await client.get("/benchmark/state")).json())
        completed = sum(stage["statuses"].get(200, 0) for stage in report["stages"])
        if args.duration:
            deadline = time.monotonic() + args.duration
            statuses, management = Counter(), deque(maxlen=4096)

            async def continuous_worker():
                nonlocal completed
                while time.monotonic() < deadline:
                    result = await client.post(
                        "/search", headers=auth, json={"query": "Synthetic Example", "max_results": 3}
                    )
                    statuses[result.status_code] += 1
                    completed += result.status_code == 200
                    await asyncio.sleep(0.02)

            jobs = [asyncio.create_task(continuous_worker()) for _ in range(8)]
            while time.monotonic() < deadline:
                started = time.monotonic()
                result = await client.get("/admin/api/overview?compact=true")
                result.raise_for_status()
                management.append((time.monotonic() - started) * 1000)
                report["resources"].append((await client.get("/benchmark/state")).json())
                await asyncio.sleep(10)
            await asyncio.gather(*jobs)
            report["sustained"] = {
                "seconds": args.duration,
                "statuses": dict(statuses),
                "management": stats(management),
            }
        await asyncio.sleep(0.2)
        global_usage = (await client.get("/admin/api/usage")).json()["summary"]["requests"] - baseline
        personal = (await client.get("/admin/api/usage/me")).json()["summary"]["requests"] - baseline
        keys = (await client.get("/admin/api/keys")).json()["keys"]
        key_uses = next(row["usage_count"] for row in keys if row["id"] == key.json()["record"]["id"])
        report["accounting"] = {
            "completed": completed,
            "global": global_usage,
            "personal": personal,
            "key_uses": key_uses,
            "matches": completed == global_usage == personal == key_uses,
        }
        report["final"] = (await client.get("/benchmark/state")).json()
    args.output.write_text(json.dumps(report, indent=2))
    assert report["accounting"]["matches"], report["accounting"]
    print(
        json.dumps({"stages": report["stages"], "accounting": report["accounting"], "final": report["final"]})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
