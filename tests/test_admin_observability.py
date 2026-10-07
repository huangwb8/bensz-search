"""Engine evidence, health and aggregate regressions using local synthetic calls."""

import asyncio
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import litellm
import pytest
from litellm.llms.base_llm.search.transformation import SearchResponse
from test_admin import console as console
from test_admin import login

from bensz_search.admin_store import AdminStore, password_hash
from bensz_search.integration import RouterLease
from bensz_search.telemetry import Telemetry


def evidence_provider(console, headers):
    body = {
        "name": "verified",
        "provider": "searxng",
        "api_base": "https://instance.example",
        "engines": ["pubmed", "github"],
        "verified_engines": ["pubmed", "github"],
        "engine_evidence": "operator verified instance engines",
    }
    assert console.post("/admin/api/providers", headers=headers, json=body).status_code == 200
    return body


def test_provider_edit_and_toggle_preserve_omitted_evidence(console):
    headers = login(console)
    original = evidence_provider(console, headers)
    body = {k: v for k, v in original.items() if k not in {"verified_engines", "engine_evidence"}}
    for enabled in (False, True):
        body.update(enabled=enabled, timeout_ms=12000)
        assert console.put("/admin/api/providers/verified", headers=headers, json=body).status_code == 200
        saved = next(
            p for p in console.get("/admin/api/providers").json()["providers"] if p["name"] == "verified"
        )
        assert saved["verified_engines"] == original["verified_engines"]
        assert saved["engine_evidence"] == original["engine_evidence"]
        capability = console.app.state.smart_search.registry.providers["verified"]
        assert capability.verified_engines == original["verified_engines"]


def test_evidence_can_be_cleared_and_does_not_follow_another_instance(console):
    headers = login(console)
    body = evidence_provider(console, headers)
    body.update(verified_engines=[], engine_evidence=None)
    assert console.put("/admin/api/providers/verified", headers=headers, json=body).status_code == 200
    assert console.app.state.smart_search.registry.providers["verified"].verified_engines == []
    body.update(verified_engines=["pubmed"], engine_evidence="verified by operator")
    assert console.put("/admin/api/providers/verified", headers=headers, json=body).status_code == 200
    body = {k: v for k, v in body.items() if k not in {"verified_engines", "engine_evidence"}}
    body["api_base"] = "https://other.example"
    assert console.put("/admin/api/providers/verified", headers=headers, json=body).status_code == 200
    assert console.app.state.smart_search.registry.providers["verified"].verified_engines == []


def test_engine_subset_edit_preserves_only_still_configured_evidence(console):
    headers = login(console)
    body = evidence_provider(console, headers)
    body = {k: v for k, v in body.items() if k not in {"verified_engines", "engine_evidence"}}
    body["engines"] = ["pubmed"]
    assert console.put("/admin/api/providers/verified", headers=headers, json=body).status_code == 200
    assert console.app.state.smart_search.registry.providers["verified"].verified_engines == ["pubmed"]


def test_health_cooldown_unknown_disabled_and_empty_explicit_result(console):
    headers = login(console)
    smart = console.app.state.smart_search
    smart.health.failure("searxng", "quota")
    health = console.get("/admin/api/providers/health").json()["health"][0]
    assert health["state"] == "open" and health["last_error"] == "quota"
    assert 290 <= health["cooldown_remaining_s"] <= 300

    async def empty(**kwargs):
        return SearchResponse(results=[])

    smart.call = empty
    response = console.post(
        "/admin/api/search",
        headers=headers,
        json={"query": "mock", "search_tool_name": "searxng", "debug": True},
    )
    assert response.status_code == 200
    assert response.json()["debug"]["attempts"][0]["status"] == "empty"
    assert smart.health.state("searxng").observed_result == "empty"


