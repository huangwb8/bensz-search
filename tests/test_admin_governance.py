"""Authorization, lifecycle and legacy SQLite regression coverage for governance."""

import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult
from test_admin import console as console
from test_admin import login

from bensz_search.admin_store import AdminStore, digest, password_hash


def test_legacy_database_migration_is_repeatable_and_preserves_credentials(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    encryption_secret = secrets.token_urlsafe(48)
    session_token = secrets.token_urlsafe(32)
    key_token = "sk-bs-" + secrets.token_urlsafe(32)
    now = time.time()
    with sqlite3.connect(path) as database:
        database.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL, role TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf TEXT NOT NULL, expires_at REAL NOT NULL
            );
            CREATE TABLE access_keys (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL, token TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL,
                created_at REAL NOT NULL, last_used_at REAL, revoked INTEGER NOT NULL DEFAULT 0
            );
        """)
        database.execute(
            "INSERT INTO users VALUES (1,?,?,?,?)",
            ("legacy-admin", password_hash("legacy-password-strong"), "admin", now),
        )
        database.execute(
            "INSERT INTO sessions VALUES (?,1,?,?)",
            (digest(session_token), "legacy-csrf", now + 3600),
        )
        database.execute(
            "INSERT INTO access_keys VALUES (?,1,?,?,?, ?,NULL,0)",
            ("legacy-key-id", "legacy-key", digest(key_token), key_token[:14], now),
        )

    public_session_id = None
    for _ in range(3):
        store = AdminStore(path, encryption_secret)
        try:
            assert store.session(session_token)["user"]["role"] == "admin"
            authenticated = store.authenticate_key(key_token)
            assert authenticated["user_id"] == 1
            assert set(authenticated["scopes"]) == {"search", "protocol"}
            assert store.users()[0]["enabled"]
            current_session = next(r for r in store.sessions(1, session_token) if r["current"])
            assert current_session["id"] != digest(session_token)
            if public_session_id is None:
                public_session_id = current_session["id"]
            assert current_session["id"] == public_session_id
            assert store.login("legacy-admin", "legacy-password-strong")
            assert len(store.users()) == 1
            assert len(store.keys(1)) == 1
        finally:
            store.close()

    raw = path.read_bytes()
    for plaintext in (session_token, key_token, "legacy-password-strong"):
        assert plaintext.encode() not in raw


def create_member(client, headers, username="governance-member", role="member"):
    response = client.post(
        "/admin/api/users",
        headers=headers,
        json={"username": username, "password": "member-password-strong", "role": role},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.mark.parametrize("change", [{"role": "member"}, {"enabled": False}])
def test_last_enabled_administrator_cannot_be_removed(console, change):
    headers = login(console)
    second_id = create_member(console, headers, "second-admin", "admin")
    assert (
        console.put(f"/admin/api/users/{second_id}", headers=headers, json={"enabled": False}).status_code
        == 200
    )
    response = console.put("/admin/api/users/1", headers=headers, json=change)
    assert response.status_code == 409
    assert console.get("/admin/api/users").status_code == 200
    assert console.get("/admin/api/session").json()["user"]["role"] == "admin"


def test_last_administrator_check_is_atomic_across_store_connections(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    secret = secrets.token_urlsafe(48)
    first = AdminStore(path, secret)
    first.bootstrap("first", "admin-password-strong")
    second_id = first.create_user("second", "admin-password-strong", "admin")["id"]
    second = AdminStore(path, secret)
    barrier = Barrier(2)

    def demote(store, user_id):
        barrier.wait()
        try:
            store.update_user(user_id, role="member", actor_id=user_id)
            return "changed"
        except ValueError:
            return "protected"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(demote, first, 1)
            b = pool.submit(demote, second, second_id)
            assert sorted([a.result(timeout=10), b.result(timeout=10)]) == ["changed", "protected"]
        assert sum(u["role"] == "admin" and u["enabled"] for u in first.users()) == 1
    finally:
        first.close()
        second.close()


def test_disabled_user_and_password_reset_revoke_active_sessions(console):
    headers = login(console)
    user_id = create_member(console, headers)
    member = TestClient(console.app, raise_server_exceptions=False)
    try:
        member_headers = login(member, "governance-member", "member-password-strong")
        created = member.post("/admin/api/keys", headers=member_headers, json={"name": "member-key"})
        key_headers = {"Authorization": "Bearer " + created.json()["key"]}
        assert (
            console.put(f"/admin/api/users/{user_id}", headers=headers, json={"enabled": False}).status_code
            == 200
        )
        assert member.get("/admin/api/session").status_code == 401
        assert member.get("/bensz-search/v1/capabilities", headers=key_headers).status_code == 401
        assert (
            member.post(
                "/admin/api/login",
                json={"username": "governance-member", "password": "member-password-strong"},
            ).status_code
            == 401
        )
        assert (
            console.put(f"/admin/api/users/{user_id}", headers=headers, json={"enabled": True}).status_code
            == 200
        )
        login(member, "governance-member", "member-password-strong")
        assert (
            console.put(
                f"/admin/api/users/{user_id}", headers=headers, json={"password": "reset-password-strong"}
            ).status_code
            == 200
        )
        assert member.get("/admin/api/session").status_code == 401
        assert (
            member.post(
                "/admin/api/login",
                json={"username": "governance-member", "password": "member-password-strong"},
            ).status_code
            == 401
        )
        login(member, "governance-member", "reset-password-strong")
    finally:
        member.close()


def test_role_change_applies_to_existing_session_immediately(console):
    headers = login(console)
    user_id = create_member(console, headers, role="admin")
    member = TestClient(console.app, raise_server_exceptions=False)
    try:
        login(member, "governance-member", "member-password-strong")
        assert member.get("/admin/api/audit").status_code == 200
        assert (
            console.put(f"/admin/api/users/{user_id}", headers=headers, json={"role": "member"}).status_code
            == 200
        )
        assert member.get("/admin/api/audit").status_code == 403
        assert member.get("/admin/api/session").json()["user"]["role"] == "member"
    finally:
        member.close()


@pytest.mark.parametrize(
    "path",
    ["/providers/health", "/audit", "/usage?days=7", "/keys?scope=all", "/providers/export"],
)
def test_governance_read_endpoints_require_administrator(console, path):
    headers = login(console)
    create_member(console, headers)
    assert console.get("/admin/api" + path).status_code == 200
    login(console, "governance-member", "member-password-strong")
    assert console.get("/admin/api" + path).status_code == 403


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PUT", "/users/2", {"role": "admin"}),
        ("DELETE", "/keys/key-id?scope=all", None),
        ("POST", "/sessions/revoke-others", None),
        ("POST", "/providers/import", {"version": 1, "providers": []}),
    ],
)
def test_governance_writes_require_csrf_and_same_origin(console, method, path, body):
    headers = login(console)
    create_member(console, headers)
    assert console.request(method, "/admin/api" + path, json=body).status_code == 403
    assert (
        console.request(
            method,
            "/admin/api" + path,
            json=body,
            headers={**headers, "Origin": "https://foreign.example"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PUT", "/users/2", {"role": "admin"}),
        ("PUT", "/users/1", {"password": "attacker-password-strong"}),
        ("DELETE", "/users/1", None),
        ("DELETE", "/keys/key-id?scope=all", None),
        (
            "POST",
            "/providers/import",
            {
                "version": 1,
                "providers": [
                    {"name": "unauthorized", "provider": "searxng", "api_base": "http://localhost:8080"},
                ],
            },
        ),
    ],
)
def test_governance_administrator_writes_reject_member_sessions(console, method, path, body):
    headers = login(console)
    create_member(console, headers)
    headers = login(console, "governance-member", "member-password-strong")
    assert (
        console.request(
            method,
            "/admin/api" + path,
            json=body,
            headers=headers,
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "body",
    [
        {"scopes": []},
        {"scopes": ["admin"]},
        {"expires_at": 1},
        {"expires_at": "NaN"},
        {"expires_at": "Infinity"},
    ],
)
def test_invalid_key_scope_and_expiration_are_rejected_without_secret_echo(console, body):
    headers = login(console)
    response = console.post("/admin/api/keys", headers=headers, json={"name": "invalid", **body})
    assert response.status_code == 422
    assert console.get("/admin/api/keys").json()["keys"] == []


@pytest.mark.parametrize(
    "scopes,method,path",
    [
        (["protocol"], "POST", "/search"),
        (["protocol"], "POST", "/v1/search/searxng"),
        (["protocol"], "GET", "/search/tools"),
        (["search"], "GET", "/bensz-search/v1/capabilities"),
        (["search"], "POST", "/bensz-search/v1/search"),
        (["search"], "POST", "/bensz-search/mcp"),
    ],
)
def test_key_scopes_are_enforced_on_native_protocol_and_mcp_paths(console, scopes, method, path):
    headers = login(console)
    key = console.post("/admin/api/keys", headers=headers, json={"name": "scoped", "scopes": scopes}).json()[
        "key"
    ]
    response = console.request(
        method, path, headers={"Authorization": "Bearer " + key}, json={"query": "scope-test"}
    )
    assert response.status_code == 403, response.text


def test_expired_key_is_rejected_at_authentication(console):
    headers = login(console)
    created = console.post(
        "/admin/api/keys",
        headers=headers,
        json={"name": "expiring", "expires_at": time.time() + 600},
    ).json()
    runtime = console.app.state.admin_runtime
    with runtime.store.lock, runtime.store.db:
        runtime.store.db.execute(
            "UPDATE access_keys SET expires_at=? WHERE id=?", (time.time() - 1, created["record"]["id"])
        )
    response = console.post(
        "/search",
        json={"query": "expiry-test"},
        headers={"Authorization": "Bearer " + created["key"]},
    )
    assert response.status_code == 401


def test_global_keys_require_admin_and_explicit_global_scope(console):
    admin_headers = login(console)
    create_member(console, admin_headers)
    member_headers = login(console, "governance-member", "member-password-strong")
    member_key = console.post("/admin/api/keys", headers=member_headers, json={"name": "member-owned"}).json()
    key_id = member_key["record"]["id"]
    assert console.delete(f"/admin/api/keys/{key_id}?scope=all", headers=member_headers).status_code == 403
    admin_headers = login(console)
    assert console.get("/admin/api/keys").json()["keys"] == []
    assert console.delete(f"/admin/api/keys/{key_id}", headers=admin_headers).status_code == 404
    global_list = console.get("/admin/api/keys?scope=all")
    assert member_key["key"] not in global_list.text
    assert key_id in {r["id"] for r in global_list.json()["keys"]}
    assert console.delete(f"/admin/api/keys/{key_id}?scope=all", headers=admin_headers).status_code == 200
    assert (
        console.get(
            "/bensz-search/v1/capabilities", headers={"Authorization": "Bearer " + member_key["key"]}
        ).status_code
        == 401
    )


def test_public_sessions_are_opaque_and_revoke_others_is_owner_scoped(console):
    headers = login(console)
    create_member(console, headers)
    admin_device = TestClient(console.app, raise_server_exceptions=False)
    member_device = TestClient(console.app, raise_server_exceptions=False)
    try:
        login(admin_device)
        login(member_device, "governance-member", "member-password-strong")
        listing = console.get("/admin/api/sessions")
        rows = listing.json()["sessions"]
        assert len(rows) == 2
        assert sum(row["current"] for row in rows) == 1
        for row in rows:
            assert set(row) == {"id", "created_at", "expires_at", "current"}
        for device in (console, admin_device, member_device):
            token = device.cookies.get("bensz_session")
            assert token not in listing.text
            assert digest(token) not in listing.text
        assert console.post("/admin/api/sessions/revoke-others", headers=headers).status_code == 200
        assert console.get("/admin/api/session").status_code == 200
        assert admin_device.get("/admin/api/session").status_code == 401
        assert member_device.get("/admin/api/session").status_code == 200
    finally:
        admin_device.close()
        member_device.close()


def test_audit_and_persistent_usage_do_not_store_identity_or_search_secrets(console):
    headers = login(console)
    create_member(console, headers, "private-user-fixture")
    key = console.post("/admin/api/keys", headers=headers, json={"name": "private-key-label"}).json()["key"]

    async def call(**kwargs):
        return SearchResponse(
            results=[
                SearchResult(
                    title="Mock search document", url="https://example.org/doc", snippet="Synthetic result"
                )
            ]
        )

    console.app.state.smart_search.call = call
    response = console.post(
        "/search",
        headers={"Authorization": "Bearer " + key},
        json={"query": "private-search-phrase-fixture"},
    )
    assert response.status_code == 200, response.text
    audit = console.get("/admin/api/audit")
    usage = console.get("/admin/api/usage?days=7")
    assert audit.status_code == usage.status_code == 200
    assert usage.json()["summary"]["requests"] == 1
    key_record = console.get("/admin/api/keys").json()["keys"][0]
    assert key_record["usage_count"] == 1
    assert key_record["last_used_at"] is not None
    assert (
        console.get("/bensz-search/v1/capabilities", headers={"Authorization": "Bearer " + key}).status_code
        == 200
    )
    assert console.get("/admin/api/keys").json()["keys"][0]["usage_count"] == 1
    store = console.app.state.admin_runtime.store
    persisted = str([tuple(row) for row in store.db.execute("SELECT * FROM audit_events")])
    persisted += str([tuple(row) for row in store.db.execute("SELECT * FROM usage_daily")])
    public = audit.text + usage.text
    for value in (
        "private-user-fixture",
        "private-key-label",
        "member-password-strong",
        "test-password-strong",
        "private-search-phrase-fixture",
        key,
    ):
        assert value not in persisted
        assert value not in public
    events = audit.json()["events"]
    assert {e["object_type"] for e in events} >= {"user", "key"}
    filtered = console.get("/admin/api/audit?actor_id=1&object_type=key&limit=1").json()
    assert len(filtered["events"]) == 1
    assert filtered["events"][0]["actor_id"] == 1
    assert filtered["events"][0]["object_type"] == "key"


def test_key_use_is_counted_once_across_native_http_and_mcp_search(console, monkeypatch):
    import litellm
    from test_openai_search import web_response
    from test_protocol_http import rpc

    headers = login(console)
    provider = {
        "name": "observed-openai",
        "provider": "openai",
        "api_key": "mock-openai-secret",
    }
    assert console.post("/admin/api/providers", headers=headers, json=provider).status_code == 200
    assert console.delete("/admin/api/providers/searxng", headers=headers).status_code == 200

    async def responses(**kwargs):
        return web_response()

    monkeypatch.setattr(litellm, "aresponses", responses)
    key = console.post("/admin/api/keys", headers=headers, json={"name": "observed"}).json()["key"]
    auth = {"Authorization": "Bearer " + key}
    for expected, path in enumerate(("/search", "/search/observed-openai", "/bensz-search/v1/search"), 1):
        response = console.post(path, headers=auth, json={"query": "Python docs"})
        assert response.status_code == 200, response.text
        assert console.get("/admin/api/keys").json()["keys"][0]["usage_count"] == expected
    capability = rpc(console, auth, "tools/call", {"name": "bensz_search_capabilities", "arguments": {}})
    assert capability.status_code == 200, capability.text
    assert console.get("/admin/api/keys").json()["keys"][0]["usage_count"] == 3
    mcp_search = rpc(
        console,
        auth,
        "tools/call",
        {
            "name": "bensz_search",
            "arguments": {"query": "Python docs"},
        },
    )
    assert mcp_search.status_code == 200, mcp_search.text
    assert not mcp_search.json()["result"].get("isError")
    assert console.get("/admin/api/keys").json()["keys"][0]["usage_count"] == 4
    # A cookie-authenticated debug call belongs in aggregate usage, not this API key's usage.
    assert (
        console.post(
            "/admin/api/search",
            headers=headers,
            json={"query": "Python docs", "search_tool_name": "observed-openai"},
        ).status_code
        == 200
    )
    assert console.get("/admin/api/keys").json()["keys"][0]["usage_count"] == 4
    assert console.get("/admin/api/usage?days=7").json()["summary"]["requests"] == 5


def test_provider_export_contains_no_credentials_and_import_is_atomic(console):
    headers = login(console)
    assert (
        console.post(
            "/admin/api/providers",
            headers=headers,
            json={"name": "private-exa", "provider": "exa_ai", "api_key": "provider-secret-fixture"},
        ).status_code
        == 200
    )
    exported = console.get("/admin/api/providers/export")
    assert exported.status_code == 200
    assert "provider-secret-fixture" not in exported.text
    assert "api_key" not in exported.text
    new_record = {
        "name": "new-searx",
        "provider": "searxng",
        "api_base": "http://localhost:8080",
    }
    response = console.post(
        "/admin/api/providers/import",
        headers=headers,
        json={"version": 1, "providers": [new_record, {**new_record, "name": "searxng"}]},
    )
    assert response.status_code == 409
    assert "new-searx" not in {r["name"] for r in console.get("/admin/api/providers").json()["providers"]}
    assert (
        console.post(
            "/admin/api/providers/import",
            headers=headers,
            json={"version": 1, "providers": [new_record]},
        ).status_code
        == 200
    )
    saved = console.app.state.admin_runtime.store.providers(private=True)
    assert next(p for p in saved if p["name"] == "private-exa")["api_key"] == "provider-secret-fixture"


@pytest.mark.parametrize(
    "invalid",
    [
        {"provider": "unsupported"},
        {"api_base": "http://user:secret@localhost:8080"},
        {"api_key": "secret-import-fixture"},
    ],
)
def test_provider_import_validates_every_record_before_writing(console, invalid):
    headers = login(console)
    valid = {"name": "first", "provider": "searxng", "api_base": "http://localhost:8080"}
    response = console.post(
        "/admin/api/providers/import",
        headers=headers,
        json={"version": 1, "providers": [valid, {**valid, "name": "second", **invalid}]},
    )
    assert response.status_code == 422
    assert "secret-import-fixture" not in response.text
    assert "user:secret" not in response.text
    names = {r["name"] for r in console.get("/admin/api/providers").json()["providers"]}
    assert "first" not in names and "second" not in names
