"""Synthetic HTTP protocols, not real search. Exercises unmodified LiteLLM adapters."""

import asyncio
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="bensz-search synthetic provider fixtures")


@app.get("/health")
async def health():
    return {"status": "ok", "synthetic": True}


@app.api_route("/{provider}", methods=["GET", "POST"])
@app.api_route("/{provider}/search", methods=["GET", "POST"])
async def search(provider: str, request: Request):
    params = dict(request.query_params) if request.method == "GET" else await request.json()
    query = params.get("query", params.get("q", ""))
    if isinstance(query, list):
        query = " ".join(query)
    if "demo-auth" in query and provider != "searxng":
        return JSONResponse({"error": "fixture authentication failure"}, status_code=401)
    if "demo-timeout" in query and provider == "exa":
        await asyncio.sleep(10)
    if "demo-empty" in query and provider != "searxng":
        rows = []
    else:
        today = datetime.now(UTC).date().isoformat()
        rows = [
            {
                "title": "Synthetic ctDNA primary study",
                "url": "https://example.org/paper/ctdna"
                + ("?utm_source=fixture" if provider == "exa" else ""),
                "snippet": "DEMO FIXTURE: not a real clinical study.",
                "date": today,
            },
            {
                "title": f"Synthetic {provider} independent result",
                "url": f"https://{provider}.example.org/unique",
                "snippet": "DEMO FIXTURE: protocol validation only.",
                "date": today,
            },
        ]
    if provider == "exa":
        return {"results": [{**r, "text": r["snippet"], "publishedDate": r["date"]} for r in rows]}
    if provider == "serper":
        return {"organic": [{**r, "link": r["url"]} for r in rows]}
    if provider == "brave":
        return {"web": {"results": [{**r, "description": r["snippet"], "page_age": r["date"]} for r in rows]}}
    if provider == "tavily":
        return {"results": [{**r, "content": r["snippet"]} for r in rows]}
    if provider == "searxng":
        return {"results": [{**r, "content": r["snippet"], "publishedDate": r["date"]} for r in rows]}
    return {"results": rows}
