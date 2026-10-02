from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult
from litellm.proxy._types import LiteLLM_TeamTable, UserAPIKeyAuth

from bensz_search.integration import RequestContext, authorized_tools, install, request_context
from bensz_search.models import SearchRequest
from bensz_search.registry import Registry


def auth(tools):
    return UserAPIKeyAuth(object_permission={"object_permission_id": "fixture", "search_tools": tools})


async def test_key_and_team_permissions_intersect():
    team = LiteLLM_TeamTable(
        team_id="fixture",
        object_permission={"object_permission_id": "fixture-team", "search_tools": ["auto", "serper"]},
    )
    allowed = await authorized_tools({"exa", "serper", "brave"}, auth(["auto", "exa", "serper"]), team)
    assert allowed == {"serper"}
    assert await authorized_tools({"exa"}, auth(["auto"]), None) == set()
    assert await authorized_tools({"exa"}, auth([]), None) == {"exa"}


async def test_explicit_pass_through_and_auto_fail_closed():
    called = []

    async def original(**kwargs):
        called.append(kwargs)
        return SearchResponse(results=[])

    proxy = SimpleNamespace(llm_router=SimpleNamespace(asearch=original))
    install(proxy, Registry.load("config/capabilities.yaml"))
    await proxy.llm_router.asearch(query="q", search_tool_name="exa", extra_provider_option="yes")
    assert called == [{"query": "q", "search_tool_name": "exa", "extra_provider_option": "yes"}]
    with pytest.raises(HTTPException) as error:
        await proxy.llm_router.asearch(query="q", search_tool_name="auto")
    assert error.value.status_code == 403


async def test_auto_fallback_cannot_escape_allowlist():
    called = []

    async def original(**kwargs):
        called.append(kwargs["search_tool_name"])
        return SearchResponse(
            results=[SearchResult(title="fixture", url="https://example.org/a", snippet="fixture")]
        )

    proxy = SimpleNamespace(llm_router=SimpleNamespace(asearch=original))
    install(proxy, Registry.load("config/capabilities.yaml"))
    token = request_context.set(RequestContext(SearchRequest(query="ctDNA clinical trial"), {"serper"}, True))
    try:
        await proxy.llm_router.asearch(query="q", search_tool_name="auto")
    finally:
        request_context.reset(token)
    assert called == ["serper"]
