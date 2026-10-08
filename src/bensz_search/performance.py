"""Small bounded HTTP observations and process-wide search admission."""

import asyncio
import os
import threading
import time
from collections import deque

from fastapi.responses import JSONResponse


class SearchCapacity:
    def __init__(self):
        self.limit = max(1, min(64, int(os.getenv("BENSZ_SEARCH_MAX_CONCURRENT_SEARCHES", "16"))))
        self.active = 0
        self.rejected = 0
        self.lock = threading.Lock()

    def enter(self):
        with self.lock:
            if self.active >= self.limit:
                self.rejected += 1
                return False
            self.active += 1
            return True

    def leave(self):
        with self.lock:
            self.active -= 1

    def snapshot(self):
        with self.lock:
            return {"limit": self.limit, "active": self.active, "rejected": self.rejected}


class Performance:
    def __init__(self):
        self.lock = threading.Lock()
        self.http = deque(maxlen=1024)
        self.loop = deque(maxlen=4096)

    async def sample_loop(self):
        while True:
            started = time.monotonic()
            await asyncio.sleep(0.005)
            with self.lock:
                self.loop.append((time.monotonic() - started) * 1000)

    def snapshot(self):
        def stats(values):
            rows = sorted(values)
            return {
                "samples": len(rows),
                "p95_ms": rows[int((len(rows) - 1) * 0.95)] if rows else 0,
                "p99_ms": rows[int((len(rows) - 1) * 0.99)] if rows else 0,
                "max_ms": max(rows, default=0),
            }

        with self.lock:
            return {"http": stats(self.http), "event_loop_interval": stats(self.loop)}


class PerformanceMiddleware:
    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        search = scope["method"] == "POST" and (
            path in {"/search", "/v1/search", "/admin/api/search", "/bensz-search/v1/search"}
            or path.startswith(("/search/", "/v1/search/"))
            or (path.startswith("/admin/api/providers/") and path.endswith(("/test", "/engines/sync")))
        )
        capacity = self.state.search_capacity
        if search and not capacity.enter():
            payload = {"detail": "Search capacity exhausted; retry later"}
            if path.startswith("/bensz-search/v1/"):
                from .protocol import ProtocolFailure

                payload = (
                    ProtocolFailure(
                        "rate_limit",
                        "Search capacity exhausted; retry later",
                        status_code=429,
                        retryable=True,
                    )
                    .envelope()
                    .model_dump()
                )
            return await JSONResponse(
                payload,
                status_code=429,
                headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )(scope, receive, send)
        if search:
            scope["bensz_search_admitted"] = True
        started = time.monotonic()

        async def timed_send(message):
            if message["type"] == "http.response.start":
                elapsed = (time.monotonic() - started) * 1000
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"server-timing", f"app;dur={elapsed:.2f}".encode()),
                    ],
                }
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            with self.state.performance.lock:
                self.state.performance.http.append((time.monotonic() - started) * 1000)
            if search:
                capacity.leave()
