"""Bounded process-local metrics; logs do not include user queries or credentials."""

import json
import logging
from collections import Counter, deque
from itertools import combinations

from .fusion import canonical_url

logger = logging.getLogger("bensz_search")


class Telemetry:
    def __init__(self, history_size=200):
        self.history = deque(maxlen=history_size)
        self.counts = Counter()
        self.feedback_counts = Counter()

    def record(self, request_id, task, plan, attempts, buckets, estimated_cost, fusion_trace):
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
        self.history.append(event)
        logger.info("smart_search %s", json.dumps(event, ensure_ascii=False))
        return event

    def feedback(self, feedback):
        if not any(event["request_id"] == feedback.request_id for event in self.history):
            raise KeyError("request_id is not in the process-local recent history")
        self.feedback_counts[feedback.event] += 1

    def snapshot(self):
        return {
            "scope": "process",
            "persistent": False,
            "counters": dict(self.counts),
            "feedback": dict(self.feedback_counts),
            "recent": list(self.history),
        }
