"""Identity, credential protection and real management/runtime contracts."""

import secrets

import pytest
from fastapi.testclient import TestClient
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from bensz_search.admin import login_attempts
from bensz_search.admin_store import AdminStore


@pytest.fixture
def console(monkeypatch, tmp_path):
    monkeypatch.setenv("BENSZ_SEARCH_MODE", "production")
    monkeypatch.setenv("BENSZ_SEARCH_CONFIG", "config/litellm.yaml")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test-" + secrets.token_urlsafe(32))
    monkeypatch.setenv("BENSZ_SEARCH_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv("BENSZ_SEARCH_ADMIN_PASSWORD", "test-password-strong")
    monkeypatch.setenv("BENSZ_SEARCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SEARXNG_API_BASE", "http://localhost:8080")
    monkeypatch.setenv("SEARXNG_ENGINES", "github,pubmed")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    for key in ("EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    from bensz_search.server import app

    login_attempts.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def login(client, username="admin", password="test-password-strong"):
    response = client.post("/admin/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_sessions_csrf_and_password_rotation(console):
    assert console.get("/admin/api/session").status_code == 401
    assert (
        console.post("/admin/api/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    )
    headers = login(console)
    assert console.get("/admin/api/session").json()["user"]["role"] == "admin"
    assert console.post("/admin/api/keys", json={"name": "test"}).status_code == 403
    assert (
        console.post(
            "/admin/api/keys", json={"name": "test"}, headers={**headers, "Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    response = console.post(
        "/admin/api/password",
        headers=headers,
        json={"current_password": "test-password-strong", "new_password": "new-password-strong"},
    )
    assert response.status_code == 200
    assert console.get("/admin/api/session").status_code == 401
    login(console, password="new-password-strong")


def test_member_permissions_and_key_ownership(console):
    admin_headers = login(console)
    response = console.post(
        "/admin/api/users",
        headers=admin_headers,
        json={"username": "member", "password": "member-password-strong", "role": "member"},
    )
    assert response.status_code == 200
    admin_key = console.post("/admin/api/keys", headers=admin_headers, json={"name": "admin-key"}).json()
    member_headers = login(console, "member", "member-password-strong")
    assert console.get("/admin/api/users").status_code == 403
    assert console.get("/admin/api/providers").status_code == 403
    assert (
        console.delete("/admin/api/keys/" + admin_key["record"]["id"], headers=member_headers).status_code
        == 404
    )
    overview = console.get("/admin/api/overview").json()
    assert "api_base" not in overview["providers"][0]
    assert overview["metrics"]["recent"] == []
    assert (
        console.post(
            "/admin/api/users",
            headers=member_headers,
            json={"username": "attack", "password": "attack-password-strong", "role": "admin"},
        ).status_code
        == 403
    )


def test_provider_crud_and_live_runtime(console):
    headers = login(console)
    assert console.app.state.smart_search.registry.providers["searxng"].intent_engines == {
        "academic": ["pubmed"],
        "coding": ["github"],
    }
    body = {
        "name": "my-exa",
        "provider": "exa_ai",
        "enabled": True,
        "api_key": "provider-secret-test",
        "timeout_ms": 6000,
    }
    assert console.post("/admin/api/providers", json=body, headers=headers).status_code == 200
    public = console.get("/admin/api/providers").text
    assert "provider-secret-test" not in public
    assert "my-exa" in console.app.state.admin_runtime.active_names()
    saved = console.app.state.admin_runtime.store.providers(private=True)
    assert next(p for p in saved if p["name"] == "my-exa")["api_key"] == "provider-secret-test"
    body.update(api_key="", enabled=False)
    assert console.put("/admin/api/providers/my-exa", json=body, headers=headers).status_code == 200
    assert "my-exa" not in console.app.state.admin_runtime.active_names()
    body.update(provider="searxng", api_base="http://localhost:8080", engines=["pubmed"])
    assert console.put("/admin/api/providers/my-exa", json=body, headers=headers).status_code == 200
    changed = next(
        p for p in console.app.state.admin_runtime.store.providers(private=True) if p["name"] == "my-exa"
    )
    assert changed["api_key"] == ""
    assert console.delete("/admin/api/providers/my-exa", headers=headers).status_code == 200
    assert console.delete("/admin/api/providers/searxng", headers=headers).status_code == 200
    assert console.get("/ready").status_code == 503
    assert console.post("/admin/api/search", json={"query": "test"}, headers=headers).status_code == 503
    assert console.get("/admin/api/session").status_code == 200


def test_search_access_keys_and_revocation(console):
    headers = login(console)

    async def call(**kwargs):
        return SearchResponse(
            results=[SearchResult(title="Test document", url="https://example.org/doc", snippet="test")]
        )

    console.app.state.smart_search.call = call
    created = console.post("/admin/api/keys", headers=headers, json={"name": "app"}).json()
    key = created["key"]
    api_headers = {"Authorization": "Bearer " + key}
    assert key not in console.get("/admin/api/keys").text
    response = console.post("/search", json={"query": "test"}, headers=api_headers)
    assert response.status_code == 200, response.text
    assert console.post("/key/generate", json={}, headers=api_headers).status_code == 403
    assert console.get("/smart-search/metrics", headers=api_headers).status_code == 403
    assert console.delete("/admin/api/keys/" + created["record"]["id"], headers=headers).status_code == 200
    assert console.post("/search", json={"query": "test"}, headers=api_headers).status_code == 401


@pytest.mark.parametrize("path", ["/search", "/search/searxng", "/v1/search/auto", "/v1/search/searxng"])
def test_all_search_paths_reject_overrides_and_large_bodies(console, path):
    assert console.post(path, json={"query": "test", "api_base": "http://internal"}).status_code == 422
    assert console.post(path, content=b"x" * 128001).status_code == 413


def test_persistence_and_encrypted_credentials(tmp_path):
    path = tmp_path / "test.sqlite3"
    secret = secrets.token_urlsafe(48)
    store = AdminStore(path, secret)
    store.bootstrap("admin", "test-password-strong")
    store.save_provider({"name": "test", "provider": "exa_ai", "enabled": True}, "provider-secret-test")
    token, _ = store.login("admin", "test-password-strong")
    key = store.create_key(1, "test")["key"]
    store.close()
    raw = path.read_bytes()
    for value in ("test-password-strong", "provider-secret-test", token, key):
        assert value.encode() not in raw
    restored = AdminStore(path, secret)
    assert restored.providers(private=True)[0]["api_key"] == "provider-secret-test"
    assert restored.session(token)
    assert restored.authenticate_key(key)
    restored.close()


def test_production_rejects_fixture_configuration(monkeypatch):
    from bensz_search.server import effective_config

    monkeypatch.setenv("BENSZ_SEARCH_MODE", "production")
    monkeypatch.setenv("BENSZ_SEARCH_CONFIG", "config/demo.yaml")
    monkeypatch.setenv("LITELLM_MASTER_KEY", secrets.token_urlsafe(48))
    with pytest.raises(RuntimeError, match="Fixture"):
        effective_config()


def test_production_rejects_fixture_environment(monkeypatch):
    from bensz_search.server import effective_config

    monkeypatch.setenv("BENSZ_SEARCH_MODE", "production")
    monkeypatch.setenv("BENSZ_SEARCH_CONFIG", "config/litellm.yaml")
    monkeypatch.setenv("LITELLM_MASTER_KEY", secrets.token_urlsafe(48))
    monkeypatch.setenv("SEARXNG_API_BASE", "https://fixtures/searxng")
    with pytest.raises(RuntimeError, match="Fixture"):
        effective_config()
