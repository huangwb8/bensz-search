"""Versioned discovery/execution invariants, with provider I/O explicitly mocked."""

import asyncio

import pytest
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult
from pydantic import ValidationError

from bensz_search.protocol import ProtocolFailure, ProtocolLimits, TenantLimiter, capabilities, search
from bensz_search.protocol_models import ProtocolSearch
from bensz_search.registry import Registry
from bensz_search.router import SmartRouter


@pytest.fixture
def router():
    registry = Registry.load("config/capabilities.yaml")
    registry.providers["searxng"] = registry.providers["searxng"].model_copy(
        update={"verified_engines": ["github", "pubmed"], "engine_evidence": "instance configuration fixture"}
    )
    called = []

    async def call(**kwargs):
        called.append(kwargs)
        return SearchResponse(
            results=[
                SearchResult(
                    title="Document",
                    url="https://example.org/document?utm_source=x",
                    snippet="fixture",
                    date="2026-10-01",
                )
            ]
        )

    instance = SmartRouter(registry, call)
    instance.called = called
    return instance


def planned(*calls, **kwargs):
    return ProtocolSearch(mode="planned", calls=list(calls), **kwargs)


def item(call_id="a", tool_id="searxng", **kwargs):
    return {"call_id": call_id, "tool_id": tool_id, "query": "ctDNA", **kwargs}


async def test_discovery_subset_unknown_health_no_io_and_hot_updates(router):
    data = capabilities(router, {"searxng"})
    assert [t["tool_id"] for t in data["tools"]] == ["searxng"]
    assert data["tools"][0]["availability"]["recent_probe_result"] == "unknown"
    assert [e["engine_id"] for e in data["tools"][0]["engines"]] == ["github", "pubmed"]
    assert not router.called
    assert data["registry_revision"] != capabilities(router, {"searxng", "brave"})["registry_revision"]
    router.health.failure("searxng", "auth")
    assert capabilities(router, {"searxng"})["tools"][0]["availability"]["cooling_down"]
    assert data["registry_revision"] == capabilities(router, {"searxng"})["registry_revision"]
    assert capabilities(router, set())["tools"] == []


async def test_different_engine_queries_provenance_and_one_family_vote(router):
    request = planned(
        item(engine_id="pubmed", query="结直肠癌 ctDNA"),
        item("b", engine_id="github", query="ctDNA pipeline"),
    )
    response = await search(router, request, {"searxng"})
    assert response.status == "success"
    assert [k["query"] for k in router.called] == ["结直肠癌 ctDNA", "ctDNA pipeline"]
    assert [k["engines"] for k in router.called] == ["pubmed", "github"]
    assert response.results[0].fusion_score == pytest.approx(1 / 61)
    assert [s.call_id for s in response.results[0].sources] == ["a", "b"]
    assert [s.engine_id for s in response.results[0].sources] == ["pubmed", "github"]
    assert all(k["num_retries"] == 0 and k["disable_fallbacks"] for k in router.called)
    assert all(e["executed"] for e in response.execution)


@pytest.mark.parametrize(
    "bad,code",
    [
        (item("b", "unknown"), "tool_unavailable"),
        (item("b", "brave"), "tool_unavailable"),
        (item("b", engine_id="unverified"), "engine_unavailable"),
        (item("b", options={"country": "CN"}), "query_not_supported"),
    ],
)
async def test_invalid_second_call_does_not_execute_first(router, bad, code):
    with pytest.raises(ProtocolFailure) as error:
        await search(router, planned(item(), bad), {"searxng"})
    assert error.value.error.code == code
    assert error.value.error.field.startswith("calls.1.")
    assert router.called == []


@pytest.mark.parametrize(
    "data",
    [
        {"mode": "planned", "calls": [item(), item()]},
        {"mode": "planned", "calls": [item(api_base="http://arbitrary")]},
        {"mode": "planned", "calls": [item(query=["a", "b"])]},
        {"mode": "planned", "calls": [item(options={"engines": "github"})]},
        {"mode": "auto", "query": " "},
        {"mode": "auto", "query": "query", "calls": [item()]},
        {"mode": "planned", "calls": [item()], "options": {"country": "US"}},
    ],
)
def test_strict_input_contract(data):
    with pytest.raises(ValidationError):
        ProtocolSearch.model_validate(data)


async def test_stale_budget_and_dry_run_zero_io(router):
    with pytest.raises(ProtocolFailure, match="Capabilities changed"):
        await search(router, planned(item(), registry_revision="stale"), {"searxng"})
    with pytest.raises(ProtocolFailure) as error:
        await search(router, planned(item(tool_id="brave"), constraints={"cost_budget_usd": 0}), {"brave"})
    assert error.value.error.code == "budget_exceeded"
    valid = await search(router, planned(item(), dry_run=True), {"searxng"})
    assert valid.status == "validated"
    assert router.called == []


