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
        state = self.state(name)
        state.failures, state.open_until, state.probing = 0, 0, False
        state.success_rate = 0.8 * state.success_rate + 0.2
        state.latency_ms = (
            latency_ms if state.latency_ms is None else 0.8 * state.latency_ms + 0.2 * latency_ms
        )

    def failure(self, name, category):
        state = self.state(name)
        probe = state.probing
        state.failures += 1
        state.probing = False
        state.success_rate *= 0.8
        if category in {"auth", "quota"} or probe or state.failures >= self.threshold:
            state.open_until = self.clock() + (300 if category in {"auth", "quota"} else self.cooldown_s)

    def release(self, name):
        self.state(name).probing = False
