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
            key = canonical_url(url)
            if key not in documents:
                key = next(
                    (
                        key2
                        for key2, document in documents.items()
                        if same_document(document["result"], result)
                    ),
                    key,
                )
            if key in seen:
                continue
            seen.add(key)
            document = documents.setdefault(
                key,
                {
                    "result": result,
                    "families": {},
                    "providers": [],
                    "index": len(documents),
                    "contributions": {},
                },
            )
            if provider not in document["providers"]:
                document["providers"].append(provider)
            weight = weights.get(provider, 1) if mode == "weighted_rrf" else 1
            contribution = weight / (k + rank)
            family = families.get(provider, provider)
            document["families"][family] = max(document["families"].get(family, 0), contribution)
            document["contributions"][provider] = contribution
            for field in ("snippet", "date", "last_updated"):
                if not getattr(document["result"], field) and getattr(result, field):
                    setattr(document["result"], field, getattr(result, field))
    values = list(documents.values())
    if mode != "none":
        values.sort(key=lambda d: (-sum(d["families"].values()), d["index"]))
    trace = [
        {
            "url": d["result"].url,
            "score": sum(d["families"].values()),
            "providers": d["providers"],
            "family_contributions": d["families"],
            "provider_contributions": d["contributions"],
        }
        for d in values[:count]
    ]
    return [d["result"] for d in values[:count]], trace
