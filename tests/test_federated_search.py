"""Multi-instance HTTP recursion, shared limits, provenance and provider boundaries."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import litellm
import pytest
from fastapi import FastAPI, HTTPException, Request
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from bensz_search.federated_search import base_url
from bensz_search.federated_search import search as delegated_search
from bensz_search.federation import FederationMiddleware, WireContext, current, receive_context
from bensz_search.fusion import fuse
from bensz_search.integration import install
from bensz_search.models import SearchRequest
from bensz_search.openai_search import provider_call
from bensz_search.protocol import capabilities, search
from bensz_search.protocol_models import ProtocolSearch, SearchEnvelope
from bensz_search.registry import Registry
from bensz_search.router import SmartRouter


@pytest.fixture
def cluster(monkeypatch):
    apps, traffic, physical = {}, [], []
    templates = Registry.load("config/capabilities.yaml")
    transport_send = httpx.AsyncClient.send

    async def send(client, request, **kwargs):
        if request.url.host not in apps:
            return await transport_send(client, request, **kwargs)
        traffic.append((request.url.host, request.method, dict(request.headers), bytes(request.content)))
        response = await httpx.ASGITransport(app=apps[request.url.host]).handle_async_request(request)
        if not kwargs.get("stream", False):
            await response.aread()
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    def add(node, providers):
        registry = Registry(
            {name: templates.providers[kind].model_copy() for name, kind in providers.items()}
        )
        tools = []
        for name, kind in providers.items():
            params = {"search_provider": registry.providers[name].provider}
            if kind == "bensz_search":
                params.update(api_base="https://" + name, api_key="remote-" + name, timeout=5)
            tools.append({"search_tool_name": name, "litellm_params": params})
        native = litellm.Router(model_list=[], search_tools=tools, num_retries=0)

        async def leaf(**kwargs):
            physical.append((node, kwargs))
            return SearchResponse(
                results=[
                    SearchResult(title="Original source", url="https://example.org/doc", snippet="original")
                ]
            )

        smart = SmartRouter(registry, provider_call(native, leaf))
        app = FastAPI()
        app.state.smart = smart
        app.add_middleware(FederationMiddleware, node=node)

        def auth(request):
            if request.headers.get("authorization") != "Bearer remote-" + node:
                raise HTTPException(401, "Rejected")

        @app.get("/bensz-search/v1/capabilities")
        async def discover(request: Request):
            auth(request)
            return capabilities(smart, set(providers))

        @app.post("/bensz-search/v1/search", response_model=SearchEnvelope)
        async def query(data: ProtocolSearch, request: Request):
            auth(request)
            return await search(smart, data, set(providers))

        apps[node] = app
        return smart

    async def query(node, data=None, wire=None):
        headers = {"Authorization": "Bearer remote-" + node}
        if wire:
            headers["x-bensz-search-context"] = wire.model_dump_json()
        async with httpx.AsyncClient() as client:
            return await client.post(
                "https://" + node + "/bensz-search/v1/search",
                headers=headers,
                json=data or {"query": "capital of France"},
            )

    return SimpleNamespace(add=add, query=query, apps=apps, traffic=traffic, physical=physical)


async def test_three_instances_keep_query_constraints_and_leaf_provenance(cluster):
    cluster.add("a", {"b": "bensz_search"})
    cluster.add("b", {"c": "bensz_search"})
    cluster.add("c", {"brave": "brave"})
    response = await cluster.query(
        "a",
        {
            "query": "原文 query",
            "profile": {"intent": "academic"},
            "constraints": {"latency_budget_ms": 2400},
            "options": {"search_domain_filter": ["example.org"]},
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    source = data["results"][0]["sources"][0]
    assert source["tool_id"] == "b" and source["upstream_tool_id"] == "brave"
    assert source["source_family"] == "brave" and source["instance_path"] == ["b", "c"]
    assert cluster.physical[0][1]["query"] == "原文 query"
    delegated = [
        (host, json.loads(body), json.loads(headers["x-bensz-search-context"]))
        for host, method, headers, body in cluster.traffic
        if method == "POST" and host != "a"
    ]
    assert len(delegated) == 2
    assert [entry[2]["path"] for entry in delegated] == [["a"], ["a", "b"]]
    assert all(entry[1]["profile"]["intent"] == "academic" for entry in delegated)
    assert all(entry[1]["options"]["search_domain_filter"] == ["example.org"] for entry in delegated)
    assert (
        100
        <= delegated[1][1]["constraints"]["latency_budget_ms"]
        <= delegated[0][1]["constraints"]["latency_budget_ms"]
        <= 2400
    )
    assert "remote-b" not in response.text and "remote-c" not in response.text


async def test_a_b_a_is_rejected_before_reentering_search(cluster):
    cluster.add("a", {"b": "bensz_search"})
    cluster.add("b", {"a": "bensz_search"})
    response = await cluster.query("a")
    assert response.json()["status"] == "failed"
    assert response.json()["execution"][0]["error_code"] == "federation_loop"
    assert [(h, m) for h, m, _, _ in cluster.traffic].count(("a", "POST")) == 1
    assert not cluster.physical
    assert current.get() is None


async def test_depth_limit_still_allows_leaf_search_and_other_branch(cluster):
    cluster.add("a", {"b": "bensz_search", "brave": "brave"})
    cluster.add("b", {"c": "bensz_search"})
    cluster.add("c", {"brave": "brave"})
    data = {
        "mode": "planned",
        "calls": [
            {"call_id": "remote", "tool_id": "b", "query": "q"},
            {"call_id": "local", "tool_id": "brave", "query": "q"},
        ],
        "constraints": {"cost_budget_usd": 0.1},
    }
    response = await cluster.query("a", data, WireContext(max_hops=2))
    assert response.json()["status"] == "partial_success"
    assert response.json()["execution"][0]["error_code"] == "federation_depth_exceeded"
    assert [n for n, _ in cluster.physical] == ["a"]
    assert not any(host == "c" for host, *_ in cluster.traffic)


async def test_parallel_subtrees_never_duplicate_call_allowances(cluster):
    cluster.add("a", {"b": "bensz_search", "c": "bensz_search"})
    for n in ("b", "c"):
        cluster.add(n, {"brave": "brave", "serper": "serper", "searxng": "searxng"})
    data = {
        "mode": "planned",
        "calls": [{"call_id": n, "tool_id": n, "query": "comprehensive research"} for n in ("b", "c")],
        "constraints": {"cost_budget_usd": 0.1},
    }
    response = await cluster.query("a", data, WireContext(remaining_calls=4))
    assert response.json()["results"]
    assert len(cluster.physical) == 2
    # Two delegation edges + two leaf searches consume the four-slot tree.
    assert sum(m == "POST" and h != "a" for h, m, *_ in cluster.traffic) + len(cluster.physical) <= 4
    headers = [
        json.loads(headers["x-bensz-search-context"])
        for h, m, headers, _ in cluster.traffic
        if m == "POST" and h != "a"
    ]
    assert sum(h["remaining_calls"] for h in headers) == 2
    assert sum(h["cost_budget_usd"] for h in headers) <= 0.1


async def test_remote_auth_failure_falls_back_without_credentials_in_response(cluster):
    smart = cluster.add("a", {"b": "bensz_search", "brave": "brave"})
    cluster.add("b", {"brave": "brave"})

    async def deny(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"SECRET upstream body"})

    cluster.apps["b"] = deny
    data = {
        "mode": "planned",
        "calls": [
            {
                "call_id": "r",
                "tool_id": "b",
                "query": "q",
                "fallbacks": [{"call_id": "f", "tool_id": "brave", "query": "q"}],
            }
        ],
        "constraints": {"cost_budget_usd": 0.1},
    }
    response = await cluster.query("a", data)
    assert response.json()["status"] == "partial_success"
    assert response.json()["execution"][0]["error_code"] == "auth"
    assert "SECRET" not in response.text and "remote-b" not in response.text
    assert not smart.health.available("b")
    assert len(cluster.physical) == 1


async def test_parent_deadline_cancels_remote_and_no_late_search(cluster):
    cluster.add("a", {"b": "bensz_search"})
    b = cluster.add("b", {"brave": "brave"})
    cancelled = asyncio.Event()

    async def slow(**kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    b.call = slow
    started = time.monotonic()
    response = await cluster.query("a", {"query": "q", "constraints": {"latency_budget_ms": 150}})
    assert time.monotonic() - started < 1
    assert response.json()["status"] == "failed"
    assert response.json()["execution"][0]["error_code"] == "timeout"
    await asyncio.wait_for(cancelled.wait(), 0.5)


@pytest.mark.parametrize(
    "value",
    [
        "https://user:pass@x",
        "https://x/search",
        "https://x/bensz-search/v1",
        "https://x?secret=1",
        "file:///tmp/x",
    ],
)
def test_base_rejects_credentials_and_wrong_endpoints(value):
    with pytest.raises(ValueError):
        base_url(value)


@pytest.mark.parametrize(
    "value",
    [
        b"{}{}",
        b'{"path":["x","x"]}',
        b'{"path":["../x"]}',
        b'{"remaining_calls":9999}',
        b'{"cost_budget_usd":NaN}',
        b'{"max_hops":9}',
    ],
)
def test_invalid_context_is_rejected_without_echoing_it(value):
    with pytest.raises(Exception) as error:
        receive_context([(b"x-bensz-search-context", value)], "a")
    assert str(error.value) == "invalid_federation_context"


@pytest.mark.parametrize("status", [200, 307])
async def test_old_remote_and_redirect_are_never_searched(monkeypatch, status):
    requests = []

    async def send(client, request, **kwargs):
        requests.append(request)
        return httpx.Response(status, json={}, headers={"location": "https://other/"}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    with pytest.raises(ValueError):
        await delegated_search({"api_base": "https://old", "api_key": "remote-secret"}, {"query": "q"})
    assert len(requests) == 1 and requests[0].method == "GET"


def test_two_remote_brave_sources_do_not_increase_fusion_votes():
    remote = SearchResult(title="Doc", url="https://example.org/doc", snippet="", source_families=["brave"])
    _, single = fuse({"a": [remote]}, {}, {"a": "remote-a"}, "rrf", 10)
    _, two = fuse({"a": [remote], "b": [remote]}, {}, {"a": "remote-a", "b": "remote-b"}, "rrf", 10)
    assert single[0]["score"] == two[0]["score"]
    assert two[0]["family_contributions"] == {"brave": single[0]["score"]}


async def test_native_explicit_call_and_legacy_auto_use_same_adapter(cluster):
    smart = cluster.add("b", {"brave": "brave"})
    tools = [
        {
            "search_tool_name": "remote",
            "litellm_params": {
                "search_provider": "bensz_search",
                "api_base": "https://b",
                "api_key": "remote-b",
            },
        }
    ]
    native = litellm.Router(model_list=[], search_tools=tools, num_retries=0)
    proxy = SimpleNamespace(llm_router=native)
    templates = Registry.load("config/capabilities.yaml")
    registry = Registry({"remote": templates.providers["bensz_search"]})
    routed, _, _ = install(proxy, registry)
    result = await proxy.llm_router.asearch(search_tool_name="remote", query="q")
    assert result.results[0].snippet == "original"
    result = await routed.search(SearchRequest(query="q"), {"remote"})
    assert result.results[0].source_families == ["brave"]
    assert len(cluster.physical) == 2 and smart.health.available("brave")


async def test_list_queries_have_disjoint_subtree_budgets(cluster):
    cluster.add("b", {"brave": "brave", "serper": "serper", "searxng": "searxng"})
    token = current.set(receive_context([], "a"))
    try:
        result = await delegated_search(
            {"api_base": "https://b", "api_key": "remote-b"},
            {
                "query": ["comprehensive one", "comprehensive two", "comprehensive three"],
                "constraints": {"cost_budget_usd": 0.09},
            },
        )
    finally:
        current.reset(token)
    assert result.results
    posts = [(h, headers) for h, method, headers, _ in cluster.traffic if method == "POST"]
    assert len(posts) == 3 and len(cluster.physical) + len(posts) <= 10
    assert sum(json.loads(h["x-bensz-search-context"])["cost_budget_usd"] for _, h in posts) <= 0.09


async def test_remote_partial_success_remains_visible_at_parent(cluster):
    cluster.add("a", {"b": "bensz_search"})
    cluster.add("b", {"brave": "brave", "serper": "serper"})
    response = await cluster.query("a", {"query": "comprehensive research"}, WireContext(remaining_calls=2))
    assert response.json()["results"]
    assert response.json()["status"] == "partial_success"
    assert response.json()["execution"][0]["status"] == "partial_success"


async def test_remote_response_byte_limit_and_malformed_envelope(monkeypatch):
    for body in (b"x" * 512001, b"{}", b"not json"):
        calls = []

        async def send(client, request, body=body, calls=calls, **kwargs):
            calls.append(request)
            return httpx.Response(
                200,
                content=b"{}" if request.method == "GET" else body,
                headers={"x-bensz-search-federation": "1", "x-bensz-search-node": "remote"},
                request=request,
            )

        monkeypatch.setattr(httpx.AsyncClient, "send", send)
        with pytest.raises(ValueError):
            await delegated_search({"api_base": "https://remote", "api_key": "secret"}, {"query": "q"})
        assert len(calls) == 2


def test_configured_hop_limit_and_worker_identity(monkeypatch):
    from bensz_search.federation import instance_id

    monkeypatch.setenv("BENSZ_SEARCH_MAX_HOPS", "6")
    monkeypatch.setenv("BENSZ_SEARCH_SECRET", "a-test-only-secret-that-is-shared-across-workers")
    assert receive_context([], "a").max_hops == 6
    assert instance_id() == instance_id() and "secret" not in instance_id()
    monkeypatch.setenv("BENSZ_SEARCH_INSTANCE_ID", "cluster-node")
    assert instance_id() == "cluster-node"


def test_missing_remote_sources_remain_unknown_instead_of_inventing_a_leaf():
    from bensz_search.federated_search import normalize
    from bensz_search.protocol_models import ProtocolResult

    item = ProtocolResult(
        result_id="r",
        title="Doc",
        url="https://example.org/doc",
        canonical_identity="example.org/doc",
        aliases=[],
        snippet="",
        snippet_kind="link_only",
        sources=[],
        fusion_score=0,
    )
    rows = normalize(SearchEnvelope(request_id="r", status="success", results=[item]), "remote")
    fused, trace = fuse({"r": rows}, {}, {}, "rrf", 10)
    assert trace[0]["family_contributions"].keys() == {"bensz_search_unknown"}
    assert fused[0].upstream_sources == [
        {
            "source_family": "bensz_search_unknown",
            "snippet_kind": "link_only",
            "date": None,
            "instance_path": ["remote"],
        }
    ]
