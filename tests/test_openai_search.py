"""OpenAI sources, real LiteLLM Responses protocol, and routing boundaries."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import litellm
import pytest
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from bensz_search.filters import filter_results
from bensz_search.integration import install
from bensz_search.models import SearchRequest, SearchTask
from bensz_search.openai_search import normalize, search
from bensz_search.registry import Registry
from bensz_search.router import failure_category


def web_response():
    text = "Python's documentation explains the language. [source]"
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 1790982000,
        "model": "gpt-4.1-mini",
        "status": "completed",
        "error": None,
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_fixture",
                "status": "completed",
                "action": {
                    "type": "search",
                    "query": "Python docs",
                    "sources": [
                        {"type": "url", "url": "https://docs.python.org/3/?utm_source=web"},
                        {"type": "url", "url": "https://www.python.org/", "title": "Python"},
                        {"type": "url", "url": "https://excluded.example/doc"},
                        {"type": "url", "url": "javascript:alert(1)"},
                        {"type": "url", "url": "https://example.org:invalid/doc"},
                    ],
                },
            },
            {
                "type": "message",
                "id": "msg_fixture",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://docs.python.org/3/",
                                "title": "Python documentation",
                                "start_index": text.index("[source]"),
                                "end_index": len(text),
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
    }


def test_sources_are_structured_deduplicated_and_not_page_extracts():
    rows = normalize(web_response())
    assert len(rows) == 3
    assert rows[0].title == "Python documentation"
    assert rows[0].snippet_kind == "generated_summary"
    assert rows[0].snippet.startswith("Python's documentation")
    assert rows[1].snippet == "" and rows[1].snippet_kind == "source_only"
    assert all(row.date is None and row.last_updated is None for row in rows)
    assert not filter_results(rows, SearchTask(query="q", freshness="week"), [])


@pytest.mark.parametrize("change", ["incomplete", "failed", "missing_search", "failed_search"])
def test_incomplete_or_unsearched_responses_cannot_look_successful(change):
    response = web_response()
    if change in {"incomplete", "failed"}:
        response["status"] = change
    elif change == "missing_search":
        response["output"].pop(0)
    else:
        response["output"][0]["status"] = "failed"
    with pytest.raises(ValueError):
        normalize(response)


def test_text_urls_are_not_sources_and_malformed_output_is_invalid():
    response = web_response()
    response["output"][0]["action"]["sources"] = []
    response["output"][1]["content"][0].update(text="See https://invented.example/doc", annotations=[])
    assert normalize(response) == []
    response["output"] = [None]
    with pytest.raises(ValueError):
        normalize(response)


async def test_responses_http_protocol_and_server_owned_configuration(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=web_response())

    handler = AsyncHTTPHandler()
    await handler.client.aclose()
    original = litellm.aresponses
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        handler.client = client

        async def responses(**kwargs):
            return await original(client=handler, **kwargs)

        monkeypatch.setattr(litellm, "aresponses", responses)
        monkeypatch.setenv("TEST_OPENAI_SEARCH_KEY", "server-test-key")
        result = await search(
            {
                "api_key": "os.environ/TEST_OPENAI_SEARCH_KEY",
                "api_base": "https://configured.example/v1",
                "search_model": "gpt-4.1-mini",
                "search_context_size": "low",
                "max_output_tokens": 1024,
            },
            {
                "query": "Python docs",
                "max_results": 2,
                "search_domain_filter": ["python.org", "-excluded.example"],
                "country": "gb",
                "api_base": "https://untrusted.example",
                "api_key": "client-key",
                "model": "another-provider/model",
                "tools": [],
                "max_output_tokens": 800000,
            },
        )
    assert len(requests) == 1 and len(result.results) == 2
    request = requests[0]
    assert str(request.url) == "https://configured.example/v1/responses"
    assert request.headers["authorization"] == "Bearer server-test-key"
    body = json.loads(request.content)
    assert body["model"] == "gpt-4.1-mini"
    assert body["tools"] == [
        {
            "type": "web_search",
            "search_context_size": "low",
            "filters": {"allowed_domains": ["python.org"], "blocked_domains": ["excluded.example"]},
            "user_location": {"type": "approximate", "country": "GB"},
        }
    ]
    assert body["tool_choice"] == "required"
    assert body["include"] == ["web_search_call.action.sources"]
    assert body["max_output_tokens"] == 1024 and body["max_tool_calls"] == 1
    assert body["store"] is False


async def test_query_list_and_domain_filter_apply_to_sources(monkeypatch):
    calls = []

    async def responses(**kwargs):
        calls.append(kwargs)
        return deepcopy(web_response())

    monkeypatch.setattr(litellm, "aresponses", responses)
    result = await search(
        {"api_key": "test-key"},
        {"query": ["Python docs", "Python language"], "search_domain_filter": ["docs.python.org"]},
    )
    assert [call["input"] for call in calls] == ["Python docs", "Python language"]
    assert len(result.results) == 1
    assert all(call["max_retries"] == 0 for call in calls)


@pytest.mark.parametrize("status, category", [(401, "auth"), (429, "rate_limit"), (500, "unavailable")])
async def test_responses_http_errors_do_not_retry(monkeypatch, status, category):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status, json={"error": {"message": "Fixture failure", "type": "api_error", "code": None}}
        )

    handler = AsyncHTTPHandler()
    await handler.client.aclose()
    original = litellm.aresponses
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        handler.client = client

        async def responses(**kwargs):
            return await original(client=handler, **kwargs)

        monkeypatch.setattr(litellm, "aresponses", responses)
        with pytest.raises(Exception) as error:
            await search({"api_key": "test-key"}, {"query": "q"})
    assert failure_category(error.value) == category
    assert len(requests) == 1


async def test_timeout_cancels_provider_and_missing_key_does_not_call(monkeypatch):
    cancelled = []

    async def responses(**kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(litellm, "aresponses", responses)
    with pytest.raises(ValueError, match="API key"):
        await search({}, {"query": "q"})
    assert not cancelled
    with pytest.raises(TimeoutError):
        await search({"api_key": "test-key", "timeout": 0.01}, {"query": ["q", "q2"]})
    assert cancelled == [True]


@pytest.mark.parametrize("status, category", [(401, "auth"), (429, "rate_limit"), (500, "unavailable")])
async def test_openai_errors_classified_and_auto_falls_back(monkeypatch, status, category):
    calls = []

    async def responses(**kwargs):
        calls.append("openai")
        error = RuntimeError("provider failure")
        error.status_code = status
        assert failure_category(error) == category
        raise error

    async def native(**kwargs):
        calls.append(kwargs["search_tool_name"])
        return SearchResponse(
            results=[SearchResult(title="Fallback", url="https://example.org/doc", snippet="")]
        )

    monkeypatch.setattr(litellm, "aresponses", responses)
    registry = Registry.load("config/capabilities.yaml")
    registry.providers["openai"] = registry.providers["openai"].model_copy(
        update={"cost_class": "low", "latency_class": "low", "capabilities": {"general": 1, "keyword": 1}}
    )
    router = SimpleNamespace(
        asearch=native,
        search_tools=[
            {
                "search_tool_name": "openai",
                "litellm_params": {"search_provider": "openai", "api_key": "test-key"},
            },
        ],
    )
    smart, _, _ = install(SimpleNamespace(llm_router=router), registry)
    result = await smart.search(
        SearchRequest(query="capital of France", debug=True, constraints={"cost_budget_usd": 0.03}),
        {"openai", "serper"},
    )
    assert calls == ["openai", "serper"]
    assert result.debug["attempts"][0]["status"] == category
    assert result.debug["attempts"][1]["fallback"]
    calls.clear()
    await smart.search(SearchRequest(query="q"), {"serper"})
    assert calls == ["serper"]