def test_daily_aggregates_are_durable_and_count_requests_separately_from_attempts(tmp_path):
    path = tmp_path / "usage.sqlite3"
    secret = secrets.token_urlsafe(48)
    store = AdminStore(path, secret)
    telemetry = Telemetry()
    telemetry.sink = store.record_usage
    event = telemetry.record_execution(
        "id",
        "protocol",
        [
            {
                "provider": "a",
                "status": "timeout",
                "latency_ms": 1200,
                "estimated_cost_usd": 0.001,
                "fallback": False,
            },
            {
                "provider": "b",
                "status": "success",
                "latency_ms": 180,
                "estimated_cost_usd": 0.002,
                "fallback": True,
            },
        ],
        3,
        0.003,
        1400,
    )
    snapshot = store.usage(7)
    assert event["timestamp"].endswith("+00:00")
    assert snapshot["summary"]["requests"] == 1
    assert snapshot["summary"]["success_rate"] == 1
    assert snapshot["summary"]["estimated_cost_usd"] == 0.003
    assert snapshot["summary"]["fallbacks"] == 1
    assert snapshot["summary"]["p95_ms"] == 1500
    assert sum(p["requests"] for p in snapshot["by_provider"]) == 2
    assert len(snapshot["trend"]) == 7
    store.close()
    restored = AdminStore(path, secret)
    assert restored.usage(30)["summary"]["requests"] == 1
    assert Telemetry().snapshot()["summary"]["requests"] == 0
    restored.close()


def test_concurrent_sqlite_aggregate_updates_do_not_lose_calls(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    secret = secrets.token_urlsafe(48)
    stores = [AdminStore(path, secret) for _ in range(2)]
    event = {
        "timestamp": "2099-01-01T00:00:00+00:00",
        "result_count": 1,
        "latency_ms": 40,
        "estimated_cost_usd": 0.001,
        "attempts": [
            {
                "provider": "provider",
                "status": "success",
                "latency_ms": 40,
                "estimated_cost_usd": 0.001,
                "fallback": False,
            }
        ],
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda i: stores[i % 2].record_usage(event), range(30)))
    assert stores[0].usage(7)["summary"]["requests"] == 30
    for store in stores:
        store.close()


def callback_sizes():
    return {
        name: len(getattr(litellm, name))
        for name in (
            "callbacks",
            "input_callback",
            "success_callback",
            "failure_callback",
            "_async_success_callback",
            "_async_failure_callback",
            "service_callback",
        )
    }


def test_provider_refresh_does_not_accumulate_global_callbacks(console):
    runtime = console.app.state.admin_runtime
    baseline = callback_sizes()
    for _ in range(110):
        runtime.refresh()
        assert callback_sizes() == baseline


@pytest.mark.parametrize("failed", [False, True])
def test_temporary_provider_test_discards_callbacks_on_success_and_failure(console, monkeypatch, failed):
    import bensz_search.admin as admin

    headers = login(console)
    baseline = callback_sizes()

    async def call(**kwargs):
        if failed:
            raise TimeoutError()
        return SearchResponse(results=[])

    monkeypatch.setattr(admin, "provider_call", lambda router, original: call)
    for _ in range(5):
        response = console.post(
            "/admin/api/providers/searxng/test", headers=headers, json={"query": "synthetic"}
        )
        assert response.status_code == 200
        assert response.json()["category"] == ("timeout" if failed else "empty")
        assert callback_sizes() == baseline


def test_concurrent_refresh_publishes_the_latest_saved_configuration(console, monkeypatch):
    import bensz_search.admin as admin

    runtime = console.app.state.admin_runtime
    original_router = litellm.Router
    entered, release, second_started, second_read = (Event() for _ in range(4))
    original_providers = runtime.store.providers
    constructions = 0

    def replacement(*args, **kwargs):
        nonlocal constructions
        constructions += 1
        if constructions == 1:
            entered.set()
            assert release.wait(5)
        return original_router(*args, **kwargs)

    def providers(*args, **kwargs):
        if second_started.is_set():
            second_read.set()
        return original_providers(*args, **kwargs)

    def second_refresh():
        second_started.set()
        runtime.refresh()

    monkeypatch.setattr(admin.litellm, "Router", replacement)
    monkeypatch.setattr(runtime.store, "providers", providers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runtime.refresh)
        assert entered.wait(5)
        updated = original_providers()[0]
        updated.pop("has_api_key")
        updated["timeout_ms"] = 2345
        runtime.store.save_provider(updated)
        second = pool.submit(second_refresh)
        assert second_started.wait(5)
        try:
            # A later refresh cannot read/publish while an older refresh is still constructing.
            assert not second_read.wait(0.1)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert console.app.state.smart_search.registry.providers[updated["name"]].timeout_ms == 2345


