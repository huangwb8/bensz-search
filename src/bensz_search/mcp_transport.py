"""SDK Streamable HTTP adapter; business logic and auth are shared with HTTP."""

import asyncio
import json
import os
from contextvars import ContextVar

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from litellm.proxy._types import ProxyException
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError

from .protocol import ProtocolFailure, capabilities
from .protocol_http import execute_for_user, permission_snapshot
from .protocol_models import ProtocolSearch
from .tools import INTERACTION_RULES, logical_tools

mcp_request = ContextVar("bensz_mcp_request", default=None)


def create_manager():
    async def list_tools(ctx, params):
        return types.ListToolsResult(
            tools=[
                types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"])
                for t in logical_tools()
            ]
        )

    async def call_tool(ctx, params):
        request = mcp_request.get()
        try:
            user = await authenticate(request)
            if params.name == "bensz_search_capabilities":
                if params.arguments:
                    raise ProtocolFailure("invalid_plan", "Capabilities accepts no parameters")
                smart, allowed = await permission_snapshot(request, user)
                data = capabilities(smart, allowed)
            elif params.name == "bensz_search":
                result = await execute_for_user(
                    request, user, ProtocolSearch.model_validate(params.arguments or {})
                )
                data = result.model_dump(mode="json")
            else:
                raise ProtocolFailure("unknown_tool", "Unknown logical tool")
        except ValidationError as error:
            location = ".".join(str(x) for x in error.errors()[0]["loc"])
            data = (
                ProtocolFailure("invalid_plan", "Invalid search arguments", location).envelope().model_dump()
            )
        except ProtocolFailure as error:
            data = error.envelope().model_dump()
        except (HTTPException, ProxyException):
            data = (
                ProtocolFailure("permission_denied", "Search authorization rejected", status_code=403)
                .envelope()
                .model_dump()
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(data))],
            structuredContent=data,
            isError=data.get("status") == "failed",
        )

    server = Server(
        "bensz-search",
        version="1.0",
        instructions=INTERACTION_RULES,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    # Origin-less server clients work by default. Browser hosts need explicit trusted
    # hosts/origins; no wildcard or credential-bearing CORS is enabled by this adapter.
    hosts = os.getenv("BENSZ_SEARCH_MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,[::1]:*,testserver").split(
        ","
    )
    origins = os.getenv("BENSZ_SEARCH_MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(
        ","
    )
    return StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        security_settings=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins),
        max_request_body_size=128000,
    )


async def authenticate(request):
    return await user_api_key_auth(
        request,
        api_key=request.headers.get("authorization", ""),
        azure_api_key_header=None,
        anthropic_api_key_header=None,
        google_ai_studio_api_key_header=None,
        azure_apim_header=None,
        custom_litellm_key_header=None,
    )


class MCPTransport:
    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)
        if os.getenv("BENSZ_SEARCH_MCP_ENABLED", "true").lower() != "true":
            return await JSONResponse({"error": "MCP disabled"}, status_code=503)(scope, receive, send)
        # Body is cached for gateway authentication and replayed exactly once to SDK.
        await request.body()
        try:
            user = await authenticate(request)
            await permission_snapshot(request, user)
        except Exception as error:
            status = int(getattr(error, "status_code", None) or getattr(error, "code", 401))
            if status not in {401, 403, 429, 503}:
                status = 401
            return await JSONResponse({"error": "Unauthorized search transport"}, status_code=status)(
                scope, receive, send
            )
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": request._body, "more_body": False}
            return await receive()

        token = mcp_request.set(request)
        task = asyncio.create_task(request.app.state.search_mcp.handle_request(scope, replay, send))

        async def watch_disconnect():
            while not task.done():
                await asyncio.sleep(0.05)
                # JSON transport consumes exactly one replayed body before waiting
                # for its tool result. Detect socket closure while it is waiting.
                if delivered and await request.is_disconnected():
                    task.cancel()
                    return

        watcher = asyncio.create_task(watch_disconnect()) if scope["method"] == "POST" else None
        try:
            await task
        finally:
            for job in (task, watcher):
                if job and not job.done():
                    job.cancel()
            await asyncio.gather(*(j for j in (task, watcher) if j), return_exceptions=True)
            mcp_request.reset(token)
