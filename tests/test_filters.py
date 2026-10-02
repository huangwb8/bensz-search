from datetime import UTC, datetime

from litellm.llms.base_llm.search.transformation import SearchResult

from bensz_search.filters import filter_results, provider_options
from bensz_search.models import SearchTask


def test_freshness_rejects_old_unknown_and_future_dates():
    task = SearchTask(query="q", freshness="month")
    now = datetime(2026, 10, 2, tzinfo=UTC)
    rows = [
        SearchResult(title="document", url="https://example.org/" + str(i), snippet="x", date=date)
        for i, date in enumerate(["2026-10-01", "2020-01-01", None, "2030-01-01"])
    ]
    assert len(filter_results(rows, task, [], now)) == 1
    assert provider_options("exa_ai", task, now)["startPublishedDate"].startswith("2026-09-02")


def test_domain_filter_and_invalid_urls():
    rows = [
        SearchResult(title="document", url=url, snippet="x")
        for url in [
            "https://a.example.org/x",
            "https://evil-example.org/x",
            "https://private.example.org/x",
            "javascript:alert(1)",
            "https://example.org:bad/a",
        ]
    ]
    assert len(filter_results(rows, SearchTask(query="q"), ["example.org", "-private.example.org"])) == 1
