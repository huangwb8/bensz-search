"""Safe adapter mappings based on the pinned LiteLLM 1.103.2 implementation."""

from .filters import provider_options

ADAPTER_EVIDENCE = "LiteLLM 1.103.2 llms/{provider}/search/transformation.py; offline mapping verified"


def contract(capability):
    provider = capability.provider
    return {
        "input_forms": capability.query_dialects,
        "max_query_length": capability.query_max_length,
        "max_queries_per_call": 1,
        "max_results": 20,
        "operators": {"boolean": "unknown", "field_search": "unknown", "quotes": "unknown"},
        "options": {
            "search_domain_filter": "post_filter",
            "freshness": "post_filter",
            "country": "native" if provider in {"exa_ai", "perplexity", "serper"} else "unsupported",
            "query_language": "advisory",
            "result_language": "native" if provider in {"searxng", "serper"} else "unsupported",
            "safe_search": "native" if provider in {"searxng", "serper"} else "unsupported",
        },
        "examples": ["colorectal cancer ctDNA", "Python reproducible analysis"],
        "common_errors": [
            "Do not infer verified field syntax from an engine name.",
            "Do not submit credentials, URLs, provider options or query arrays.",
        ],
        "evidence": ADAPTER_EVIDENCE.format(provider=provider),
        "last_verified": "2026-10-03",
        "verification_scope": "adapter transformation; live query semantics not guaranteed",
    }


def map_options(capability, options, task):
    kwargs = provider_options(capability.provider, task)
    # Domains use a deterministic post filter: several native adapters append clauses,
    # cannot handle negative domains, or otherwise alter the submitted query.
    if options.country:
        kwargs["country"] = options.country
    if options.result_language:
        kwargs["language" if capability.provider == "searxng" else "hl"] = options.result_language
    if options.safe_search:
        kwargs["safesearch" if capability.provider == "searxng" else "safe"] = (
            {"off": 0, "moderate": 1, "strict": 2}[options.safe_search]
            if capability.provider == "searxng"
            else "off"
            if options.safe_search == "off"
            else "active"
        )
    return kwargs
