"""Stable rank fusion. A source family contributes at most one vote per document."""

import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit

from litellm.llms.base_llm.search.transformation import SearchResult

TRACKERS = {
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "msclkid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref_src",
    "ref_url",
    "_hsenc",
    "_hsmi",
}


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = parts.port
    if port and not ((parts.scheme == "https" and port == 443) or (parts.scheme == "http" and port == 80)):
        host += f":{port}"
    path = parts.path.rstrip("/")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKERS
    )
    return host + path + ("?" + urlencode(query) if query else "")


def title_key(title):
    return re.sub(r"\W+", " ", title.casefold()).strip()


def document_identity(result):
    """Only authoritative identifiers/URL namespaces; never title-only cross-site merges."""
    parts = urlsplit(result.url)
    host = (parts.hostname or "").lower()
    doi = getattr(result, "doi", None)
    if host in {"doi.org", "dx.doi.org"}:
        doi = parts.path.lstrip("/")
    if isinstance(doi, str) and re.fullmatch(r"10\.\d{4,9}/[^\s?#]+", doi, re.I):
        return "doi:" + doi.lower()
    pmid = getattr(result, "pmid", None)
    if host == "pubmed.ncbi.nlm.nih.gov":
        pmid = parts.path.strip("/")
    elif host in {"www.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"} and parts.path.startswith("/pubmed/"):
        pmid = parts.path.removeprefix("/pubmed/").strip("/")
    if isinstance(pmid, (int, str)) and re.fullmatch(r"\d{1,10}", str(pmid)):
        return "pmid:" + str(pmid)
    arxiv = getattr(result, "arxiv_id", None)
    if host in {"arxiv.org", "www.arxiv.org"} and parts.path.startswith(("/abs/", "/pdf/")):
        arxiv = parts.path[5:].removesuffix(".pdf")
    # Keep explicit versions separate; absent version is not assumed to be v1.
    if isinstance(arxiv, str) and re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?", arxiv):
        return "arxiv:" + arxiv
    return None


def same_document(a: SearchResult, b: SearchResult) -> bool:
    pa, pb = urlsplit(a.url), urlsplit(b.url)
    # Same domain alone is not enough. Keep meaningful query variants / pagination.
    if pa.hostname != pb.hostname or pa.query != pb.query:
        return False
    ta, tb = title_key(a.title), title_key(b.title)
    if len(ta) < 20 or len(tb) < 20:
        return False

    # Conservative same-document alternative: .html/.pdf/amp versions of same path.
    def stem(path):
        return re.sub(r"(?:\.html?|\.pdf|/amp)$", "", path.rstrip("/"))

    return stem(pa.path) == stem(pb.path) and SequenceMatcher(None, ta, tb).ratio() >= 0.96


def fuse(
    buckets: dict[str, list[SearchResult]],
    weights: dict[str, float],
    families: dict[str, str],
    mode: str,
    count: int,
    k=60,
    scholarly=False,
):
    documents = {}
    for provider, results in buckets.items():
        seen = set()
        for rank, raw in enumerate(results, start=1):
            result = raw.model_copy(deep=True)
            hinted = getattr(result, "canonical_url", None)
            # Trust a canonical hint only if it stays on the result host.
            url = (
                hinted
                if isinstance(hinted, str) and urlsplit(hinted).hostname == urlsplit(result.url).hostname
                else result.url
            )
            key = (document_identity(result) if scholarly else None) or canonical_url(url)
            if key not in documents:
                key = next(
                    (
                        key2
                        for key2, document in documents.items()
                        if same_document(document["result"], result)
                    ),
                    key,
                )
            duplicate = key in seen
            seen.add(key)
            document = documents.setdefault(
                key,
                {
                    "result": result,
                    "families": {},
                    "providers": [],
                    "index": len(documents),
                    "contributions": {},
                    "sources": [],
                    "aliases": [],
                    "identity": key,
                },
            )
            document["sources"].append(
                {
                    "provider": provider,
                    "rank": getattr(result, "original_rank", rank),
                    "snippet_kind": getattr(result, "snippet_kind", "search_summary"),
                    "date": result.date,
                    "upstream_sources": getattr(result, "upstream_sources", []),
                }
            )
            if result.url not in document["aliases"]:
                document["aliases"].append(result.url)
            if provider not in document["providers"]:
                document["providers"].append(provider)
            weight = weights.get(provider, 1) if mode == "weighted_rrf" else 1
            contribution = weight / (k + rank)
            leaf_families = getattr(result, "source_families", None) or [families.get(provider, provider)]
            if not duplicate:
                # An aggregate gets one vote split across its declared leaf families.
                # Two remote instances backed by the same source never create two votes.
                for family in leaf_families:
                    document["families"][family] = max(
                        document["families"].get(family, 0), contribution / len(leaf_families)
                    )
                document["contributions"][provider] = contribution
            for field in ("snippet", "date", "last_updated"):
                if not getattr(document["result"], field) and getattr(result, field):
                    setattr(document["result"], field, getattr(result, field))
                    if field == "snippet":
                        document["result"].snippet_kind = getattr(result, "snippet_kind", "search_summary")
    values = list(documents.values())
    for document in values:
        document["result"].source_families = sorted(document["families"])
        # Preserve every merged branch for legacy responses and the next federation hop.
        document["result"].upstream_sources = [
            source
            for item in document["sources"]
            for source in (
                item["upstream_sources"]
                or [
                    {
                        "source_family": families.get(item["provider"], item["provider"]),
                        "snippet_kind": item["snippet_kind"],
                        "date": item["date"],
                        "upstream_tool_id": item["provider"],
                        "upstream_call_id": item["provider"],
                        "upstream_rank": item["rank"],
                        "instance_path": [],
                    }
                ]
            )
        ][:30]
    if mode != "none":
        values.sort(key=lambda d: (-sum(d["families"].values()), d["index"]))
    trace = [
        {
            "url": d["result"].url,
            "score": sum(d["families"].values()),
            "providers": d["providers"],
            "family_contributions": d["families"],
            "provider_contributions": d["contributions"],
            "canonical_identity": d["identity"],
            "sources": d["sources"],
            "aliases": d["aliases"],
        }
        for d in values[:count]
    ]
    return [d["result"] for d in values[:count]], trace
