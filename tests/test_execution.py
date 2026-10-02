import asyncio

import pytest
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from bensz_search.models import SearchRequest
from bensz_search.registry import Registry
from bensz_search.router import SearchFailed, SmartRouter


def response(url="https://example.com/result"):
    return SearchResponse(results=[SearchResult(title="A valid document", url=url, snippet="fixture")])


async def test_fallback_and_auth_no_retry():
    calls = []

    async def call(**kwargs):
        calls.append(kwargs["search_tool_name"])
        if len(calls) == 1:
            error = RuntimeError("private credential error")
            error.status_code = 401
            raise error
        return response()

    router = SmartRouter(Registry.load("config/capabilities.yaml"), call)
    result = await router.search(
        SearchRequest(query="capital of France", debug=True), {"brave", "serper", "searxng"}
    )
    assert len(result.results) == 1
    assert len(calls) == len(set(calls)) == 2
    assert result.debug["attempts"][0]["status"] == "auth"
    assert result.debug["attempts"][1]["fallback"]
    assert "private credential" not in str(result.debug)
    assert not router.health.available(calls[0])


async def test_parallel_timeout_returns_partial_and_cancels():
    cancelled = []

    async def call(**kwargs):
        if kwargs["search_tool_name"] == "exa":
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(True)
        return response()

    router = SmartRouter(Registry.load("config/capabilities.yaml"), call)
    result = await router.search(
        SearchRequest(query="ctDNA clinical trial", constraints={"latency_budget_ms": 100}, debug=True),
        {"exa", "serper"},
    )
    assert result.results
    assert cancelled
    assert result.debug["partial_success"]


async def test_cost_is_reserved_across_failed_attempts():
    calls = []

    async def call(**kwargs):
        calls.append(kwargs["search_tool_name"])
        return SearchResponse(results=[])

    router = SmartRouter(Registry.load("config/capabilities.yaml"), call)
    with pytest.raises(SearchFailed):
        await router.search(
            SearchRequest(query="capital", constraints={"cost_budget_usd": 0.002}), {"brave", "serper"}
        )
    assert calls == ["serper"]


async def test_no_duplicate_fallback_under_parallel_failures():
    calls = []

    async def call(**kwargs):
        calls.append(kwargs["search_tool_name"])
        await asyncio.sleep(0.001)
        return SearchResponse(results=[])

    router = SmartRouter(Registry.load("config/capabilities.yaml"), call)
    with pytest.raises(SearchFailed):
        await router.search(
            SearchRequest(query="comprehensive landscape", constraints={"cost": "high"}),
            set(router.registry.providers),
        )
    assert len(calls) == len(set(calls))


async def test_no_authorized_provider_no_network_call():
    async def call(**kwargs):
        pytest.fail("must not call unauthorized provider")

    router = SmartRouter(Registry.load("config/capabilities.yaml"), call)
    with pytest.raises(SearchFailed) as error:
        await router.search(SearchRequest(query="x"), set())
    assert error.value.status_code == 503


async def test_academic_uses_only_configured_scholarly_searxng_engines():
    called = []

    async def call(**kwargs):
        called.append(kwargs)
        return response()

    registry = Registry.load("config/capabilities.yaml")
    registry.providers["searxng"] = registry.providers["searxng"].model_copy(
        update={"intent_engines": {"academic": ["pubmed"], "coding": ["github"]}}
    )
    router = SmartRouter(registry, call)
    await router.search(SearchRequest(query="colorectal cancer ctDNA"), {"searxng"})
    assert called[0]["engines"] == "pubmed"


async def test_failed_branch_does_not_spend_other_primary_reservation():
    called = []

    async def call(**kwargs):
        name = kwargs["search_tool_name"]
        called.append(name)
        if name == "exa":
            return SearchResponse(results=[])
        return response()

    reg = Registry.load("config/capabilities.yaml")
    router = SmartRouter(reg, call)
    # .007 + .008 fills the primary budget; synchronous Exa failure must not steal Tavily's share.
    result = await router.search(
        SearchRequest(query="ctDNA", constraints={"cost_budget_usd": 0.015}, debug=True),
        {"exa", "tavily", "serper"},
    )
    assert "tavily" in called
    assert result.results