async def test_empty_partial_and_all_failure_classification(router):
    async def call(**kwargs):
        if kwargs["query"] == "fail":
            error = RuntimeError("secret must not escape")
            error.status_code = 429
            raise error
        return SearchResponse(results=[])

    router.call = call
    response = await search(router, planned(item()), {"searxng"})
    assert response.status == "no_results"
    assert router.health.state("searxng").failures == 0
    response = await search(router, planned(item(query="fail")), {"searxng"})
    assert response.status == "failed" and response.execution[0]["error_code"] == "rate_limit"
    assert "secret" not in response.model_dump_json()


async def test_partial_timeout_global_concurrency_and_cancel(router):
    active, maximum, cancelled = 0, 0, []

    async def call(**kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            if kwargs["query"] == "slow":
                await asyncio.sleep(10)
            await asyncio.sleep(0.001)
            return SearchResponse(
                results=[SearchResult(title="Doc", url="https://example.org/doc", snippet="x")]
            )
        finally:
            active -= 1
            cancelled.append(kwargs["query"])

    router.call = call
    limits = ProtocolLimits()
    limits.concurrency = 1
    result = await search(
        router,
        planned(item(), item("b", query="slow"), item("c"), constraints={"latency_budget_ms": 100}),
        {"searxng"},
        limits,
    )
    assert result.status == "partial_success"
    assert maximum == 1 and active == 0
    assert "slow" in cancelled
    assert result.execution[2]["executed"] is False
    running = asyncio.create_task(search(router, planned(item(query="slow"), item("b")), {"searxng"}, limits))
    await asyncio.sleep(0.01)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert active == 0


async def test_fallback_requires_own_query_and_includes_failed_cost(router):
    async def call(**kwargs):
        router.called.append(kwargs)
        if kwargs["search_tool_name"] == "serper":
            raise TimeoutError()
        return SearchResponse(results=[SearchResult(title="Doc", url="https://example.org/doc", snippet="x")])

    router.call = call
    result = await search(
        router,
        planned(
            item(tool_id="serper", query="pubmed style", fallbacks=[item("b", query="plain keywords")]),
            constraints={"cost_budget_usd": 0.002},
        ),
        {"serper", "searxng"},
    )
    assert result.status == "partial_success"
    assert [k["query"] for k in router.called] == ["pubmed style", "plain keywords"]
    assert result.estimated_cost_usd == 0.002
    assert result.execution[1]["fallback"]


async def test_doi_pmid_versions_generated_summary_and_truncation(router):
    async def call(**kwargs):
        return SearchResponse(
            results=[
                SearchResult(
                    title="Same paper", url="https://doi.org/10.1234/PAPER", snippet="", date="2020-01-01"
                ),
                SearchResult(
                    title="Same paper",
                    url="https://publisher.org/paper",
                    doi="10.1234/paper",
                    snippet="x" * 1000,
                    snippet_kind="generated_summary",
                    date="2021-01-01",
                ),
                SearchResult(title="Same title", url="https://arxiv.org/abs/2401.12345v1", snippet="a"),
                SearchResult(title="Same title", url="https://arxiv.org/abs/2401.12345v2", snippet="b"),
                SearchResult(title="Pubmed", url="https://pubmed.ncbi.nlm.nih.gov/12345/", snippet="c"),
                SearchResult(title="Pubmed", url="https://www.ncbi.nlm.nih.gov/pubmed/12345", snippet="d"),
            ]
        )

    router.call = call
    limits = ProtocolLimits()
    limits.max_snippet_chars = 100
    result = await search(router, planned(item()), {"searxng"}, limits)
    assert len(result.results) == 4
    doi = next(r for r in result.results if r.canonical_identity.startswith("doi:"))
    assert len(doi.aliases) == 2 and doi.snippet_kind == "generated_summary"
    assert doi.truncated and len(doi.snippet) == 100
    assert any(w["code"] == "date_conflict" for w in result.warnings)


def test_tenant_admission_shared_boundaries():
    limiter, limits = TenantLimiter(), ProtocolLimits()
    limits.tenant_concurrency, limits.requests_per_minute = 1, 2
    limiter.enter("tenant", limits)
    with pytest.raises(ProtocolFailure):
        limiter.enter("tenant", limits)
    limiter.enter("other", limits)
    limiter.leave("tenant")
    limiter.enter("tenant", limits)
    limiter.leave("tenant")
    with pytest.raises(ProtocolFailure):
        limiter.enter("tenant", limits)
