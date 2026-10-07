"""Real console and legacy/v1 entry points with remote HTTP I/O simulated."""

import json

import httpx
from test_admin import console as console
from test_admin import login


def test_remote_provider_crud_test_and_application_search(console, monkeypatch):
    admin = login(console)
    requests = []
    leaf = {
        "call_id": "leaf",
        "tool_id": "brave",
        "rank": 1,
        "source_family": "brave",
        "snippet_kind": "generated_summary",
        "date": None,
    }

    async def send(client, request, **kwargs):
        assert request.url.host == "remote.example"
        assert request.headers["authorization"] == "Bearer remote-test-key"
        requests.append(request)
        result = (
            {}
            if request.method == "GET"
            else {
                "request_id": "remote-request",
                "status": "success",
                "results": [
                    {
                        "result_id": "r",
                        "title": "Remote result",
                        "url": "https://example.org/doc",
                        "canonical_identity": "example.org/doc",
                        "aliases": [],
                        "snippet": "generated remote summary",
                        "snippet_kind": "generated_summary",
                        "date": None,
                        "sources": [leaf],
                        "fusion_score": 1.0,
                    }
                ],
            }
        )
        return httpx.Response(
            200,
            json=result,
            headers={"x-bensz-search-federation": "1", "x-bensz-search-node": "remote-node"},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    data = {
        "name": "remote",
        "provider": "bensz_search",
        "api_base": "https://remote.example",
        "api_key": "remote-test-key",
        "timeout_ms": 1200,
    }
    assert (
        console.post("/admin/api/providers", headers=admin, json={**data, "api_base": ""}).status_code == 422
    )
    assert (
        console.post("/admin/api/providers", headers=admin, json={**data, "api_key": ""}).status_code == 422
    )
    assert console.post("/admin/api/providers", headers=admin, json=data).status_code == 200
    public = console.get("/admin/api/providers").json()
    assert any(p["provider"] == "bensz_search" for p in public["catalog"])
    assert "remote-test-key" not in json.dumps(public)
    assert (
        console.put(
            "/admin/api/providers/remote", headers=admin, json={**data, "api_key": "", "enabled": False}
        ).status_code
        == 200
    )
    tested = console.post("/admin/api/providers/remote/test", headers=admin, json={"query": "q"})
    assert tested.json()["ok"], tested.text
    assert tested.json()["results"][0]["snippet_kind"] == "generated_summary"
    assert (
        console.put("/admin/api/providers/remote", headers=admin, json={**data, "api_key": ""}).status_code
        == 200
    )
    debugged = console.post(
        "/admin/api/search",
        headers=admin,
        json={
            "query": "q",
            "search_tool_name": "remote",
            "profile": {"intent": "news"},
            "constraints": {"latency_budget_ms": 600},
        },
    )
    assert debugged.status_code == 200, debugged.text
    payload = json.loads(requests[-1].content)
    assert payload["profile"]["intent"] == "news"
    assert payload["constraints"]["latency_budget_ms"] <= 600
    app_key = console.post("/admin/api/keys", headers=admin, json={"name": "remote-client"}).json()["key"]
    headers = {"Authorization": "Bearer " + app_key}
    for path in ("/search/remote", "/v1/search/remote"):
        result = console.post(path, headers=headers, json={"query": "q"})
        assert result.status_code == 200, result.text
        assert result.json()["results"][0]["source_families"] == ["brave"]
    protocol = console.post(
        "/bensz-search/v1/search",
        headers=headers,
        json={"mode": "planned", "calls": [{"call_id": "r", "tool_id": "remote", "query": "q"}]},
    )
    assert protocol.status_code == 200, protocol.text
    source = protocol.json()["results"][0]["sources"][0]
    assert source["source_family"] == "brave" and source["instance_path"] == ["remote-node"]
    assert source["upstream_tool_id"] == "brave"
    assert "remote-test-key" not in protocol.text
    assert console.delete("/admin/api/providers/remote", headers=admin).status_code == 200
    assert console.post("/search/remote", headers=headers, json={"query": "q"}).status_code in {
        400,
        403,
        404,
        422,
    }
