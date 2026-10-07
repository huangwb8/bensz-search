"""Small bounded aggregates shared by process metrics and SQLite daily summaries."""

from bisect import bisect_left

# Persist bucket counts, never raw queries, URLs, user identifiers or unbounded samples.
LATENCY_BOUNDS = (25, 50, 100, 200, 400, 800, 1500, 3000, 6000, 10000, 15000, 30000, 60000)
SUCCESS = {"success", "partial_success"}


def aggregate():
    return {
        "requests": 0,
        "successes": 0,
        "latency_total_ms": 0,
        "histogram": [0] * (len(LATENCY_BOUNDS) + 1),
        "estimated_cost_usd": 0,
        "fallbacks": 0,
        "statuses": {},
    }


def add(target, status, latency_ms, cost=0, fallbacks=0):
    target["requests"] += 1
    target["successes"] += int(status in SUCCESS)
    target["latency_total_ms"] += latency_ms
    target["histogram"][bisect_left(LATENCY_BOUNDS, latency_ms)] += 1
    target["estimated_cost_usd"] += cost
    target["fallbacks"] += fallbacks
    target["statuses"][status] = target["statuses"].get(status, 0) + 1


def merge(target, source):
    for field in ("requests", "successes", "latency_total_ms", "estimated_cost_usd", "fallbacks"):
        target[field] += source[field]
    target["histogram"] = [a + b for a, b in zip(target["histogram"], source["histogram"], strict=True)]
    for status, count in source["statuses"].items():
        target["statuses"][status] = target["statuses"].get(status, 0) + count


def summary(data):
    count = data["requests"]

    def percentile(fraction):
        seen = 0
        for bound, amount in zip((*LATENCY_BOUNDS, 120000), data["histogram"], strict=True):
            seen += amount
            if count and seen >= count * fraction:
                return bound
        return None

    return {
        "requests": count,
        "successes": data["successes"],
        "success_rate": data["successes"] / count if count else None,
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "mean_latency_ms": round(data["latency_total_ms"] / count, 2) if count else None,
        "estimated_cost_usd": round(data["estimated_cost_usd"], 8),
        "fallbacks": data["fallbacks"],
        "statuses": data["statuses"].copy(),
        "latency_basis": "histogram bucket upper bounds; overflow bucket capped at 120000 ms",
        "cost_basis": "configured conservative estimate; not provider billing",
    }
