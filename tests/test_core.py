import pytest
from litellm.llms.base_llm.search.transformation import SearchResult

from bensz_search.fusion import canonical_url, fuse
from bensz_search.health import Health
from bensz_search.intent import analyze
from bensz_search.models import SearchRequest, SearchTask
from bensz_search.planner import Planner
from bensz_search.registry import Registry


def registry():
    return Registry.load("config/capabilities.yaml")


def test_rules_and_profile_override():
    assert analyze(SearchRequest(query="ctDNA randomized clinical trial evidence")).intent == "academic"
    assert analyze(SearchRequest(query="Python asyncio documentation")).intent == "coding"
    assert analyze(SearchRequest(query="OpenAI launched today")).intent == "news"
    assert (
        analyze(SearchRequest(query="anything", profile={"type": "scientific_research"})).intent == "academic"
    )
    task = analyze(
        SearchRequest(
            query="ctDNA",
            profile_prompt="I am a biomedical research agent. Prefer primary literature and high recall.",
        )
    )
    assert task.domain == "biomedical"
    assert task.recall_requirement == "high"


def test_simple_and_research_plans():
    reg = registry()
    planner = Planner(reg, Health())
    single = planner.plan(analyze(SearchRequest(query="capital of France")), set(reg.providers))
    assert len(single.providers) == 1
    multi = planner.plan(
        analyze(SearchRequest(query="ctDNA trial", constraints={"recall": "high"})), set(reg.providers)
    )
    assert len(multi.providers) == 2
    assert len({reg.providers[p.name].source_family for p in multi.providers}) == 2


def test_budget_all_primary_calls_and_query_list():
    reg = registry()
    task = SearchTask(query=["a", "b"], intent="deep", cost_budget_usd=0.004)
    plan = Planner(reg, Health()).plan(task, set(reg.providers))
    assert sum(reg.providers[p.name].estimated_cost_usd * 2 for p in plan.providers) <= 0.004
    assert len(plan.providers) <= 3


def test_url_keeps_meaningful_case_and_pages():
    assert canonical_url("https://WWW.Example.com:443/Doc?utm_source=a&id=X#x") == "example.com/Doc?id=X"
    assert canonical_url("http://example.com/Doc?id=X") == "example.com/Doc?id=X"
    assert canonical_url("https://x.com/A") != canonical_url("https://x.com/a")
    assert canonical_url("https://x.com/p?page=1") != canonical_url("https://x.com/p?page=2")


def test_family_votes_and_duplicates():
    result = SearchResult(title="Shared paper", url="https://x.com/a", snippet="a")
    other = SearchResult(title="Independent paper", url="https://y.com/b", snippet="b")
    buckets = {"g1": [result, result], "g2": [result], "exa": [other]}
    results, trace = fuse(
        buckets,
        {"g1": 1, "g2": 1, "exa": 1},
        {"g1": "google", "g2": "google", "exa": "exa"},
        "weighted_rrf",
        10,
    )
    assert len(results) == 2
    assert trace[0]["score"] == pytest.approx(1 / 61)
    assert trace[1]["score"] == pytest.approx(1 / 61)
    buckets["exa"].append(result)
    results, trace = fuse(
        buckets,
        {"g1": 1, "g2": 1, "exa": 1},
        {"g1": "google", "g2": "google", "exa": "exa"},
        "weighted_rrf",
        10,
    )
    assert results[0].url == result.url
    assert trace[0]["score"] == pytest.approx(1 / 61 + 1 / 62)


def test_validation_and_health():
    with pytest.raises(ValueError):
        SearchRequest(query="", constraints={"cost": "bad"})
    with pytest.raises(ValueError):
        SearchRequest(query="x", api_base="http://arbitrary")
    health = Health(threshold=2, cooldown_s=10)
    health.failure("exa", "auth")
    assert not health.available("exa")
    health.failure("brave", "timeout")
    assert health.available("brave")
    health.failure("brave", "timeout")
    assert not health.available("brave")
