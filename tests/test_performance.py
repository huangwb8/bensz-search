"""Concurrency regressions use actual ASGI requests and real SQLite contention."""

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult
from test_admin import console as console
from test_admin import login

from bensz_search.admin_store import AdminStore
from bensz_search.assets import Assets
from bensz_search.telemetry import Telemetry, usage_key, usage_user
from bensz_search.work import BlockingWork


def response():
    return SearchResponse(
        results=[SearchResult(title="Example", url="https://example.org", snippet="Example")]
    )


def test_sqlite_writer_and_store_lock_do_not_block_light_reads(console, monkeypatch, tmp_path):
    login(console)
    runtime = console.app.state.admin_runtime
    smart = console.app.state.smart_search

    async def provider(**kwargs):
        await asyncio.sleep(0.025)
        return response()

    monkeypatch.setattr(smart, "call", provider)
    key = runtime.store.create_key(1, "performance")
    completed = threading.Event()
    entered = threading.Event()

    def contention():
        db = sqlite3.connect(Path(runtime.store.db.execute("PRAGMA database_list").fetchone()[2]))
        with runtime.store.lock:
            db.execute("BEGIN IMMEDIATE")
            entered.set()
            time.sleep(0.35)
            db.rollback()
        db.close()
        completed.set()

    thread = threading.Thread(target=contention)
    thread.start()
    assert entered.wait(1)

    async def run():
        stop = asyncio.Event()
        heartbeats = []

        async def heartbeat():
            while not stop.is_set():
                started = time.monotonic()
                await asyncio.sleep(0.005)
                heartbeats.append((time.monotonic() - started) * 1000)

        monitor = asyncio.create_task(heartbeat())
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=console.app),
                base_url="http://testserver",
                cookies=dict(console.cookies),
            ) as client:
                jobs = [
                    asyncio.create_task(
                        client.post(
                            "/search",
                            headers={"Authorization": "Bearer " + key["key"]},
                            json={"query": "Example", "search_tool_name": "auto"},
                        )
                    )
                    for _ in range(8)
                ]
                await asyncio.sleep(0.03)
                intervals = []
                started = time.monotonic()
                for _ in range(20):
                    tick = time.monotonic()
                    results = await asyncio.gather(
                        *(
                            client.get(path)
                            for path in ["/ready", "/admin/api/workspace", "/admin/api/overview"]
                        )
                    )
                    assert all(r.status_code == 200 for r in results)
                    intervals.append((time.monotonic() - tick) * 1000)
                    await asyncio.sleep(0.005)
                assert not completed.is_set() or time.monotonic() - started < 0.3
                responses = await asyncio.gather(*jobs)
                assert all(r.status_code == 200 for r in responses)
                return intervals, heartbeats

        finally:
            stop.set()
            await monitor

    try:
        intervals, heartbeats = console.portal.call(run)
    finally:
        thread.join()
    assert max(intervals) < 200
    ordered = sorted(heartbeats)
    p99 = ordered[int((len(ordered) - 1) * 0.99)]
    assert p99 < 50 and max(ordered) < 200
    import json

    (tmp_path / "performance-lock.json").write_text(
        json.dumps(
            {
                "write_lock_ms": 350,
                "concurrent_searches": 8,
                "heartbeat_samples": len(ordered),
                "heartbeat_p99_ms": p99,
                "heartbeat_max_ms": max(ordered),
                "management_samples": len(intervals) * 3,
                "management_batch_max_ms": max(intervals),
            }
        )
    )
    assert runtime.store.usage(7)["summary"]["requests"] == 8
    assert runtime.store.usage(7, 1)["summary"]["requests"] == 8
    assert runtime.store.keys(1)[0]["usage_count"] == 8


@pytest.mark.asyncio
async def test_record_releases_memory_lock_and_waits_for_cancelled_commit(tmp_path):
    store = AdminStore(tmp_path / "usage.sqlite", "s" * 40)
    store.bootstrap("admin", "long-password")
    key = store.create_key(1, "performance")
    telemetry = Telemetry()
    entered = threading.Event()

    def sink(event):
        entered.set()
        time.sleep(0.15)
        store.record_usage(event, usage_key.get(), usage_user.get())

    telemetry.sink = sink
    usage_key.set(key["record"]["id"])
    usage_user.set(1)
    attempt = {"provider": "test", "status": "success", "latency_ms": 1, "result_count": 1}
    job = asyncio.create_task(telemetry.arecord_execution("once", "test", [attempt], 1, 0, 1))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    started = time.monotonic()
    assert telemetry.snapshot()["summary"]["requests"] == 1
    assert time.monotonic() - started < 0.05
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert store.usage(7)["summary"]["requests"] == 1
    assert store.usage(7, 1)["summary"]["requests"] == 1
    assert store.keys(1)[0]["usage_count"] == 1
    assert telemetry.counts["persistence_errors"] == 0
    await telemetry.work.close()
    store.close()


