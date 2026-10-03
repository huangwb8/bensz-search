"""Offline complete loops for each family; these are not live model claims."""

import copy
import json

import httpx
import pytest

from bensz_search.client import SearchClient, ToolSession
from bensz_search.model_adapters import (
    CodexRuntimeAdapter,
    ModelAdapter,
    assemble_stream,
    dispatch_structured,
    run_tool_loop,
)
from bensz_search.model_transport import HttpModel


def wire(family, name, arguments, call_id="c"):
    if family == "responses":
        return {
            "output": [
                {"type": "reasoning", "id": "reason", "encrypted_content": "context"},
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            ]
        }
    if family == "anthropic":
        return {
            "content": [
                {"type": "thinking", "thinking": "context", "signature": "signed"},
                {"type": "tool_use", "id": call_id, "name": name, "input": arguments},
            ]
        }
    if family == "gemini":
        return {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {"id": call_id, "name": name, "args": arguments},
                                "thoughtSignature": "signed",
                            }
                        ],
                    }
                }
            ]
        }
    message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": "context",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments if family == "ollama" else json.dumps(arguments),
                },
            }
        ],
    }
    return {"message": message} if family == "ollama" else {"choices": [{"message": message}]}


def final(family):
    if family == "responses":
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Answer"}]}]}
    if family == "anthropic":
        return {"content": [{"type": "text", "text": "Answer"}]}
    if family == "gemini":
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": "Answer"}]}}]}
    message = {"role": "assistant", "content": "Answer"}
    return {"message": message} if family == "ollama" else {"choices": [{"message": message}]}


@pytest.fixture
def search_transport():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "protocol_version": "1.0",
                    "registry_revision": "rev",
                    "cache_ttl_seconds": 30,
                    "tools": [],
                },
            )
        data = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "protocol_version": "1.0",
                "status": "success",
                "estimated_cost_usd": data["constraints"]["cost_budget_usd"],
                "execution": [{"call_id": "p", "status": "success"}],
                "results": [],
            },
        )

    return httpx.MockTransport(handle), requests


@pytest.mark.parametrize("family", ["responses", "chat", "anthropic", "gemini", "ollama"])
async def test_discover_plan_execute_answer_and_preserve_context(family, search_transport):
    transport, requests = search_transport
    adapter, payloads = ModelAdapter(family), []
    async with SearchClient("https://search.example", "tenant-key", transport=transport) as client:
        session = ToolSession(client)

        async def generate(payload):
            payloads.append(copy.deepcopy(payload))
            if len(payloads) == 1:
                return wire(family, "bensz_search_capabilities", {})
            if len(payloads) == 2:
                assert "rev" in json.dumps(payload)
                return wire(
                    family,
                    "bensz_search",
                    {
                        "mode": "planned",
                        "registry_revision": "rev",
                        "calls": [{"call_id": "p", "tool_id": "fixture", "query": "中文 query"}],
                    },
                )
            return final(family)

        result = await run_tool_loop(generate, adapter, session, "Find papers")
        assert result == final(family)
        assert len(requests) == 2 and len(payloads) == 3
        assert json.loads(requests[-1].content)["calls"][0]["query"] == "中文 query"
        assert "tenant-key" not in json.dumps(payloads)
        assert (
            "encrypted_content"
            if family == "responses"
            else "signature"
            if family == "anthropic"
            else "thoughtSignature"
            if family == "gemini"
            else "reasoning_content"
        ) in json.dumps(payloads[-1])


async def test_session_parallel_admission_budget_missing_capabilities_no_network_and_bad_json(
    search_transport,
):
    import asyncio

    transport, requests = search_transport
    async with SearchClient("https://search.example", "key", transport=transport) as client:
        session = ToolSession(client, budget_usd=0.02)
        error = await session.dispatch(
            "bensz_search", {"mode": "planned", "calls": [{"call_id": "a", "tool_id": "x", "query": "q"}]}
        )
        assert error["error"]["code"] == "capabilities_required" and not requests
        assert (await session.dispatch("bensz_search", '{"query":'))["error"]["code"] == "invalid_plan"
        results = await asyncio.gather(*(session.dispatch("bensz_search", {"query": "q"}) for _ in range(3)))
        assert sum(r.get("status") == "success" for r in results) == 1
        assert len(requests) == 1
        forbidden = ToolSession(client, allow_network=False)
        assert (await forbidden.dispatch("bensz_search_capabilities", {}))["error"][
            "code"
        ] == "network_forbidden"
        assert len(requests) == 1


async def test_per_key_cache_isolation_and_stale_invalidation():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200, json={"protocol_version": "1.0", "registry_revision": "r", "cache_ttl_seconds": 30}
            )
        return httpx.Response(
            409, json={"protocol_version": "1.0", "status": "failed", "error": {"code": "stale_capabilities"}}
        )

    async with SearchClient("https://search.example", "key1", transport=httpx.MockTransport(handle)) as first:
        async with SearchClient(
            "https://search.example", "key2", transport=httpx.MockTransport(handle)
        ) as second:
            await first.capabilities()
            await first.capabilities()
            await second.capabilities()
            await first.search({"query": "q"})
            await first.capabilities()
    assert len(requests) == 4
    assert requests[0].headers["authorization"] != requests[1].headers["authorization"]


