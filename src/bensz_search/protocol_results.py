"""Enrich shared deterministic fusion with bounded, always-visible provenance."""

import hashlib

from .fusion import fuse
from .protocol_models import ProtocolResult, Source


def normalize_results(buckets, calls, registry, mode, count, snippet_limit):
    ordered = {c: buckets[c] for c in calls if c in buckets}
    warnings = []
    # Model-based search adapters must retain generated-summary classification.
    for call_id, rows in ordered.items():
        provider = registry.providers[calls[call_id].tool_id].provider
        for row in rows:
            if not getattr(row, "snippet_kind", None):
                row.snippet_kind = (
                    "generated_summary"
                    if provider == "openai"
                    else (
                        "page_excerpt"
                        if provider == "exa_ai" and row.snippet
                        else "search_summary"
                        if row.snippet
                        else "link_only"
                    )
                )
        # Skip oversized links rather than returning a cut URL that cannot be cited.
        ordered[call_id] = [r for r in rows if len(r.url) <= 4096]
        if len(ordered[call_id]) != len(rows):
            warnings.append(
                {
                    "code": "result_url_too_long",
                    "call_id": call_id,
                    "message": "Oversized citation links were omitted",
                }
            )
    results, trace = fuse(
        ordered,
        {k: c.weight for k, c in calls.items()},
        {k: registry.providers[c.tool_id].source_family for k, c in calls.items()},
        mode,
        count,
        scholarly=True,
    )
    enriched = []
    for row, item in zip(results, trace, strict=True):
        sources = [
            Source(
                call_id=s["provider"],
                tool_id=calls[s["provider"]].tool_id,
                engine_id=calls[s["provider"]].engine_id,
                rank=s["rank"],
                source_family=registry.providers[calls[s["provider"]].tool_id].source_family,
                snippet_kind=s["snippet_kind"],
                date=s["date"],
            )
            for s in item["sources"]
        ]
        identity = item["canonical_identity"]
        result_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        if len({s.date for s in sources if s.date}) > 1:
            warnings.append(
                {
                    "code": "date_conflict",
                    "result_id": result_id,
                    "message": "Sources report different dates; retained source dates",
                }
            )
        snippet = row.snippet or ""
        enriched.append(
            ProtocolResult(
                result_id=result_id,
                title=row.title[:500],
                url=row.url,
                canonical_identity=identity,
                aliases=item["aliases"],
                snippet=snippet[:snippet_limit],
                snippet_kind=row.snippet_kind,
                date=row.date,
                sources=sources,
                fusion_score=item["score"],
                truncated=len(snippet) > snippet_limit or len(row.title) > 500,
            )
        )
    return enriched, warnings
