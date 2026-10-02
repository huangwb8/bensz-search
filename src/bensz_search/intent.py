"""Cheap, auditable rules. Natural language profiles are a limited heuristic."""

import re

from .models import SearchRequest, SearchTask

RULES = [
    (
        "deep",
        r"\b(deep research|comprehensive|systematic review|exhaustive|in.depth|landscape|compare all)\b|全面调研|深入研究|系统综述|全景",
    ),
    (
        "coding",
        r"\b(github|source code|api reference|documentation|sdk|python|javascript|typescript|rust|debug|stacktrace|litellm|asyncio|docker|kubernetes|sql|programming)\b|源码|编程|代码|开发文档",
    ),
    (
        "people",
        r"\b(linkedin|biography|who is|person|people|profile of|researcher profile|contact details|founder of|ceo of|author biography)\b|人物|个人简介|履历|创始人",
    ),
    (
        "academic",
        r"\b(ctdna|biomedical|clinical|trial|pubmed|arxiv|academic|scholar|paper|papers|literature|primary literature|meta.analysis|randomized|cancer|research agent|scientific)\b|论文|临床|学术|科研|文献|肿瘤",
    ),
    (
        "news",
        r"\b(today|breaking|latest news|this week|released|launched|announced|news|headlines|yesterday|current events)\b|今日|今天|新闻|最新消息|突发",
    ),
]
PROFILE_TYPES = {
    "scientific_research": "academic",
    "scholar": "academic",
    "deep_research": "deep",
    "documentation": "coding",
    "factual": "general",
}


def classify(text: str) -> str:
    for intent, pattern in RULES:
        if re.search(pattern, text, re.I):
            return intent
    return "general"


def analyze(request: SearchRequest) -> SearchTask:
    profile = request.profile
    constraints = request.constraints
    query_text = " ".join(request.query) if isinstance(request.query, list) else request.query
    prompt = request.profile_prompt or ""
    reasons = []
    if profile.intent != "auto":
        intent = profile.intent
        reasons.append("structured profile intent takes precedence")
    elif profile.type != "auto":
        intent = PROFILE_TYPES.get(profile.type, profile.type)
        if intent not in {"general", "news", "academic", "deep", "people", "coding"}:
            intent = classify(profile.type)
        reasons.append("intent inferred from structured caller type")
    elif prompt and classify(prompt) != "general":
        intent = classify(prompt)
        reasons.append("profile_prompt interpreted using limited keyword rules")
    else:
        intent = classify(query_text)
        reasons.append("intent inferred using deterministic query rules")
    domain = profile.domain
    if domain == "auto" and re.search(
        r"biomedical|ctdna|clinical|cancer|pubmed|生物医学|肿瘤", prompt + " " + query_text, re.I
    ):
        domain = "biomedical"
    recall = constraints.recall
    if recall == "auto" and re.search(r"high recall|comprehensive|高召回", prompt, re.I):
        recall = "high"
    authority = constraints.authority
    if authority == "auto" and re.search(r"authoritative|primary literature|权威", prompt, re.I):
        authority = "high"
    freshness = constraints.freshness
    if freshness == "auto":
        freshness = (
            "day" if re.search(r"today|breaking|今天|突发", query_text, re.I) and intent == "news" else "any"
        )
    if intent in {"academic", "deep", "people"}:
        reasons.append("semantic retrieval preferred")
    if recall == "high":
        reasons.append("high recall requested")
    if freshness != "any":
        reasons.append(f"freshness window requested: {freshness}")
    latency = constraints.latency_budget_ms
    cost = constraints.cost_budget_usd
    return SearchTask(
        query=request.query,
        intent=intent,
        domain=domain,
        freshness=freshness,
        authority_requirement=authority,
        recall_requirement=recall,
        precision_requirement=constraints.precision,
        semantic_requirement=constraints.semantic,
        source_diversity=constraints.source_diversity,
        latency_budget_ms=latency
        if latency is not None
        else {"low": 2500, "high": 15000}.get(constraints.latency, 8000),
        cost_budget_usd=cost
        if cost is not None
        else {"low": 0.005, "high": 0.05}.get(constraints.cost, 0.02),
        result_count=request.max_results,
        caller_profile=profile,
        routing_reason=reasons,
        prefer_single=constraints.cost == "low"
        or constraints.latency == "low"
        or constraints.precision == "high",
    )
