"""Identity, credential protection and real management/runtime contracts."""

import os
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from bensz_search.admin import login_attempts
from bensz_search.admin_store import AdminStore


@pytest.fixture
def console(monkeypatch, tmp_path, request):
    monkeypatch.setenv("BENSZ_SEARCH_MODE", "production")
    monkeypatch.setenv("BENSZ_SEARCH_CONFIG", "config/litellm.yaml")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test-" + secrets.token_urlsafe(32))
    monkeypatch.setenv("BENSZ_SEARCH_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv("BENSZ_SEARCH_ADMIN_PASSWORD", "test-password-strong")
    monkeypatch.setenv("BENSZ_SEARCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SEARXNG_API_BASE", "http://localhost:8080")
    engines = getattr(request, "param", "github,pubmed")
    if engines is None:
        monkeypatch.delenv("SEARXNG_ENGINES", raising=False)
    else:
        monkeypatch.setenv("SEARXNG_ENGINES", engines)
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    for key in (
        "EXA_API_KEY",
        "BRAVE_API_KEY",
        "TAVILY_API_KEY",
        "SERPER_API_KEY",
        "PERPLEXITY_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    from bensz_search.server import app

    login_attempts.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def login(client, username="admin", password="test-password-strong"):
    response = client.post("/admin/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.mark.parametrize(
    "message, category",
    [("Not enough credits", "quota"), ("Invalid query", "bad_request")],
)
def test_serper_test_classifies_real_http_error(console, monkeypatch, message, category):
    headers = login(console)
    assert (
        console.post(
            "/admin/api/providers",
            headers=headers,
            json={"name": "Serper", "provider": "serper", "api_key": "test-provider-secret"},
        ).status_code
        == 200
    )
    requests = []

    async def send(self, request, **kwargs):
        assert str(request.url) == "https://google.serper.dev/search"
        requests.append(request)
        return httpx.Response(400, json={"message": message, "statusCode": 400}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    response = console.post("/admin/api/providers/Serper/test", headers=headers, json={"query": "三体"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["category"] == category
    assert data["result_count"] == 0
    assert data["results"] == []
    assert len(requests) == 1
    assert "test-provider-secret" not in response.text
    assert message not in response.text


@pytest.mark.parametrize("path", ["/", "/search", "/v1/search"])
def test_browser_entries_redirect_without_search_credentials(console, path):
    response = console.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    page = console.get(path)
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert console.get("/admin/api/session").status_code == 401


@pytest.mark.parametrize("path", ["/admin", "/admin/", "/app", "/app/"])
def test_workspace_entries_keep_session_api_protected(console, path):
    response = console.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "no-store" in response.headers["cache-control"].split(", ")
    assert "nosniff" in response.headers["x-content-type-options"].split(", ")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert console.get("/admin/api/session").status_code == 401
    login(console)
    assert console.get(path).status_code == 200
    assert console.get("/admin/api/session").json()["user"]["role"] == "admin"


@pytest.mark.parametrize("trusted_hosts, expected", [("127.0.0.1", 403), ("172.18.0.22", 200)])
def test_https_login_behind_proxy(console, monkeypatch, trusted_hosts, expected):
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    monkeypatch.setenv("BENSZ_SEARCH_COOKIE_SECURE", "true")
    app = ProxyHeadersMiddleware(console.app, trusted_hosts=trusted_hosts)
    client = TestClient(app, base_url="http://search.example", client=("172.18.0.22", 12345))
    headers = {
        "Origin": "https://search.example",
        "X-Forwarded-Proto": "https",
        "Sec-Fetch-Site": "same-origin",
    }
    response = client.post(
        "/admin/api/login", headers=headers, json={"username": "admin", "password": "test-password-strong"}
    )
    assert response.status_code == expected
    if expected == 200:
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("https://search.example/admin/api/session", headers=headers).status_code == 200
    response = client.post(
        "/admin/api/login",
        headers={**headers, "Origin": "https://evil.example"},
        json={"username": "admin", "password": "test-password-strong"},
    )
    assert response.status_code == 403
    client.close()


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
    assert console.get("/app").status_code == 200
    assert console.get("/admin/api/session").json()["user"]["role"] == "member"
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


@pytest.mark.parametrize("console", [None, ""], indirect=True)
def test_searxng_default_engines_and_explicit_instance_defaults(console):
    headers = login(console)
    data = console.get("/admin/api/providers").json()
    configured = next(row for row in data["providers"] if row["name"] == "searxng")
    recommended = next(row for row in data["catalog"] if row["provider"] == "searxng")["default_engines"]
    assert {
        "google",
        "bing",
        "duckduckgo",
        "brave",
        "baidu",
        "wikipedia",
        "github",
        "pubmed",
        "arxiv",
        "google news",
        "stackoverflow",
    } <= set(recommended)
    # Missing env selects application defaults; an explicit empty value uses instance defaults.
    expected = [] if os.environ.get("SEARXNG_ENGINES") == "" else recommended
    assert configured["engines"] == expected
    runtime = console.app.state.admin_runtime
    if expected:
        assert runtime.capability(configured).intent_engines["general"] == [
            "google",
            "bing",
            "duckduckgo",
            "brave",
            "baidu",
            "wikipedia",
        ]
        assert runtime.capability(configured).intent_engines["academic"] == ["pubmed", "arxiv"]
        assert runtime.capability(configured).intent_engines["coding"] == ["github", "stackoverflow"]
        assert runtime.capability(configured).intent_engines["news"] == ["google news"]
    # Applying recommendations updates the active router; a custom list remains authoritative.
    for engines in [recommended, ["duckduckgo", "pubmed"], []]:
        body = {
            "name": "searxng",
            "provider": "searxng",
            "api_base": configured["api_base"],
            "engines": engines,
        }
        assert console.put("/admin/api/providers/searxng", json=body, headers=headers).status_code == 200
        runtime.refresh()
        saved = next(row for row in runtime.store.providers() if row["name"] == "searxng")
        assert saved["engines"] == engines
        runtime.store.seed_providers([dict(body, engines=recommended)])
        assert runtime.store.providers()[0]["engines"] == engines


@pytest.mark.parametrize("console", [None], indirect=True)
def test_expanded_searxng_routes_queries_to_configured_engine_groups(console):
    headers = login(console)
    calls = []

    async def call(**kwargs):
        calls.append(kwargs)
        return SearchResponse(
            results=[SearchResult(title="Search result", url="https://example.org", snippet="Fixture result")]
        )

    console.app.state.smart_search.call = call
    for query, expected in [
        ("Paris travel guide", "google,bing,duckduckgo,brave,baidu,wikipedia"),
        ("colorectal cancer ctDNA", "pubmed,arxiv"),
        ("Python source code", "github,stackoverflow"),
        ("world news", "google news"),
    ]:
        result = console.post("/admin/api/search", json={"query": query}, headers=headers)
        assert result.status_code == 200, result.text
        assert calls[-1]["engines"] == expected


def test_openai_configuration_test_native_paths_and_auto(console, monkeypatch):
    import litellm
    from test_openai_search import web_response

    headers = login(console)
    calls = []

    async def responses(**kwargs):
        calls.append(kwargs)
        return web_response()

    monkeypatch.setattr(litellm, "aresponses", responses)
    body = {
        "name": "openai-main",
        "provider": "openai",
        "api_key": "openai-server-secret",
        "api_base": "https://configured.example/v1",
        "search_model": "gpt-4.1-mini",
        "search_context_size": "low",
        "max_output_tokens": 1024,
        "timeout_ms": 30000,
    }
    assert console.post("/admin/api/providers", headers=headers, json=body).status_code == 200
    public = console.get("/admin/api/providers")
    assert "openai-server-secret" not in public.text
    assert any(row["provider"] == "openai" for row in public.json()["catalog"])
    result = console.post(
        "/admin/api/providers/openai-main/test", headers=headers, json={"query": "Python docs"}
    )
    assert result.json()["ok"], result.text
    body.update(api_key="", enabled=False)
    assert console.put("/admin/api/providers/openai-main", headers=headers, json=body).status_code == 200
    assert "openai-main" not in console.app.state.admin_runtime.active_names()
    assert console.post("/admin/api/providers/openai-main/test", headers=headers, json={}).json()["ok"]
    body["enabled"] = True
    assert console.put("/admin/api/providers/openai-main", headers=headers, json=body).status_code == 200
    assert console.delete("/admin/api/providers/searxng", headers=headers).status_code == 200
    key = console.post("/admin/api/keys", headers=headers, json={"name": "openai-app"}).json()["key"]
    auth = {"Authorization": "Bearer " + key}
    for path in ("/search", "/v1/search", "/search/openai-main", "/v1/search/openai-main"):
        result = console.post(
            path,
            headers=auth,
            json={"query": "Python docs", "search_tool_name": "openai-main", "max_results": 1},
        )
        assert result.status_code == 200, result.text
        assert result.json()["object"] == "search" and len(result.json()["results"]) == 1
    result = console.post("/search", headers=auth, json={"query": "Python docs", "debug": True})
    assert result.status_code == 200, result.text
    assert result.json()["debug"]["providers"] == ["openai-main"]
    result = console.post(
        "/admin/api/search",
        headers=headers,
        json={
            "query": "Python docs",
            "search_tool_name": "openai-main",
            "search_domain_filter": ["docs.python.org"],
            "country": "GB",
        },
    )
    assert result.status_code == 200 and len(result.json()["results"]) == 1
    assert calls[-1]["tools"][0]["user_location"]["country"] == "GB"
    assert all(call["api_key"] == "openai-server-secret" for call in calls)
    assert console.post("/search/openai-main", json={"query": "q"}).status_code == 401
    assert (
        console.post(
            "/search/openai-main", headers=auth, json={"query": "q", "api_base": "https://evil.example"}
        ).status_code
        == 422
    )
    assert (
        console.delete(
            "/admin/api/keys/" + console.get("/admin/api/keys").json()["keys"][0]["id"], headers=headers
        ).status_code
        == 200
    )
    assert console.post("/search/openai-main", headers=auth, json={"query": "q"}).status_code == 401


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
