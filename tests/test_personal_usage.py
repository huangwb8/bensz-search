"""Personal aggregate isolation and persistence, with synthetic searches only."""

import secrets
from datetime import UTC, datetime, timedelta

import litellm
import pytest
from test_admin import console as console
from test_admin import login
from test_openai_search import web_response

from bensz_search.admin_store import AdminStore


def event(day=None):
    return {
        "timestamp": day or datetime.now(UTC).isoformat(),
        "result_count": 1,
        "latency_ms": 1400,
        "estimated_cost_usd": 0.003,
        "attempts": [
            {"provider": "a", "status": "timeout", "latency_ms": 1200, "estimated_cost_usd": 0.001},
            {
                "provider": "b",
                "status": "success",
                "latency_ms": 180,
                "estimated_cost_usd": 0.002,
                "fallback": True,
            },
            {"provider": "skipped", "status": "skipped", "latency_ms": 0},
        ],
    }


def test_personal_aggregates_survive_restart_and_user_deletion_clears_ownership(tmp_path):
    path = tmp_path / "personal.sqlite3"
    secret = secrets.token_urlsafe(48)
    store = AdminStore(path, secret)
    store.bootstrap("admin", "synthetic-password-strong")
    member = store.create_user("member", "synthetic-password-strong", "member")["id"]
    store.record_usage(event())  # Legacy/global-only events cannot be assigned to a user.
    store.record_usage(event(), user_id=1)
    store.record_usage(event(), user_id=member)
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    store.record_usage(event(old), user_id=member)
    store.close()
    store = AdminStore(path, secret)
    try:
        mine = store.usage(7, member)
        assert mine["summary"]["requests"] == 1
        assert mine["summary"]["fallbacks"] == 1
        assert mine["summary"]["estimated_cost_usd"] == pytest.approx(0.003)
        assert {p["name"]: p["requests"] for p in mine["by_provider"]} == {"a": 1, "b": 1}
        assert mine["by_provider"][0]["success_rate"] == 0
        assert mine["by_provider"][1]["success_rate"] == 1
        assert mine["by_provider"][1]["p95_ms"] == 200
        assert len(mine["trend"]) == 7
        assert sum(row["requests"] for row in mine["trend"]) == 1
        assert store.usage(30, member)["summary"]["requests"] == 2
        assert store.usage(7, 1)["summary"]["requests"] == 1
        assert store.usage(7)["summary"]["requests"] == 3
        store.delete_user(member)
        assert store.usage(30, member)["summary"]["requests"] == 0
        store.record_usage(event(), user_id=member)
        assert store.usage(7)["summary"]["requests"] == 4
        assert store.usage(30, member)["summary"]["requests"] == 0
    finally:
        store.close()


def test_personal_endpoint_uses_session_owner_and_preserves_deleted_key_history(console, monkeypatch):
    assert console.get("/admin/api/usage/me").status_code == 401
    admin_headers = login(console)
    created = console.post(
        "/admin/api/users",
        headers=admin_headers,
        json={"username": "member", "password": "synthetic-password-strong", "role": "member"},
    )
    assert created.status_code == 200
    member_id = created.json()["id"]
    provider = {"name": "personal-openai", "provider": "openai", "api_key": "synthetic-secret"}
    assert console.post("/admin/api/providers", headers=admin_headers, json=provider).status_code == 200
    assert console.delete("/admin/api/providers/searxng", headers=admin_headers).status_code == 200

    async def responses(**kwargs):
        return web_response()

    monkeypatch.setattr(litellm, "aresponses", responses)
    store = console.app.state.admin_runtime.store
    store.record_usage(event(), user_id=1)
    member_headers = login(console, "member", "synthetic-password-strong")
    key = console.post("/admin/api/keys", headers=member_headers, json={"name": "synthetic"}).json()
    auth = {"Authorization": "Bearer " + key["key"]}
    for path, headers, payload in [
        ("/search", auth, {"query": "Python docs"}),
        ("/admin/api/search", member_headers, {"query": "Python docs"}),
        (
            "/admin/api/search",
            member_headers,
            {"query": "Python docs", "search_tool_name": "personal-openai"},
        ),
    ]:
        response = console.post(path, headers=headers, json=payload)
        assert response.status_code == 200, response.text
    for days in (7, 30):
        response = console.get(f"/admin/api/usage/me?days={days}&user_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["requests"] == 3
        assert [p["name"] for p in data["by_provider"]] == ["personal-openai"]
        assert data["by_provider"][0]["requests"] == 3
        assert data["recent"] == []
        assert "user_id" not in data
        assert key["key"] not in response.text
    assert console.get("/admin/api/usage/me?days=8").status_code == 422
    assert console.get("/admin/api/usage?days=7").status_code == 403
    assert console.get("/admin/api/keys").json()["keys"][0]["usage_count"] == 1
    assert (
        console.delete(
            f"/admin/api/keys/{key['record']['id']}?permanent=true", headers=member_headers
        ).status_code
        == 200
    )
    assert store.usage(7, member_id)["summary"]["requests"] == 3
    login(console)
    assert console.get("/admin/api/usage/me").json()["summary"]["requests"] == 1
    assert console.get("/admin/api/usage").json()["summary"]["requests"] == 4
