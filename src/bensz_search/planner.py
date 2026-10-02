"""Small deterministic planner: bounded fan-out and diverse information sources."""

from .health import Health
from .models import PlanEntry, SearchPlan, SearchTask
from .registry import Registry


class NoProviders(ValueError):
    pass


class Planner:
    def __init__(self, registry: Registry, health: Health):
        self.registry, self.health = registry, health

    def score(self, task, name):
        p = self.registry.providers[name]
        c, state = p.capabilities, self.health.state(name)
        semantic = task.intent in {"academic", "deep", "people"} or task.semantic_requirement == "high"
        score = 0.65 * c.get(task.intent, 0.3) + 0.20 * c.get("semantic" if semantic else "keyword", 0.3)
        score += 0.15 * c.get("authority" if task.authority_requirement == "high" else "general", 0.3)
        if task.freshness != "any":
            score = score * 0.7 + 0.3 * c.get("freshness", 0.3)
        score *= p.quality * max(0.2, state.success_rate)
        if state.latency_ms is not None:
            score *= max(0.5, 1 - state.latency_ms / (task.latency_budget_ms * 4))
        score *= {"low": 1.0, "medium": 0.97, "high": 0.90}[p.cost_class]
        score *= {"low": 1.0, "medium": 0.98, "high": 0.94}[p.latency_class]
        return score

    def plan(self, task: SearchTask, allowed: set[str], fusion="weighted_rrf") -> SearchPlan:
        multiplier = len(task.query) if isinstance(task.query, list) else 1
        eligible = [
            name
            for name, p in self.registry.providers.items()
            if name in allowed
            and self.health.available(name)
            and p.estimated_cost_usd * multiplier <= task.cost_budget_usd + 1e-12
        ]
        ranked = sorted(eligible, key=lambda name: (-self.score(task, name), name))
        if not ranked:
            raise NoProviders("No configured, authorized and healthy provider fits the estimated cost budget")
        count = (
            3
            if task.intent == "deep"
            else 2
            if task.intent in {"academic", "news", "people"}
            or task.recall_requirement == "high"
            or task.source_diversity == "high"
            else 1
        )
        if task.prefer_single:
            count = 1
        if fusion == "none":
            count = 1
        selected, families, spent = [], set(), 0.0
        while ranked and len(selected) < count:
            candidates = [
                n
                for n in ranked
                if spent + self.registry.providers[n].estimated_cost_usd * multiplier
                <= task.cost_budget_usd + 1e-12
            ]
            if not candidates:
                break
            name = max(
                candidates,
                key=lambda n: (
                    self.score(task, n)
                    * (0.55 if self.registry.providers[n].source_family in families else 1)
                ),
            )
            ranked.remove(name)
            selected.append(name)
            families.add(self.registry.providers[name].source_family)
            spent += self.registry.providers[name].estimated_cost_usd * multiplier

        def entry(name):
            return PlanEntry(name=name, weight=max(0.01, self.score(task, name)), count=task.result_count)

        reasons = list(task.routing_reason)
        reasons += [
            "only configured, authorized, healthy tools considered",
            "global timeout and estimated cost budget enforced",
        ]
        if len(selected) > 1:
            reasons.append("source diversity preferred; correlated source families penalized")
        else:
            reasons.append("single provider sufficient or constrained by cost/latency")
        reasons.append("capability scores are configurable priors; no LLM planner call")
        return SearchPlan(
            strategy="parallel" if len(selected) > 1 else "single",
            providers=[entry(n) for n in selected],
            fallbacks=[entry(n) for n in ranked],
            fusion=fusion,
            timeout_ms=task.latency_budget_ms,
            max_cost=task.cost_budget_usd,
            routing_reason=reasons,
        )
