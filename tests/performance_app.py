"""Synthetic production-mode gateway for isolated container capacity checks."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("BENSZ_SEARCH_MODE", "production")
os.environ.setdefault("BENSZ_SEARCH_CONFIG", "config/litellm.yaml")
os.environ.setdefault("SEARXNG_API_BASE", "http://127.0.0.1:8099")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-synthetic-performance-master-not-a-real-secret")
os.environ.setdefault("BENSZ_SEARCH_SECRET", "synthetic-performance-encryption-not-a-real-secret")
os.environ.setdefault("BENSZ_SEARCH_ADMIN_PASSWORD", "synthetic-performance-password")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_TELEMETRY", "False")

from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult  # noqa: E402

from bensz_search.server import app  # noqa: E402

original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with original_lifespan(application) as state:

        async def provider(**kwargs):
            await asyncio.sleep(0.1)
            return SearchResponse(
                results=[SearchResult(title="Synthetic", url="https://example.org", snippet="Synthetic")]
            )

        application.state.smart_search.call = provider
        yield state


app.router.lifespan_context = lifespan


@app.get("/benchmark/state")
async def benchmark_state():
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"VmRSS", "VmSize", "Threads"}:
            status[key] = int(value.strip().split()[0])
    status["fds"] = len(list(Path("/proc/self/fd").iterdir()))
    status["tasks"] = len(asyncio.all_tasks())
    status["capacity"] = app.state.search_capacity.snapshot()
    status["performance"] = app.state.performance.snapshot()
    status["store"] = app.state.admin_runtime.store.performance()
    return status
