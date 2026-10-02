"""Native gateway contracts, with provider I/O replaced after proxy startup."""

from fastapi.testclient import TestClient
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult


def test_native_proxy_auth_auto_and_validation(monkeypatch):
    monkeypatch.setenv("BENSZ_SEARCH_MODE", "development")
    monkeypatch.setenv("BENSZ_SEARCH_CONFIG", "config/demo.yaml")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-bensz-search-local-demo")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    from bensz_search.server import app

    calls = []

    async def call(**kwargs):
        calls.append(kwargs["search_tool_name"])
        return SearchResponse(
            results=[SearchResult(title="Fixture", url="https://example.org/doc", snippet="fixture")]
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.smart_search.call = call
        headers = {"Authorization": "Bearer sk-bensz-search-local-demo"}
        response = client.post("/search", json={"query": "capital of France"})
        assert response.status_code == 401, response.text
        assert calls == []
        response = client.post("/search", json={"query": "capital of France", "debug": True}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["debug"]["plan"]["strategy"] == "single"
        assert len(calls) == 1
        response = client.post(
            "/v1/search/auto", json={"query": "ctDNA trial", "debug": True}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["debug"]["plan"]["strategy"] == "parallel"
        assert len(calls) == 3
        response = client.post(
            "/search", json={"query": "fixture", "api_base": "http://arbitrary"}, headers=headers
        )
        assert response.status_code == 422
        assert len(calls) == 3
        response = client.get("/smart-search/metrics", headers=headers)
        assert response.status_code == 200, response.text


def test_production_requires_a_real_master_key(monkeypatch):
    import pytest

    from bensz_search.server import effective_config

    monkeypatch.setenv("BENSZ_SEARCH_CONFIG", "config/demo.yaml")
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LITELLM_MASTER_KEY"):
        effective_config()
