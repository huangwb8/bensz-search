"""Lightweight per-identity HTTP client and bounded host-side tool dispatcher."""

import asyncio
import copy
import json
import time

import httpx
from pydantic import ValidationError

from .protocol_models import ProtocolSearch


class SearchClient:
    def __init__(self, url, key, *, timeout=20, transport=None):
        self._http = httpx.AsyncClient(
            base_url=url.rstrip("/") + "/",
            timeout=timeout,
            headers={"Authorization": "Bearer " + key},
            transport=transport,
        )
        self._snapshot = None
        self._expires = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self._http.aclose()

    def invalidate(self):
        self._snapshot, self._expires = None, 0

    async def capabilities(self):
        if self._snapshot is not None and time.monotonic() < self._expires:
            return copy.deepcopy(self._snapshot)
        response = await self._http.get("bensz-search/v1/capabilities")
        response.raise_for_status()
        data = response.json()
        if str(data.get("protocol_version", "")).split(".")[0] != "1":
            raise ValueError("unsupported search protocol version")
        self._snapshot = data
        self._expires = time.monotonic() + min(30, max(0, data["cache_ttl_seconds"]))
        return copy.deepcopy(data)

    async def search(self, request):
        data = ProtocolSearch.model_validate(request).model_dump(mode="json")
        # No retries: a timed-out request may already have incurred provider cost.
        response = await self._http.post("bensz-search/v1/search", json=data)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("response must be an object")
        except ValueError:
            raise httpx.DecodingError(
                "Invalid search response; execution outcome unknown", request=response.request
            ) from None
        if (result.get("error") or {}).get("code") == "stale_capabilities":
            self.invalidate()
        if response.is_error and "protocol_version" not in result:
            response.raise_for_status()
        return result

    async def legacy_auto(self, query, max_results=10):
        """Explicit migration fallback; the legacy response has fewer guarantees."""
        response = await self._http.post("search", json={"query": query, "max_results": max_results})
        response.raise_for_status()
        return {
            "integration_mode": "legacy_auto",
            "legacy_response": response.json(),
            "cost_basis": "legacy response may not report estimated cost",
        }


def tool_error(code, message):
    return {"status": "failed", "error": {"code": code, "message": message}}


class ToolSession:
    """Task totals survive model turns and parallel tool requests; no shared keys."""

    def __init__(
        self, client, *, budget_usd=0.06, max_searches=3, max_corrections=2, duration_s=60, allow_network=True
    ):
        self.client = client
        self.budget_usd, self.max_searches = budget_usd, max_searches
        self.max_corrections, self.allow_network = max_corrections, allow_network
        self.deadline = time.monotonic() + duration_s
        self.spent, self.searches, self.corrections = 0.0, 0, 0
        self.delivered_revision = None
        self._lock = asyncio.Lock()

    async def dispatch(self, name, arguments):
        async with self._lock:
            if not self.allow_network:
                return tool_error("network_forbidden", "Network access is disabled by the host")
            if time.monotonic() >= self.deadline:
                return tool_error("limit_reached", "Task deadline reached")
            try:
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                if name == "bensz_search_capabilities":
                    if arguments:
                        raise ValueError("capabilities accepts no arguments")
                    snapshot = await asyncio.wait_for(
                        self.client.capabilities(), self.deadline - time.monotonic()
                    )
                    self.delivered_revision = snapshot["registry_revision"]
                    return snapshot
                if name != "bensz_search":
                    return tool_error("unknown_tool", "Unknown logical tool")
                if self.corrections > self.max_corrections:
                    return tool_error("limit_reached", "Invalid plan correction limit reached")
                request = ProtocolSearch.model_validate(arguments)
                if request.mode == "planned" and not self.delivered_revision:
                    return tool_error("capabilities_required", "Discover capabilities before planned search")
                if request.mode == "planned" and request.registry_revision != self.delivered_revision:
                    return tool_error("stale_capabilities", "Use the delivered registry_revision")
                if self.searches >= self.max_searches or self.spent >= self.budget_usd:
                    return tool_error("limit_reached", "Task search count or budget reached")
                remaining = self.deadline - time.monotonic()
                if remaining < 0.1:
                    return tool_error("limit_reached", "Insufficient task time remaining")
                values = request.model_dump()
                values["constraints"]["cost_budget_usd"] = min(
                    request.constraints.cost_budget_usd
                    if request.constraints.cost_budget_usd is not None
                    else 0.02,
                    max(0, self.budget_usd - self.spent),
                )
                values["constraints"]["latency_budget_ms"] = min(
                    request.constraints.latency_budget_ms or 8000, int(remaining * 1000), 60000
                )
                result = await asyncio.wait_for(self.client.search(values), remaining)
                code = (result.get("error") or {}).get("code")
                if code == "stale_capabilities":
                    self.delivered_revision = None
                    self.corrections += 1
                elif result.get("status") == "failed" and not result.get("execution"):
                    self.corrections += 1
                elif not request.dry_run:
                    self.searches += 1
                    self.spent += result.get("estimated_cost_usd", values["constraints"]["cost_budget_usd"])
                return result
            except (ValidationError, ValueError, TypeError):
                self.corrections += 1
                return tool_error("invalid_plan", "Complete valid JSON arguments are required")
            except (httpx.TimeoutException, TimeoutError):
                # Exhaust admission when paid execution outcome is unknown.
                self.spent = self.budget_usd
                return tool_error("outcome_unknown", "Search timed out; do not replay this request")
            except asyncio.CancelledError:
                self.spent = self.budget_usd
                raise
            except httpx.HTTPError:
                self.spent = self.budget_usd
                return tool_error("transport_error", "Search transport failed; execution may be unknown")

    async def auto_context(self, query):
        """Observable fallback for hosts whose model cannot reliably call tools."""
        result = await self.dispatch("bensz_search", {"mode": "auto", "query": query})
        return {"integration_mode": "host_auto", "search": result}