@pytest.mark.parametrize("change", ["config", "secret", "delete"])
def test_engine_evidence_compare_and_swap_rejects_changes_from_another_store(tmp_path, change):
    secret = secrets.token_urlsafe(48)
    path = tmp_path / "compare-and-swap.sqlite3"
    first, second = AdminStore(path, secret), AdminStore(path, secret)
    original = {
        "name": "engine-instance",
        "provider": "searxng",
        "enabled": True,
        "api_base": "https://instance.example",
        "engines": ["pubmed"],
        "verified_engines": [],
        "engine_evidence": None,
    }
    try:
        first.save_provider(original, "synthetic-provider-secret")
        expected = first.providers(private=True)[0]
        if change == "config":
            second.save_provider({**original, "api_base": "https://edited.example"})
        elif change == "secret":
            second.save_provider(original, "synthetic-replacement-secret")
        else:
            second.delete_provider(original["name"])
        current = second.providers(private=True)
        synchronized = {**original, "verified_engines": ["pubmed"], "engine_evidence": "synthetic evidence"}
        with pytest.raises(ValueError, match="配置已变化"):
            first.save_provider(synchronized, expected=expected)
        assert first.providers(private=True) == current
    finally:
        first.close()
        second.close()


def test_native_named_batch_cost_counts_each_query(console, monkeypatch):
    from test_openai_search import web_response

    headers = login(console)
    assert (
        console.post(
            "/admin/api/providers",
            headers=headers,
            json={
                "name": "batch-openai",
                "provider": "openai",
                "api_key": "synthetic-openai-secret",
                "estimated_cost_usd": 0.01,
            },
        ).status_code
        == 200
    )

    async def responses(**kwargs):
        return web_response()

    monkeypatch.setattr(litellm, "aresponses", responses)
    created = console.post("/admin/api/keys", headers=headers, json={"name": "batch-test"}).json()
    response = console.post(
        "/search/batch-openai",
        headers={"Authorization": "Bearer " + created["key"]},
        json={"query": ["Python docs", "Python tutorials"]},
    )
    assert response.status_code == 200, response.text
    event = console.app.state.smart_search.telemetry.snapshot()["recent"][-1]
    assert event["estimated_cost_usd"] == pytest.approx(0.02)
    assert event["attempts"][0]["estimated_cost_usd"] == pytest.approx(0.02)
    assert console.get("/admin/api/keys").json()["keys"][0]["usage_count"] == 1


@pytest.mark.parametrize("existing_user", [False, True])
def test_concurrent_legacy_startup_migrates_and_bootstraps_once(tmp_path, existing_user):
    path = tmp_path / "legacy-startup.sqlite3"
    secret = secrets.token_urlsafe(48)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,"
            "password TEXT NOT NULL,role TEXT NOT NULL,created_at REAL NOT NULL)"
        )
        if existing_user:
            db.execute(
                "INSERT INTO users VALUES (1,?,?,?,?)",
                ("legacy-admin", password_hash("synthetic-legacy-password"), "admin", time.time()),
            )
    barrier = Barrier(4)

    def startup(_):
        barrier.wait(timeout=5)
        store = AdminStore(path, secret)
        try:
            store.bootstrap("bootstrap-admin", "synthetic-bootstrap-password")
            return store.users()
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(startup, range(4)))
    assert all(len(users) == 1 and users[0]["enabled"] for users in results)
    final = AdminStore(path, secret)
    try:
        username = "legacy-admin" if existing_user else "bootstrap-admin"
        password = "synthetic-legacy-password" if existing_user else "synthetic-bootstrap-password"
        assert final.login(username, password)
        assert final.db.execute("SELECT count(*) FROM meta WHERE name='encryption_check'").fetchone()[0] == 1
        assert len(final.users()) == 1
    finally:
        final.close()


@pytest.mark.parametrize("cancelled", [False, True])
def test_router_lease_keeps_inflight_callbacks_until_completion_or_cancellation(cancelled):
    discards = []

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()

        async def call(**kwargs):
            started.set()
            await finish.wait()
            return "completed"

        lease = RouterLease(SimpleNamespace(discard=lambda: discards.append(True)), call)
        task = asyncio.create_task(lease(query="synthetic"))
        await started.wait()
        lease.retire()
        assert not discards
        if cancelled:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            finish.set()
            assert await task == "completed"
        assert lease.active == 0
        assert discards == [True]

    asyncio.run(scenario())


def test_test_query_validation_marks_field_and_never_echoes_input(console):
    headers = login(console)
    query = "synthetic-private-value" * 60
    response = console.post("/admin/api/providers/searxng/test", headers=headers, json={"query": query})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "query"
    assert query not in response.text