async def test_timeout_never_replays_unknown_outcome():
    count = 0

    def handle(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("private endpoint", request=request)

    async with SearchClient("https://search.example", "key", transport=httpx.MockTransport(handle)) as client:
        session = ToolSession(client)
        assert (await session.auto_context("q"))["search"]["error"]["code"] == "outcome_unknown"
        assert (await session.auto_context("q"))["search"]["error"]["code"] == "limit_reached"
    assert count == 1


async def events(*values):
    for value in values:
        yield value


async def test_streamed_chat_parallel_argument_assembly_and_incomplete_rejection():
    result = await assemble_stream(
        "chat",
        events(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 1,
                                    "id": "b",
                                    "function": {"name": "bensz_search", "arguments": '{"query":'},
                                },
                                {
                                    "index": 0,
                                    "id": "a",
                                    "function": {"name": "bensz_search_capabilities", "arguments": "{"},
                                },
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "kept",
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": "}"}},
                                {"index": 1, "function": {"arguments": '"q"}'}},
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ),
    )
    calls = ModelAdapter("chat").calls(result)
    assert [c.call_id for c in calls] == ["a", "b"]
    assert json.loads(calls[1].arguments) == {"query": "q"}
    with pytest.raises(ValueError):
        await assemble_stream("chat", events({"choices": [{"delta": {"content": "unfinished"}}]}))


async def test_anthropic_gemini_responses_streams_retain_signatures():
    claude = await assemble_stream(
        "anthropic",
        events(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "kept"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig"},
            },
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "a", "name": "bensz_search", "input": {}},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"query":"q"}'},
            },
            {"type": "message_stop"},
        ),
    )
    assert claude["content"][0]["signature"] == "sig"
    assert ModelAdapter("anthropic").calls(claude)[0].arguments == {"query": "q"}
    gemini = wire("gemini", "bensz_search_capabilities", {})
    gemini["candidates"][0]["finishReason"] = "STOP"
    assert "thoughtSignature" in json.dumps(await assemble_stream("gemini", events(gemini)))
    response = wire("responses", "bensz_search_capabilities", {})
    assert (
        await assemble_stream("responses", events({"type": "response.completed", "response": response}))
        == response
    )


async def test_loop_limit_json_fallback_and_codex_capability_gate(search_transport):
    transport, _ = search_transport
    async with SearchClient("https://search.example", "key", transport=transport) as client:
        session = ToolSession(client)

        async def generate(payload):
            return wire("chat", "bensz_search_capabilities", {})

        assert (await run_tool_loop(generate, ModelAdapter("chat"), session, "q", max_turns=2))["error"][
            "code"
        ] == "limit_reached"
        result = await dispatch_structured(session, '{"tool":"bensz_search","arguments":{"query":"q"}}')
        assert result["integration_mode"] == "structured_output"
        assert not (await CodexRuntimeAdapter.handle(session, "item/tool/call", {}))["success"]
        result = await CodexRuntimeAdapter.handle(
            session,
            "item/tool/call",
            {"tool": "bensz_search_capabilities", "arguments": {}},
            dynamic_tools_enabled=True,
        )
        assert result["success"]


@pytest.mark.parametrize(
    "family,path",
    [
        ("responses", "responses"),
        ("chat", "chat/completions"),
        ("anthropic", "messages"),
        ("gemini", "models/example:generateContent"),
        ("ollama", "api/chat"),
    ],
)
async def test_optional_http_model_paths_headers_and_payload(family, path):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=final(family))

    async with HttpModel(
        "https://model.example/v1/", "model-key", "example", family, transport=httpx.MockTransport(handle)
    ) as model:
        result = await model.generate(ModelAdapter(family).request([]))
    assert result == final(family)
    assert seen[0].url.path == "/v1/" + path
    if family == "anthropic":
        assert seen[0].headers["x-api-key"] == "model-key"
    elif family == "gemini":
        assert seen[0].headers["x-goog-api-key"] == "model-key"


async def test_ollama_stream_and_model_output_truncation():
    response = wire("ollama", "bensz_search_capabilities", {})
    assert (
        ModelAdapter("ollama")
        .calls(await assemble_stream("ollama", events({**response, "done": True})))[0]
        .arguments
        == {}
    )
    with pytest.raises(ValueError):
        await assemble_stream("chat", events({"choices": [{"delta": {}, "finish_reason": "length"}]}))
    with pytest.raises(ValueError):
        await assemble_stream("gemini", events({"candidates": [{"finishReason": "MAX_TOKENS"}]}))


@pytest.mark.parametrize(
    "url", ["https://dashscope.aliyuncs.com/compatible-mode/v1", "https://api.deepseek.com/v1"]
)
async def test_chinese_channel_wire_loops_with_mock_models(url, search_transport):
    transport, requests = search_transport
    models = []

    def handle(request):
        models.append(json.loads(request.content))
        index = len(models)
        if index == 1:
            return httpx.Response(200, json=wire("chat", "bensz_search_capabilities", {}))
        if index == 2:
            return httpx.Response(200, json=wire("chat", "bensz_search", {"query": "中文检索"}))
        return httpx.Response(200, json=final("chat"))

    async with SearchClient("https://search.example", "key", transport=transport) as client:
        async with HttpModel(
            url, "model-key", "fixture-model", "chat", transport=httpx.MockTransport(handle)
        ) as model:
            result = await run_tool_loop(
                model.generate, ModelAdapter("chat"), ToolSession(client), "中文问题"
            )
    assert result == final("chat") and len(models) == 3 and len(requests) == 2


def test_gemini_schema_uses_supported_subset():
    schema = ModelAdapter("gemini").tools()
    serialized = json.dumps(schema)
    assert (
        '"pattern"' not in serialized
        and '"$ref"' not in serialized
        and '"additionalProperties"' not in serialized
    )
