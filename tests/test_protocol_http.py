"""Real gateway lifecycle, application-key confinement and HTTP/MCP parity."""

import json

import pytest
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult
from test_admin import console as console
from test_admin import login


def application_key(console):
    headers = login(console)
    key = console.post("/admin/api/keys", headers=headers, json={"name": "protocol"}).json()
    return headers, key, {"Authorization": "Bearer " + key["key"]}


def rpc(console, headers, method, params=None, request_id=1):
    return console.post(
        "/bensz-search/mcp/",
        headers={
            **headers,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
    )


@pytest.mark.parametrize("permanent", [False, True])
def test_application_key_discovery_execution_revocation_and_errors(console, permanent):
    admin, key, headers = application_key(console)
    calls = []

    async def call(**kwargs):
        calls.append(kwargs)
        return SearchResponse(
            results=[SearchResult(title="文献", url="https://example.org/paper", snippet="fixture")]
        )

    console.app.state.smart_search.call = call
    snapshot = console.get("/bensz-search/v1/capabilities", headers=headers)
    assert snapshot.status_code == 200, snapshot.text
    assert "api_base" not in snapshot.text and "api_key" not in snapshot.text
    request = {
        "mode": "planned",
        "registry_revision": snapshot.json()["registry_revision"],
        "calls": [{"call_id": "a", "tool_id": "searxng", "query": "中文文献"}],
    }
    result = console.post("/bensz-search/v1/search", headers=headers, json=request)
    assert result.status_code == 200, result.text
    assert result.json()["results"][0]["sources"][0]["tool_id"] == "searxng"
    assert len(calls) == 1
    invalid = console.post("/bensz-search/v1/search", headers=headers, json={**request, "api_key": "SECRET"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_plan"
    assert "SECRET" not in invalid.text and len(calls) == 1
    assert console.get("/admin/api/providers", headers=headers).status_code == 200  # session still admin
    console.cookies.clear()
    assert console.get("/admin/api/providers", headers=headers).status_code in {401, 403}
    # Reauthenticate the console to revoke the application credential.
    admin = login(console)
    assert (
        console.delete(
            "/admin/api/keys/" + key["record"]["id"], params={"permanent": permanent}, headers=admin
        ).status_code
        == 200
    )
    assert bool(console.get("/admin/api/keys").json()["keys"]) is not permanent
    assert console.post("/search", headers=headers, json={"query": "deleted-key"}).status_code == 401
    assert console.get("/bensz-search/v1/capabilities", headers=headers).status_code == 401
    assert console.post("/bensz-search/v1/search", headers=headers, json=request).status_code == 401
    assert rpc(console, headers, "tools/list").status_code == 401


def test_mcp_standard_discovery_and_shared_search_result(console):
    _, _, headers = application_key(console)
    called = []

    async def call(**kwargs):
        called.append(kwargs["query"])
        return SearchResponse(
            results=[SearchResult(title="Fixture", url="https://example.org/doc", snippet="x")]
        )

    console.app.state.smart_search.call = call
    init = rpc(
        console,
        headers,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-host", "version": "1"},
        },
    )
    assert init.status_code == 200, init.text
    assert "protocolVersion" in init.json()["result"]
    tools = rpc(console, headers, "tools/list")
    assert tools.status_code == 200, tools.text
    assert [t["name"] for t in tools.json()["result"]["tools"]] == [
        "bensz_search_capabilities",
        "bensz_search",
    ]
    capability = rpc(console, headers, "tools/call", {"name": "bensz_search_capabilities", "arguments": {}})
    assert capability.status_code == 200, capability.text
    data = capability.json()["result"]
    snapshot = data.get("structuredContent") or json.loads(data["content"][0]["text"])
    args = {
        "mode": "planned",
        "registry_revision": snapshot["registry_revision"],
        "calls": [{"call_id": "a", "tool_id": "searxng", "query": "query"}],
    }
    http_result = console.post("/bensz-search/v1/search", headers=headers, json=args).json()
    mcp_result = rpc(console, headers, "tools/call", {"name": "bensz_search", "arguments": args})
    assert mcp_result.status_code == 200, mcp_result.text
    business = mcp_result.json()["result"]
    data = business.get("structuredContent") or json.loads(business["content"][0]["text"])
    assert data["results"] == http_result["results"]
    assert data["status"] == http_result["status"]
    assert called == ["query", "query"]  # exactly one physical execution per request
    invalid = rpc(
        console, headers, "tools/call", {"name": "bensz_search", "arguments": {"api_key": "SECRET"}}
    )
    assert invalid.json()["result"]["isError"]
    assert "SECRET" not in invalid.text
    assert len(called) == 2
    personal = console.get("/admin/api/usage/me").json()
    assert personal["summary"]["requests"] == 2
    assert personal["by_provider"][0]["requests"] == 2
