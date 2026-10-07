"""The only version-sensitive adapter: retain LiteLLM HTTP, auth and provider execution."""

import json
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger
from pydantic import ValidationError

from .executor import failure_category
from .federation import FederationMiddleware
from .models import SearchRequest
from .openai_search import provider_call
from .router import SearchFailed, SmartRouter
from .telemetry import usage_key


@dataclass
class RequestContext:
    request: SearchRequest
    allowed: set[str] = field(default_factory=set)
    authorized: bool = False


request_context: ContextVar[RequestContext | None] = ContextVar("bensz_search_request", default=None)


class RouterLease:
    """Retire only this router's callbacks after its in-flight calls finish."""

    def __init__(self, router, call):
        self.router, self.call = router, call
        self.active = 0
        self.retired = False
        self.lock = threading.RLock()

    async def __call__(self, **kwargs):
        with self.lock:
            self.active += 1
        try:
            return await self.call(**kwargs)
        finally:
            with self.lock:
                self.active -= 1
                if self.retired and not self.active:
                    self.router.discard()

    def retire(self):
        with self.lock:
            self.retired = True
            if not self.active:
                self.router.discard()


class SearchInputMiddleware:
    """Set the default tool before native auth, and bind smart requests to this ASGI task."""

    def __init__(self, app, default_tool="auto"):
        self.app, self.default_tool = FederationMiddleware(app), default_tool

    async def __call__(self, scope, receive, send):
        token = usage_key.set(None)
        try:
            return await self.handle(scope, receive, send)
        finally:
            usage_key.reset(token)

    async def handle(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        is_search = path in {"/search", "/v1/search"} or any(
            path.startswith(prefix) and "/" not in path[len(prefix) :]
            for prefix in ("/search/", "/v1/search/")
        )
        is_admin = path.startswith("/admin")
        is_console = is_admin or path in {"/app", "/app/"}
        is_protocol = path.startswith("/bensz-search/")
        error_start, error_body = None, bytearray()

        async def secure_send(message):
            nonlocal error_start
            if path.startswith("/bensz-search/v1/"):
                if message["type"] == "http.response.start" and message["status"] >= 400:
                    error_start = message
                    return
                if error_start and message["type"] == "http.response.body":
                    error_body.extend(message.get("body", b""))
                    if message.get("more_body", False):
                        return
                    from .protocol import ProtocolFailure

                    try:
                        data = json.loads(error_body)
                    except ValueError:
                        data = {}
                    if not isinstance(data, dict) or "protocol_version" not in data:
                        code = {
                            401: "authentication_error",
                            403: "permission_denied",
                            413: "request_too_large",
                            422: "invalid_plan",
                            429: "rate_limit",
                        }.get(error_start["status"], "request_failed")
                        data = (
                            ProtocolFailure(
                                code, "Search request rejected", status_code=error_start["status"]
                            )
                            .envelope()
                            .model_dump()
                        )
                    payload = json.dumps(data).encode()
                    headers = [
                        (k, v)
                        for k, v in error_start.get("headers", [])
                        if k not in {b"content-length", b"content-encoding", b"content-type"}
                    ]
                    await send(
                        {
                            **error_start,
                            "headers": headers
                            + [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(payload)).encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": payload})
                    return
            if message["type"] == "http.response.start" and is_console:
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

        if scope.get("method") not in {"POST", "PUT", "PATCH"} or not (is_search or is_admin or is_protocol):
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
            if path == "/bensz-search/v1/search":
                from .protocol import ProtocolFailure
                from .protocol_models import ProtocolSearch

                try:
                    ProtocolSearch.model_validate_json(bytes(body))
                except ValidationError as error:
                    field = ".".join(str(x) for x in error.errors()[0]["loc"])
                    data = (
                        ProtocolFailure("invalid_plan", "Invalid search request", field)
                        .envelope()
                        .model_dump()
                    )
                    return await self.error(secure_send, 422, data=data)
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
            if any(key.startswith("_federation_") for key in data) or any(
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
    async def error(send, status, detail=None, data=None):
        body = json.dumps(data if data is not None else {"detail": detail}).encode()
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
    physical = RouterLease(proxy.llm_router, provider_call(proxy.llm_router, original))
    proxy.llm_router._bensz_lease = physical
    smart = SmartRouter(registry, physical)

    async def routed_search(**kwargs):
        if kwargs.get("search_tool_name", kwargs.get("model")) != "auto":
            name = kwargs.get("search_tool_name", kwargs.get("model"))
            # Preserve native named-provider semantics while observing the actual call.
            started, request_id = time.monotonic(), str(uuid4())
            attempt = {
                "provider": name,
                "status": "unavailable",
                "fallback": False,
                "latency_ms": 0,
                "estimated_cost_usd": 0,
                "result_count": 0,
            }
            capability = smart.registry.providers.get(name)
            if capability:
                attempt["estimated_cost_usd"] = capability.estimated_cost_usd * (
                    len(kwargs.get("query")) if isinstance(kwargs.get("query"), list) else 1
                )
            try:
                result = await physical(**kwargs)
                attempt.update(
                    status="success" if result.results else "empty", result_count=len(result.results)
                )
                if result.results:
                    smart.health.success(name, (time.monotonic() - started) * 1000)
                else:
                    smart.health.failure(name, "empty")
                return result
            except Exception as error:
                category = failure_category(error)
                attempt["status"] = category
                smart.health.failure(name, category)
                raise
            finally:
                attempt["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
                smart.telemetry.record_execution(
                    request_id,
                    "explicit",
                    [attempt],
                    attempt["result_count"],
                    attempt["estimated_cost_usd"],
                    attempt["latency_ms"],
                    ["Explicit provider selection"],
                )
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
