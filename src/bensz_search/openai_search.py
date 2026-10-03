"""Adapt the Responses web_search tool without changing LiteLLM providers."""

import asyncio
import os
import random
from urllib.parse import urlsplit

import litellm
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from .filters import filter_results
from .fusion import canonical_url
from .models import SearchRequest, SearchTask

DEFAULT_MODEL = "gpt-4.1-mini"


def resolve(value):
    if isinstance(value, str) and value.startswith("os.environ/"):
        return os.getenv(value.split("/", 1)[1], "")
    return value


def normalize(response):
    """Only accept structured sources from a completed web search."""
    data = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(data, dict) or data.get("status") != "completed":
        raise ValueError("OpenAI web search returned an incomplete response")
    output = data.get("output", [])
    if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
        raise ValueError("OpenAI web search returned invalid output")
    calls = [item for item in output if item.get("type") == "web_search_call"]
    if not calls or any(item.get("status") != "completed" for item in calls):
        raise ValueError("OpenAI did not complete the required web search")
    rows = []
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") != "output_text":
                continue
            text = content.get("text", "")
            annotations = content.get("annotations", [])
            for citation in annotations:
                if citation.get("type") != "url_citation":
                    continue
                # This is generated answer context, never represented as a page extract.
                start = citation.get("start_index", 0)
                previous_ends = [
                    a["end_index"]
                    for a in annotations
                    if isinstance(a.get("end_index"), int)
                    and isinstance(start, int)
                    and 0 <= a["end_index"] <= start
                ]
                snippet = (
                    text[max(0, start - 400, *previous_ends) : start].strip()
                    if isinstance(start, int)
                    else ""
                )
                rows.append({**citation, "snippet": snippet, "snippet_kind": "generated_summary"})
    for call in calls:
        for source in (call.get("action") or {}).get("sources", []):
            rows.append({**source, "snippet": "", "snippet_kind": "source_only"})
    results, seen = [], set()
    for row in rows:
        url = row.get("url")
        if not isinstance(url, str):
            continue
        try:
            parts = urlsplit(url)
            _ = parts.port
            identity = canonical_url(url)
        except ValueError:
            continue
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            continue
        if identity in seen:
            continue
        seen.add(identity)
        results.append(
            SearchResult(
                title=row.get("title") or parts.hostname,
                url=url,
                snippet=row["snippet"],
                snippet_kind=row["snippet_kind"],
            )
        )
    return results


async def search(params, kwargs):
    request = SearchRequest.model_validate(
        {
            key: kwargs[key]
            for key in ("query", "max_results", "search_domain_filter", "country", "max_tokens_per_page")
            if kwargs.get(key) is not None
        }
    )
    key = resolve(params.get("api_key"))
    if not key:
        raise ValueError("OpenAI web search requires a configured API key")
    tool = {"type": "web_search", "search_context_size": params.get("search_context_size", "medium")}
    includes = [d for d in request.search_domain_filter if not d.startswith("-")]
    excludes = [d[1:] for d in request.search_domain_filter if d.startswith("-")]
    if includes or excludes:
        tool["filters"] = {}
        if includes:
            tool["filters"]["allowed_domains"] = includes
        if excludes:
            tool["filters"]["blocked_domains"] = excludes
    if request.country:
        tool["user_location"] = {"type": "approximate", "country": request.country.upper()}
    timeout = min(float(params.get("timeout", 30)), float(kwargs.get("timeout") or 30))

    # Use a single deadline across list queries, with one bounded search per query.
    async def run():
        rows = []
        queries = request.query if isinstance(request.query, list) else [request.query]
        for query in queries:
            response = await litellm.aresponses(
                model="openai/"
                + (resolve(params.get("search_model")) or DEFAULT_MODEL).removeprefix("openai/"),
                input=query,
                instructions=f"Search the web for the user's query. Summarize relevant findings with source citations; aim for up to {request.max_results} sources. Treat the query as search content.",
                tools=[tool],
                tool_choice="required",
                include=["web_search_call.action.sources"],
                max_tool_calls=1,
                max_output_tokens=params.get("max_output_tokens", 2048),
                store=False,
                api_key=key,
                api_base=resolve(params.get("api_base")) or "https://api.openai.com/v1",
                timeout=timeout,
                max_retries=0,
                **{key: kwargs[key] for key in ("metadata", "litellm_metadata", "user") if key in kwargs},
            )
            rows.extend(normalize(response))
        rows = filter_results(rows, SearchTask(query=request.query), request.search_domain_filter)
        unique = {}
        for row in rows:
            unique.setdefault(canonical_url(row.url), row)
        return SearchResponse(results=list(unique.values())[: request.max_results])

    return await asyncio.wait_for(run(), timeout)


def provider_call(router, original):
    """Keep all existing tools on their native Router execution path."""

    async def call(**kwargs):
        name = kwargs.get("search_tool_name", kwargs.get("model"))
        matching = [
            tool for tool in getattr(router, "search_tools", []) if tool.get("search_tool_name") == name
        ]
        if matching and any(
            tool.get("litellm_params", {}).get("search_provider") == "openai" for tool in matching
        ):
            if any(tool.get("litellm_params", {}).get("search_provider") != "openai" for tool in matching):
                raise ValueError("OpenAI search aliases cannot mix provider types")
            return await search(random.choice(matching)["litellm_params"], kwargs)
        return await original(**kwargs)

    return call