@pytest.mark.asyncio
async def test_blocking_work_bounds_started_jobs_and_preserves_context():
    work = BlockingWork(workers=2, capacity=2)
    release = threading.Event()
    started = []

    def blocking():
        started.append(usage_user.get())
        release.wait(1)

    usage_user.set(7)
    jobs = [asyncio.create_task(work.run(blocking)) for _ in range(10)]
    await asyncio.sleep(0.025)
    assert started == [7, 7]
    for job in jobs[2:]:
        job.cancel()
    release.set()
    await asyncio.gather(*jobs, return_exceptions=True)
    await work.close()


def test_password_check_revalidates_user_after_concurrent_update(tmp_path, monkeypatch):
    from bensz_search import admin_store

    store = AdminStore(tmp_path / "identity.sqlite", "s" * 40)
    store.bootstrap("admin", "long-password")
    member = store.create_user("member", "long-password", "member")
    original = admin_store.password_matches

    def matches(password, encoded):
        assert not store.lock._is_owned()
        store.update_user(member["id"], enabled=False)
        return original(password, encoded)

    monkeypatch.setattr(admin_store, "password_matches", matches)
    assert store.login("member", "long-password") is None
    assert not store.change_password(member["id"], "long-password", "new-password-long")
    store.close()


def test_pagination_filtering_and_user_isolation(console):
    headers = login(console)
    store = console.app.state.admin_runtime.store
    other = store.create_user("other", "long-password", "member")
    with store.transaction():
        for i in range(105):
            store.db.execute(
                "INSERT INTO access_keys(id,user_id,name,token,prefix,created_at) VALUES (?,?,?,?,?,?)",
                (f"id-{i}", 1 if i % 2 else other["id"], f"sample-{i:03}", f"hash-{i}", "public", i),
            )
    first = console.get("/admin/api/keys?limit=50&scope=all&sort=name").json()
    second = console.get("/admin/api/keys?limit=50&scope=all&sort=name&offset=50").json()
    assert first["total"] == second["total"] == 105
    assert len(first["keys"]) == len(second["keys"]) == 50
    assert {r["id"] for r in first["keys"]}.isdisjoint(r["id"] for r in second["keys"])
    mine = console.get("/admin/api/keys?limit=50&query=sample-0").json()
    assert all(r["user_id"] == 1 for r in mine["keys"])
    assert console.get("/admin/api/users?limit=0").status_code == 422
    assert console.get("/admin/api/keys?limit=201").status_code == 422
    assert console.get("/admin/api/keys?sort=password").status_code == 422
    assert console.get("/admin/api/workspace").json()["providers"]
    assert console.delete("/admin/api/keys/id-1", headers=headers).status_code == 200


def test_compact_history_preserves_detail_and_private_cache(console):
    login(console)
    telemetry = console.app.state.smart_search.telemetry
    for i in range(205):
        telemetry.record_execution(f"req-{i}", "test", [], 0, 0, 0, ["Detail retained"])
    data = console.get("/admin/api/overview?compact=true").json()
    assert len(data["metrics"]["recent"]) == 20
    assert "routing_reason" not in data["metrics"]["recent"][-1]
    assert len(telemetry.snapshot()["recent"]) == 200
    legacy = console.get("/admin/api/overview").json()["metrics"]["recent"]
    assert len(legacy) == 200 and legacy[-1]["routing_reason"] == ["Detail retained"]
    assert console.get("/admin/api/requests/req-204").json()["routing_reason"] == ["Detail retained"]
    assert console.get("/admin/api/requests/req-0").status_code == 404
    page = console.get("/admin")
    import re

    path = re.search(r'src="([^"]+app.js)"', page.text)[1]
    resource = console.get(path, headers={"Accept-Encoding": "identity"})
    assert "immutable" in resource.headers["cache-control"]
    assert "no-store" not in resource.headers["cache-control"]
    assert console.get(path, headers={"If-None-Match": resource.headers["etag"]}).status_code == 304
    assert "no-store" in page.headers["cache-control"]
    assert "no-store" in console.get("/admin/api/workspace").headers["cache-control"]
    assert console.get(path.replace("app.js", "cache.js")).status_code == 200
    gzip = console.get(path, headers={"Accept-Encoding": "gzip"})
    assert gzip.headers["content-encoding"] == "gzip"
    assert int(gzip.headers["content-length"]) < len(resource.content)


def test_graph_fingerprint_changes_when_relative_dependency_changes(tmp_path):
    (tmp_path / "index.html").write_text('<script src="/admin/static/app.js"></script>')
    (tmp_path / "app.js").write_text('import "./dependency.js"')
    (tmp_path / "dependency.js").write_text("export const value = 1;")
    before = Assets(tmp_path)
    (tmp_path / "dependency.js").write_text("export const value = 2;")
    after = Assets(tmp_path)
    assert before.fingerprint != after.fingerprint
    assert before.files["dependency.js"] != after.files["dependency.js"]
    assert before.fingerprint.encode() in before.html


