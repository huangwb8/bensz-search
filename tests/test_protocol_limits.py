import asyncio
from types import SimpleNamespace

import httpx
import pytest
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from bensz_search.client import SearchClient, ToolSession
from bensz_search.executor import failure_category
from bensz_search.protocol import ProtocolLimits, search
from bensz_search.protocol_http import execute_for_user
from bensz_search.protocol_models import ProtocolSearch
from bensz_search.registry import Registry
from bensz_search.router import SmartRouter


async def test_http_disconnect_cancels_provider_and_releases_tenant(monkeypatch):
    stopped = []

    async def call(**kwargs):
        try:
            await asyncio.sleep(30)
        finally:
            stopped.append(True)

    smart = SmartRouter(Registry.load("config/capabilities.yaml"), call)
    state = SimpleNamespace(smart_search=smart)
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    async def disconnect():
        return True

    async def permissions(request, user):
        return smart, {"searxng"}

    request.is_disconnected = disconnect
    monkeypatch.setattr("bensz_search.protocol_http.permission_snapshot", permissions)
    with pytest.raises(asyncio.CancelledError):
        await execute_for_user(
            request,
            SimpleNamespace(user_id="u", api_key="k"),
            ProtocolSearch(query="q"),
            cancel_on_disconnect=True,
        )
    assert stopped == [True]
    assert state.protocol_limiter.states["u"][2] == 0


async def test_response_bytes_are_bounded_after_truncation_warning():
    async def call(**kwargs):
        return SearchResponse(
            results=[
                SearchResult(title="汉字" * 1000, url=f"https://example.org/{i}", snippet="汉字" * 10000)
                for i in range(20)
            ]
        )

    router = SmartRouter(Registry.load("config/capabilities.yaml"), call)
    limits = ProtocolLimits()
    limits.max_response_bytes = 32768
    result = await search(
        router,
        ProtocolSearch(
            mode="planned",
            max_results=20,
            calls=[{"call_id": "a", "tool_id": "searxng", "query": "q", "max_results": 20}],
        ),
        {"searxng"},
        limits,
    )
    assert result.truncated
    assert len(result.model_dump_json().encode()) <= limits.max_response_bytes
    assert all(r.truncated for r in result.results)


async def test_malformed_search_response_exhausts_task_admission():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content="not JSON")

    async with SearchClient("https://search.example", "key", transport=httpx.MockTransport(handle)) as client:
        session = ToolSession(client)
        assert (await session.auto_context("q"))["search"]["error"]["code"] == "transport_error"
        assert (await session.auto_context("q"))["search"]["error"]["code"] == "limit_reached"
    assert len(calls) == 1


def test_network_failure_separate_from_provider_unavailable():
    assert failure_category(httpx.ConnectError("private address")) == "network"
    assert failure_category(RuntimeError("provider failed")) == "unavailable"
