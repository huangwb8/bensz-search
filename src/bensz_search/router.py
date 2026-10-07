"""Execution owns one deadline, one attempt per tool and one estimated cost reservation."""

import time
from uuid import uuid4

from litellm.llms.base_llm.search.transformation import SearchResponse

from .executor import ExecutionCall, execute
from .executor import failure_category as failure_category
from .federation import bounded_task
from .filters import provider_options
from .fusion import fuse
from .health import Health
from .intent import analyze
from .models import SearchRequest
from .planner import NoProviders, Planner
from .telemetry import Telemetry


class SearchFailed(Exception):
    def __init__(self, message="Search providers could not return usable results", status_code=502):
        super().__init__(message)
        self.status_code = status_code


class SmartRouter:
    def __init__(self, registry, call, health=None, telemetry=None):
        self.registry, self.call = registry, call
        self.health, self.telemetry = health or Health(), telemetry or Telemetry()
        self.planner = Planner(registry, self.health)
        self.generation = str(uuid4())

    async def search(self, request: SearchRequest, allowed: set[str], context=None):
        started = time.monotonic()
        task = bounded_task(analyze(request))
        try:
            plan = self.planner.plan(task, allowed, request.fusion)
        except NoProviders as error:
            raise SearchFailed(str(error), 503) from error
        request_id = str(uuid4())
        all_entries = plan.providers + plan.fallbacks

        def execution_call(entry):
            capability = self.registry.providers[entry.name]
            options = provider_options(capability.provider, task)
            if capability.provider == "bensz_search":
                options["fusion"] = request.fusion
            if request.search_domain_filter:
                options["search_domain_filter"] = request.search_domain_filter
            if request.country:
                options["country"] = request.country
            if request.max_tokens_per_page is not None:
                options["max_tokens_per_page"] = request.max_tokens_per_page
            if capability.intent_engines.get(task.intent):
                options["engines"] = ",".join(capability.intent_engines[task.intent])
            return ExecutionCall(
                entry.name,
                entry.name,
                request.query,
                entry.count,
                entry.weight,
                options=options,
                domains=request.search_domain_filter,
                task=task,
            )

        calls = [execution_call(e) for e in plan.providers]
        fallbacks = [execution_call(e) for e in plan.fallbacks]
        for item in calls:
            item.fallbacks = fallbacks
        buckets, attempts, reserved_cost = await execute(
            self, calls, plan.timeout_ms, plan.max_cost, request_id, context, empty_is_failure=True
        )
        # Stable provider order, independent of network completion speed.
        ordered = {entry.name: buckets[entry.name] for entry in all_entries if entry.name in buckets}
        results, trace = fuse(
            ordered,
            {e.name: e.weight for e in all_entries},
            {n: p.source_family for n, p in self.registry.providers.items()},
            plan.fusion,
            request.max_results,
        )
        event = self.telemetry.record(
            request_id,
            task,
            plan,
            attempts,
            ordered,
            round(reserved_cost, 8),
            trace,
            round((time.monotonic() - started) * 1000, 2),
        )
        if not results:
            raise SearchFailed()
        response = SearchResponse(results=results)
        response._hidden_params["smart_search_request_id"] = request_id
        if request.debug:
            response.debug = {
                **event,
                "task": task.model_dump(exclude={"query", "caller_profile"}),
                "plan": plan.model_dump(),
                "fusion": trace,
                "partial_success": any(a["status"] != "success" for a in attempts),
                "cost_basis": "configured conservative estimate; not provider billing",
            }
        return response
