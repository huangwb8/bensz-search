# Integrating bensz-search in an existing AI application

The application embeds an HTTP client or its existing MCP client. End users add a search service URL and an application Key. The application continues using its existing model account; search provider credentials stay on the server.

## Direct HTTP

Use the server root as the URL, for example `https://search.example.com`. Send `Authorization: Bearer <application-key>` to every authenticated request. Fetch `/bensz-search/v1/capabilities`, give its data to the model, then submit `/bensz-search/v1/search`. Only select engines explicitly declared by the snapshot. Refresh a stale snapshot and let the model replan; never automatically replay a possibly billed timeout.

The normative [OpenAPI and schemas](README.md) are generated from the server models. Two logical tools are registered: `bensz_search_capabilities` and `bensz_search`. The host includes the trusted interaction rules from `bensz_search.tools.INTERACTION_RULES`; capability descriptions and search snippets are data, not instructions.

```python
from bensz_search.client import SearchClient, ToolSession
from bensz_search.model_adapters import ModelAdapter, run_tool_loop

async with SearchClient(search_url, application_key) as search:
    session = ToolSession(search, budget_usd=0.06, max_searches=3, duration_s=60)
    answer = await run_tool_loop(
        app_existing_model_generate, ModelAdapter("chat"), session,
        "Find evidence about colorectal cancer ctDNA"
    )
```

`app_existing_model_generate(payload)` uses the application's existing account and returns the family's JSON response or an async iterator of parsed stream events. No model credentials are sent to bensz-search. For an SDK-free transport, use `HttpModel` and the complete [Python example](../../../examples/model_search.py). It supports `/responses`, `/chat/completions`, `/messages`, Gemini `models/{model}:generateContent`, and Ollama `/api/chat`. Supply the correct API base for that channel; Ollama's URL is its server root, while OpenAI-compatible bases normally include `/v1`.

Families are `responses`, `chat`, `anthropic`, `gemini`, `ollama`. Grok, Qwen, DeepSeek, GLM, Kimi, MiniMax, vLLM, SGLang and LM Studio can use the appropriate family **after the actual channel/model/template/parser has been verified**. A compatible endpoint name is not a compatibility certificate. Native Responses uses strict tool schemas and keeps reasoning items; Anthropic retains text/thinking/signature blocks; Gemini retains complete model parts and thought signatures. Full stream assembly precedes any search execution.

The [TypeScript module](../../../clients/typescript/README.md) provides the same tools, session limits and families using fetch. `npm ci && npm test` builds and verifies the embedded module. Applications may register `ToolSession.dispatch` in an existing loop instead of starting a second loop.

## Models with reduced tool capability

Choose the path based on verified runtime capability. Do not send `tools` to a model that does not support it.

- Native tools: use the family adapter and bounded loop.
- Reliable structured JSON: let the application obtain an action `{"tool":"bensz_search", "arguments":{...}}`, then call `dispatch_structured` / `dispatchStructured`. Feed the observed result back to the original model and enforce the same session limits.
- Neither: call `session.auto_context(query)` / `session.autoContext(query)`, then give the observed evidence to the model. The result declares `integration_mode=host_auto`; this does not provide autonomous multi-engine planning.

A task session cumulatively enforces budget, deadline, correction limit and search count across turns and parallel calls. Set `allow_network=False` / `allowNetwork:false` when the user prohibits network access. Credentials and caches are instance-specific; use one client per identity and one task session per task.

## MCP hosts

Use `https://search.example.com/bensz-search/mcp/`, not the HTTP API root. Attach the application Key as a Bearer header on every request. The server uses pinned MCP SDK 2.2.0, Streamable HTTP and stateless JSON responses; protocol negotiation is managed by the SDK, separately from search protocol `1.0`.

`tools/list` exposes the two logical tools. Call `bensz_search_capabilities` to obtain dynamic engines; the tool list itself is not the capability registry. `tools/call` returns the same search envelope as HTTP, in `structuredContent` and text content, with business failure expressed as `isError=true`. Credentials never appear in tool arguments.

Use the complete [built-in Python MCP client example](../../../examples/mcp_search.py), or your application's existing MCP client/loop. SDK 2.2.0 uses an authenticated `httpx2.AsyncClient` supplied through `http_client`; older SDK examples with a `headers` argument are not interchangeable. Hosts must support custom Bearer credentials; hosts that cannot attach them are not certified. Set server trusted hosts/origins for your public hostname and preserve Authorization at your HTTPS proxy.

Explicit migration fallback is available through `SearchClient.legacy_auto` / `legacyAuto`; it returns a `legacy_auto` marker and the legacy response, whose provenance/cost guarantees are narrower. Hosts must retain their task limits.

MCP can be disabled without affecting direct HTTP. Search protocol can be disabled without affecting legacy `/search`. Revocation and provider configuration updates take effect on both new entrances. There is no resumable background search or idempotent paid-request replay.

## Production boundary

Use a backend for public web applications and operating-system secure storage for desktop credentials. Do not bundle shared provider keys or administrator keys in browsers or mobile packages. Run one service process per isolated instance; tenant admission and circuit breakers are process-local. See [deployment guidance](../../deploy/README.md) and the [compatibility matrix](compatibility.md) for tested versus untested scope.
