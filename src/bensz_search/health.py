"""Process-local circuit breaker, including exclusive half-open probes."""

import time
from dataclasses import dataclass


@dataclass
class State:
    failures: int = 0
    open_until: float = 0
    probing: bool = False
    success_rate: float = 1
    latency_ms: float | None = None
    observed_at: str | None = None
    observed_result: str = "unknown"


class Health:
    def __init__(self, threshold=3, cooldown_s=30, clock=time.monotonic):
        self.states: dict[str, State] = {}
        self.threshold, self.cooldown_s, self.clock = threshold, cooldown_s, clock

    def state(self, name):
        return self.states.setdefault(name, State())

    def available(self, name):
        state = self.state(name)
        return state.open_until <= self.clock() and not state.probing

    def claim(self, name):
        if not self.available(name):
            return False
        state = self.state(name)
        if state.open_until:
            state.probing = True
        return True

    def success(self, name, latency_ms):
        from datetime import UTC, datetime

        state = self.state(name)
        state.observed_at, state.observed_result = datetime.now(UTC).isoformat(), "success"
        state.failures, state.open_until, state.probing = 0, 0, False
        state.success_rate = 0.8 * state.success_rate + 0.2
        state.latency_ms = (
            latency_ms if state.latency_ms is None else 0.8 * state.latency_ms + 0.2 * latency_ms
        )

    def failure(self, name, category):
        from datetime import UTC, datetime

        state = self.state(name)
        state.observed_at, state.observed_result = datetime.now(UTC).isoformat(), category
        probe = state.probing
        state.failures += 1
        state.probing = False
        state.success_rate *= 0.8
        if category in {"auth", "quota"} or probe or state.failures >= self.threshold:
            state.open_until = self.clock() + (300 if category in {"auth", "quota"} else self.cooldown_s)

    def release(self, name):
        self.state(name).probing = False

    def snapshot(self, name, enabled=True):
        state = self.states.get(name, State())
        remaining = max(0, state.open_until - self.clock())
        status = (
            "disabled"
            if not enabled
            else "half_open"
            if state.probing
            else "open"
            if remaining
            else "unknown"
            if state.observed_at is None
            else "degraded"
            if state.failures
            else "healthy"
        )
        return {
            "name": name,
            "state": status,
            "scope": "process",
            "cooldown_remaining_s": round(remaining, 1),
            "failures": state.failures,
            "last_error": None if state.observed_result in {"unknown", "success"} else state.observed_result,
            "observed_at": state.observed_at,
            "success_rate": state.success_rate,
            "latency_ms": state.latency_ms,
        }
