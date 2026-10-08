"""Bounded process-local metrics; logs do not include user queries or credentials."""

import json
import logging
import threading
from collections import Counter, deque
from contextvars import ContextVar
from datetime import UTC, datetime
from itertools import combinations

from .fusion import canonical_url
from .usage import SUCCESS, add, aggregate, summary
from .work import BlockingWork

logger = logging.getLogger("bensz_search")
usage_key = ContextVar("bensz_search_usage_key", default=None)
usage_user = ContextVar("bensz_search_usage_user", default=None)


class Telemetry:
    def __init__(self, history_size=200):
        self.history = deque(maxlen=history_size)
        self.counts = Counter()
        self.feedback_counts = Counter()
        self.lock = threading.RLock()
        self.started_at = datetime.now(UTC).isoformat()
        self.total = aggregate()
        self.providers = {}
        self.days = {}
        self.sink = None
        self.work = BlockingWork()

    def record(
        self, request_id, task, plan, attempts, buckets, estimated_cost, fusion_trace, latency_ms=None
    ):
        with self.lock:
            event = self._record(
                request_id, task, plan, attempts, buckets, estimated_cost, fusion_trace, latency_ms
            )
        return self._persist(event)

    async def arecord(self, *args, **kwargs):
        return await self.work.run(self.record, *args, **kwargs)

    async def arecord_execution(self, *args, **kwargs):
        return await self.work.run(self.record_execution, *args, **kwargs)

    def _persist(self, event):
        if self.sink:
            try:
                self.sink(event)
            except Exception:
                with self.lock:
                    self.counts["persistence_errors"] += 1
                logger.error("Search usage persistence failed; process metrics remain available")
        logger.info("smart_search %s", json.dumps(event, ensure_ascii=False))
        return event

    def _record(
        self, request_id, task, plan, attempts, buckets, estimated_cost, fusion_trace, latency_ms=None
    ):
        marginal, seen = {}, set()
        urls = {name: {canonical_url(r.url) for r in rows} for name, rows in buckets.items()}
        for name, keys in urls.items():
            marginal[name] = len(keys - seen)
            seen |= keys
        overlap = {
            f"{a}:{b}": {
                "shared": len(urls[a] & urls[b]),
                "jaccard": len(urls[a] & urls[b]) / max(1, len(urls[a] | urls[b])),
            }
            for a, b in combinations(urls, 2)
        }
        for entry in plan.providers:
            self.counts[f"selected:{task.intent}:{entry.name}"] += 1
        provider_contributions, family_contributions = Counter(), Counter()
        for document in fusion_trace:
            provider_contributions.update(document["provider_contributions"])
            family_contributions.update(document["family_contributions"])
        for attempt in attempts:
            self.counts[f"{task.intent}:{attempt['provider']}:{attempt['status']}"] += 1
        self.counts["requests"] += 1
        self.counts["fallbacks"] += sum(bool(a["fallback"]) for a in attempts)
        event = {
            "request_id": request_id,
            "intent": task.intent,
            "providers": [p.name for p in plan.providers],
            "plan": plan.model_dump(),
            "result_count": len(fusion_trace),
            "fusion_contribution": {
                "providers": dict(provider_contributions),
                "families": dict(family_contributions),
            },
            "routing_reason": plan.routing_reason,
            "attempts": attempts,
            "estimated_cost_usd": estimated_cost,
            "marginal_gain": marginal,
            "overlap": overlap,
        }
        return self._append(event, latency_ms)

    def record_execution(self, request_id, intent, attempts, result_count, cost, latency_ms, reasons=None):
        # Deliberately project only safe execution metadata, never external query/call IDs.
        event = {
            "request_id": request_id,
            "intent": intent,
            "providers": list(dict.fromkeys(a["provider"] for a in attempts)),
            "routing_reason": reasons or [],
            "attempts": attempts,
            "result_count": result_count,
            "estimated_cost_usd": cost,
            "fusion_contribution": {"providers": {}, "families": {}},
            "marginal_gain": {},
            "overlap": {},
        }
        with self.lock:
            self.counts["requests"] += 1
            self.counts["fallbacks"] += sum(bool(a.get("fallback")) for a in attempts)
            for a in attempts:
                self.counts[f"{intent}:{a['provider']}:{a['status']}"] += 1
            self._append(event, latency_ms)
        return self._persist(event)

    def _append(self, event, latency_ms=None):
        event["timestamp"] = datetime.now(UTC).isoformat()
        event["latency_ms"] = (
            latency_ms
            if latency_ms is not None
            else max(
                (a["latency_ms"] for a in event["attempts"]),
                default=0,
            )
        )
        status = "success" if event["result_count"] else "failed"
        if status == "success" and any(a["status"] not in SUCCESS for a in event["attempts"]):
            status = "partial_success"
        event["status"] = status
        with self.lock:
            self.history.append(event)
            for target in (self.total, self.days.setdefault(event["timestamp"][:10], aggregate())):
                add(
                    target,
                    status,
                    event["latency_ms"],
                    event["estimated_cost_usd"],
                    sum(bool(a.get("fallback")) for a in event["attempts"]),
                )
            # Keep the process trend bounded, independent of uptime.
            for day in sorted(self.days)[:-30]:
                del self.days[day]
            for a in event["attempts"]:
                if a["status"] != "skipped":
                    add(
                        self.providers.setdefault(a["provider"], aggregate()),
                        a["status"],
                        a["latency_ms"],
                        a.get("estimated_cost_usd", 0),
                        int(bool(a.get("fallback"))),
                    )
        return event

    def feedback(self, feedback):
        with self.lock:
            if not any(event["request_id"] == feedback.request_id for event in self.history):
                raise KeyError("request_id is not in the process-local recent history")
            self.feedback_counts[feedback.event] += 1

    def detail(self, request_id):
        with self.lock:
            return next((e for e in self.history if e["request_id"] == request_id), None)

    def snapshot(self, compact=False):
        with self.lock:
            return {
                "scope": "process",
                "persistent": False,
                "started_at": self.started_at,
                "window_basis": "current process lifetime; trend limited to 30 UTC days",
                "counters": dict(self.counts),
                "feedback": dict(self.feedback_counts),
                "recent": [
                    {
                        k: e[k]
                        for k in (
                            "request_id",
                            "timestamp",
                            "intent",
                            "providers",
                            "result_count",
                            "status",
                            "latency_ms",
                        )
                    }
                    | {"attempts": [{"status": a["status"]} for a in e["attempts"]]}
                    for e in list(self.history)[-20:]
                ]
                if compact
                else list(self.history),
                "summary": summary(self.total),
                "by_provider": [{"name": n, **summary(d)} for n, d in sorted(self.providers.items())],
                "trend": [{"day": day, **summary(data)} for day, data in sorted(self.days.items())],
            }
