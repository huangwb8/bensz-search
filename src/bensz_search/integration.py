"""The only version-sensitive adapter: retain LiteLLM HTTP, auth and provider execution."""

import json
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger
from pydantic import ValidationError

from .models import SearchRequest
from .router import SearchFailed, SmartRouter


@dataclass
class RequestContext:
    request: SearchRequest
    allowed: set[str] = field(default_factory=set)
    authorized: bool = False


request_context: ContextVar[RequestContext | None] = ContextVar("bensz_search_request", default=None)


class SearchInputMiddleware:
    """Set the default tool before native auth, and bind smart requests to this ASGI task."""

    def __init__(self, app, default_tool="auto"):
        self.app, self.default_tool = app, default_tool

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        is_search = path in {"/search", "/v1/search"} or any(
            path.startswith(prefix) and "/" not in path[len(prefix) :]
            for prefix in ("/search/", "/v1/search/")
        )
        is_admin = path.startswith("/admin")

        async def secure_send(message):
            if message["type"] == "http.response.start" and is_admin:
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                        ),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        if scope.get("method") not in {"POST", "PUT", "PATCH"} or not (is_search or is_admin):
            return await self.app(scope, receive, secure_send)
        try:
            length = int(dict(scope.get("headers", [])).get(b"content-length", b"0"))
        except ValueError:
            return await self.error(secure_send, 400, "invalid content length")
        if length > 128000:
            return await self.error(secure_send, 413, "request too large")
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 128000:
                return await self.error(secure_send, 413, "request too large")
            if not message.get("more_body", False):
                break
        if not is_search:
            delivered = False

            async def replay_admin():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay_admin, secure_send)
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("search body must be an object")
            if any(
                key in data
                for key in (
                    "api_key",
                    "api_base",
                    "headers",
                    "extra_headers",
                    "search_provider",
                    "custom_llm_provider",
                    "metadata",
                    "litellm_metadata",
                    "proxy_server_request",
                )
            ):
                return await self.error(
                    secure_send, 422, "credentials and internal request parameters cannot be overridden"
                )
            tool = (
                path.rsplit("/", 1)[-1]
                if path not in {"/search", "/v1/search"}
                else data.get("search_tool_name") or self.default_tool
            )
            data["search_tool_name"] = tool
            smart = SearchRequest.model_validate(data) if tool == "auto" else None
        except (ValueError, ValidationError):
            return await self.error(
                secure_send, 422, "invalid search request; see the bensz-search request schema"
            )
        payload = json.dumps(data).encode()
        headers = [(key, value) for key, value in scope.get("headers", []) if key != b"content-length"]
        scope = {**scope, "headers": headers + [(b"content-length", str(len(payload)).encode())]}
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        token = request_context.set(RequestContext(smart) if smart else None)
        try:
            await self.app(scope, replay, secure_send)
        finally:
            request_context.reset(token)

    @staticmethod
    async def error(send, status, detail):
        body = json.dumps({"detail": detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


async def authorized_tools(names, user, team=None):
    from litellm.proxy._types import ProxyException
    from litellm.proxy.auth.auth_checks import can_key_call_search_tool, can_team_call_search_tool

    allowed = set()
    for name in names:
        try:
            await can_key_call_search_tool(search_tool_name=name, valid_token=user)
            await can_team_call_search_tool(search_tool_name=name, team_object=team)
        except ProxyException as error:
            if str(error.code) != "403":
                raise
        else:
            allowed.add(name)
    return allowed


class AuthorizationCallback(CustomLogger):
    def __init__(self, registry, proxy):
        super().__init__()
        self.registry, self.proxy = registry, proxy

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        ctx = request_context.get()
        if ctx is None or data.get("search_tool_name") != "auto":
            return data
        if call_type not in {"search", "asearch"}:
            return data
        # Reflect any query transformation by earlier gateway guardrails.
        values = ctx.request.model_dump()
        values["query"] = data["query"]
        ctx.request = SearchRequest.model_validate(values)
        from litellm.proxy.auth.auth_checks import get_team_object

        team = None
        if user_api_key_dict.team_id:
            team = await get_team_object(
                team_id=user_api_key_dict.team_id,
                prisma_client=self.proxy.prisma_client,
                user_api_key_cache=self.proxy.user_api_key_cache,
                parent_otel_span=user_api_key_dict.parent_otel_span,
                proxy_logging_obj=self.proxy.proxy_logging_obj,
            )
        names = self.registry.configured(self.proxy.llm_router.search_tools)
        ctx.allowed = await authorized_tools(names, user_api_key_dict, team)
        ctx.authorized = True
        return data


def install(proxy, registry):
    """Wrap one initialized Router instance; caller restores it at shutdown."""
    if proxy.llm_router is None:
        raise RuntimeError("LiteLLM must configure at least one search tool")
    original = proxy.llm_router.asearch
    smart = SmartRouter(registry, original)

    async def routed_search(**kwargs):
        if kwargs.get("search_tool_name", kwargs.get("model")) != "auto":
            return await original(**kwargs)
        ctx = request_context.get()
        if ctx is None or not ctx.authorized:
            raise HTTPException(403, "Smart search requires the authenticated gateway context")
        context = {key: kwargs[key] for key in ("metadata", "litellm_metadata", "user") if key in kwargs}
        try:
            values = ctx.request.model_dump()
            values["query"] = kwargs["query"]
            request = SearchRequest.model_validate(values)
            return await smart.search(request, ctx.allowed, context)
        except SearchFailed as error:
            raise HTTPException(error.status_code, str(error)) from error

    proxy.llm_router.asearch = routed_search
    return smart, original, AuthorizationCallback(registry, proxy)