def test_overload_rejects_search_but_keeps_admin_and_health_live(console):
    login(console)
    capacity = console.app.state.search_capacity
    entered = 0
    try:
        while capacity.enter():
            entered += 1
        response = console.post("/search", json={"query": "Example"})
        assert response.status_code == 429
        assert response.headers["retry-after"] == "1"
        assert console.get("/ready").status_code == 200
        assert console.get("/admin/api/workspace").status_code == 200
    finally:
        for _ in range(entered):
            capacity.leave()
    assert capacity.active == 0


@pytest.mark.asyncio
async def test_old_html_module_graph_survives_atomic_asset_publication(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text('<script src="/admin/static/app.js"></script>')
    (source / "app.js").write_text('import "./removed.js"')
    (source / "removed.js").write_text("export const value = 1;")
    old = Assets(source)
    old.publish(tmp_path / "volume")
    (source / "app.js").write_text("export const value = 2;")
    (source / "removed.js").unlink()
    new = Assets(source)
    new.publish(tmp_path / "volume")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=new), base_url="http://test") as client:
        result = await client.get(f"/admin/assets/{old.fingerprint}/app.js")
        assert result.status_code == 200 and result.text == old.files["app.js"].decode()
        dependency = await client.get(f"/admin/assets/{old.fingerprint}/removed.js")
        assert dependency.status_code == 200


@pytest.mark.asyncio
async def test_shutdown_drains_pending_usage_and_surfaces_persistence_failure(tmp_path):
    telemetry = Telemetry()
    entered = threading.Event()

    def failure(event):
        entered.set()
        time.sleep(0.025)
        raise sqlite3.OperationalError("database unavailable")

    telemetry.sink = failure
    record = asyncio.create_task(telemetry.arecord_execution("failed-write", "test", [], 0, 0, 0))
    while not entered.is_set():
        await asyncio.sleep(0.001)
    await telemetry.work.close()
    await record
    assert telemetry.counts["persistence_errors"] == 1
    assert not telemetry.work.pending


def test_search_capacity_does_not_repurpose_protocol_fanout_env(monkeypatch):
    from bensz_search.performance import SearchCapacity
    from bensz_search.protocol import ProtocolLimits

    monkeypatch.setenv("BENSZ_SEARCH_CONCURRENCY", "2")
    monkeypatch.setenv("BENSZ_SEARCH_MAX_CONCURRENT_SEARCHES", "16")
    assert ProtocolLimits().concurrency == 2
    assert SearchCapacity().limit == 16


def test_overload_retains_protocol_error_contract(console):
    capacity = console.app.state.search_capacity
    entered = 0
    try:
        while capacity.enter():
            entered += 1
        result = console.post("/bensz-search/v1/search", json={})
        assert result.status_code == 429
        assert result.json()["protocol_version"] == "1.0"
        assert result.json()["error"]["code"] == "rate_limit"
        assert result.json()["error"]["retryable"] is True
        assert result.headers["retry-after"] == "1"
    finally:
        for _ in range(entered):
            capacity.leave()


@pytest.mark.parametrize("planned", [False, True])
@pytest.mark.asyncio
async def test_cancelled_router_and_protocol_execution_record_once(tmp_path, planned):
    from bensz_search.models import SearchRequest
    from bensz_search.protocol import ProtocolLimits, search
    from bensz_search.protocol_models import ProtocolSearch
    from bensz_search.registry import Registry
    from bensz_search.router import SmartRouter

    store = AdminStore(tmp_path / "cancel.sqlite", "synthetic-cancellation-encryption")
    store.bootstrap("admin", "synthetic-password-long")
    key = store.create_key(1, "cancel-test")
    entered = asyncio.Event()

    async def provider(**kwargs):
        entered.set()
        await asyncio.sleep(10)

    registry = Registry.load("config/capabilities.yaml")
    telemetry = Telemetry()
    telemetry.sink = lambda event: store.record_usage(event, usage_key.get(), usage_user.get())
    router = SmartRouter(registry, provider, telemetry=telemetry)
    usage_key.set(key["record"]["id"])
    usage_user.set(1)
    if planned:
        data = ProtocolSearch(
            mode="planned",
            calls=[{"call_id": "one", "tool_id": "searxng", "query": "Example"}],
        )
        job = asyncio.create_task(search(router, data, {"searxng"}, ProtocolLimits()))
    else:
        job = asyncio.create_task(router.search(SearchRequest(query="Example"), {"searxng"}))
    await entered.wait()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert store.usage(7)["summary"]["requests"] == 1
    assert store.usage(7, 1)["summary"]["requests"] == 1
    assert store.keys(1)[0]["usage_count"] == 1
    assert telemetry.snapshot()["recent"][-1]["intent"] == "cancelled"
    assert telemetry.counts["persistence_errors"] == 0
    await telemetry.work.close()
    store.close()
