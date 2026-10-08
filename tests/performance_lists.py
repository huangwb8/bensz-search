"""Measure list HTTP payload bounds and SQLite query plans at fixed data sizes."""

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bensz_search.admin import router
from bensz_search.admin_store import AdminStore


def run(args):
    store = AdminStore(args.output.parent / "lists.sqlite", "synthetic-encryption-for-list-benchmark")
    store.bootstrap("admin", "synthetic-list-password")
    token, _ = store.login("admin", "synthetic-list-password")
    app = FastAPI()
    app.include_router(router)
    app.state.admin_runtime = SimpleNamespace(store=store)
    report = []
    with TestClient(app) as client:
        client.cookies.set("bensz_session", token, path="/admin")
        for count in [100, 1000, 5000]:
            with store.transaction():
                store.db.execute("DELETE FROM access_keys")
                store.db.execute("DELETE FROM users WHERE id!=1")
                store.db.executemany(
                    "INSERT INTO users(username,password,role,created_at) VALUES (?,?,?,?)",
                    [(f"user-{i:05}", "synthetic", "member", i) for i in range(count - 1)],
                )
                store.db.executemany(
                    "INSERT INTO access_keys(id,user_id,name,token,prefix,created_at) VALUES (?,1,?,?,?,?)",
                    [(f"id-{i}", f"key-{i:05}", f"synthetic-{i}", "public", i) for i in range(count)],
                )
            for endpoint in ["keys", "users"]:
                durations, sizes = [], []
                for _ in range(50):
                    started = time.monotonic()
                    response = client.get(f"/admin/api/{endpoint}?limit=50&scope=all&sort=name")
                    durations.append((time.monotonic() - started) * 1000)
                    response.raise_for_status()
                    assert len(response.json()[endpoint]) == 50
                    assert response.json()["total"] == count
                    sizes.append(len(response.content))
                durations.sort()
                report.append(
                    {
                        "endpoint": endpoint,
                        "rows": count,
                        "samples": 50,
                        "p95_ms": round(durations[46], 2),
                        "max_ms": round(max(durations), 2),
                        "max_response_bytes": max(sizes),
                    }
                )
        with store.read() as db:
            plans = {
                name: [row["detail"] for row in db.execute(sql)]
                for name, sql in {
                    "keys_name": "EXPLAIN QUERY PLAN SELECT id,name FROM access_keys ORDER BY name COLLATE NOCASE,id LIMIT 50",
                    "users_name": "EXPLAIN QUERY PLAN SELECT id,username FROM users ORDER BY username COLLATE NOCASE,id LIMIT 50",
                }.items()
            }
    store.close()
    args.output.write_text(json.dumps({"measurements": report, "query_plans": plans}, indent=2))
    print(json.dumps({"measurements": report, "query_plans": plans}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
