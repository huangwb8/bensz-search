"""Bounded, credential-free context for cooperating search instances."""

import hashlib
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from pydantic import Field

from .models import StrictModel

HEADER = b"x-bensz-search-context"
PROCESS_ID = uuid4().hex
MAX_HOPS = 8


class FederationError(Exception):
    def __init__(self, category, status_code=503):
        self.category, self.status_code = category, status_code
        super().__init__(category)


class WireContext(StrictModel):
    version: int = Field(default=1, ge=1, le=1)
    path: list[str] = Field(default_factory=list, max_length=MAX_HOPS)
    max_hops: int = Field(default=4, ge=1, le=MAX_HOPS)
    remaining_ms: int = Field(default=60000, ge=1, le=60000)
    remaining_calls: int = Field(default=10, ge=1, le=64)
    cost_budget_usd: float = Field(default=10, ge=0, le=10)


@dataclass(frozen=True)
class FederationContext:
    path: tuple[str, ...]
    max_hops: int
    deadline: float
    remaining_calls: int
    cost_budget_usd: float

    def remaining_ms(self):
        remaining = int((self.deadline - time.monotonic()) * 1000)
        if remaining < 100:
            raise FederationError("timeout", 408)
        return min(60000, remaining)

    def headers(self, timeout_ms, calls, cost):
        if len(self.path) >= self.max_hops:
            raise FederationError("federation_depth_exceeded")
        if calls < 1:
            raise FederationError("call_budget_exceeded")
        wire = WireContext(
            path=list(self.path),
            max_hops=self.max_hops,
            remaining_ms=min(timeout_ms, self.remaining_ms()),
            remaining_calls=min(calls, self.remaining_calls),
            cost_budget_usd=min(cost, self.cost_budget_usd),
        )
        return {HEADER.decode(): wire.model_dump_json()}


current: ContextVar[FederationContext | None] = ContextVar("bensz_search_federation", default=None)


def instance_id():
    configured = os.getenv("BENSZ_SEARCH_INSTANCE_ID")
    if configured:
        if not valid_id(configured):
            raise RuntimeError("BENSZ_SEARCH_INSTANCE_ID must contain 1–64 ASCII letters, digits, _ or -")
        return configured
    # Production already shares this secret across workers; never expose the secret itself.
    secret = os.getenv("BENSZ_SEARCH_SECRET")
    return (
        hashlib.sha256(("bensz-search-instance-v1:" + secret).encode()).hexdigest() if secret else PROCESS_ID
    )


def valid_id(value):
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value)
    )


def receive_context(headers, node=None):
    values = [v for k, v in headers if k.lower() == HEADER]
    local_hops = max(1, min(MAX_HOPS, int(os.getenv("BENSZ_SEARCH_MAX_HOPS", "4"))))
    try:
        if len(values) > 1 or (values and len(values[0]) > 4096):
            raise ValueError("invalid header")
        wire = WireContext.model_validate_json(values[0]) if values else WireContext(max_hops=local_hops)
        if any(not valid_id(n) for n in wire.path) or len(set(wire.path)) != len(wire.path):
            raise ValueError("invalid path")
    except ValueError:
        raise FederationError("invalid_federation_context", 422) from None
    node = node or instance_id()
    if node in wire.path:
        raise FederationError("federation_loop", 508)
    max_hops = min(wire.max_hops, local_hops)
    if len(wire.path) >= max_hops:
        raise FederationError("federation_depth_exceeded")
    return FederationContext(
        (*wire.path, node),
        max_hops,
        time.monotonic() + wire.remaining_ms / 1000,
        min(wire.remaining_calls, max(1, min(10, int(os.getenv("BENSZ_SEARCH_MAX_CALLS", "10"))))),
        wire.cost_budget_usd,
    )


def context():
    return current.get() or receive_context([])


class FederationMiddleware:
    """Bind a context to HTTP/MCP and expose support before any delegated search."""

    def __init__(self, app, node=None):
        self.app, self.node = app, node

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == "/search"
            or path.startswith(("/search/", "/v1/search", "/bensz-search/"))
            or path == "/admin/api/search"
            or (path.startswith("/admin/api/providers/") and path.endswith("/test"))
        ):
            return await self.app(scope, receive, send)
        node = self.node or instance_id()

        async def response_send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-bensz-search-federation", b"1"),
                        (b"x-bensz-search-node", node.encode()),
                    ],
                }
            await send(message)

        try:
            ctx = receive_context(scope.get("headers", []), node)
        except FederationError as error:
            from .protocol import ProtocolFailure

            body = (
                ProtocolFailure(error.category, "Federated search rejected", status_code=error.status_code)
                .envelope()
                .model_dump_json()
                .encode()
            )
            await response_send(
                {
                    "type": "http.response.start",
                    "status": error.status_code,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            return await response_send({"type": "http.response.body", "body": body})
        token = current.set(ctx)
        try:
            await self.app(scope, receive, response_send)
        finally:
            current.reset(token)


def bounded_task(task):
    ctx = current.get()
    if ctx is None:
        return task
    return task.model_copy(
        update={
            "latency_budget_ms": min(
                task.latency_budget_ms, max(100, int((ctx.deadline - time.monotonic()) * 1000))
            ),
            "cost_budget_usd": min(task.cost_budget_usd, ctx.cost_budget_usd),
        }
    )
