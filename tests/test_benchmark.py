import json
from pathlib import Path

import pytest

from bensz_search.health import Health
from bensz_search.intent import analyze
from bensz_search.models import SearchRequest
from bensz_search.planner import Planner
from bensz_search.registry import Registry

CASES = json.loads(Path("tests/benchmarks/routing.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_routing_benchmark(case):
    reg = Registry.load("config/capabilities.yaml")
    task = analyze(SearchRequest(query=case["query"]))
    assert task.intent == case["expected_intent"]
    plan = Planner(reg, Health()).plan(task, set(reg.providers))
    selected = {p.name for p in plan.providers}
    assert selected & set(case["expected_provider"]["any_of"])
    assert selected <= set(case["acceptable"])
    assert not selected & set(case["invalid"])
    assert len(selected) <= 3
