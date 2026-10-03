"""Operator-requested SearXNG metadata sync from the already configured address."""

from datetime import UTC, datetime

import httpx


async def verified_instance_engines(record):
    if record["provider"] != "searxng":
        raise ValueError("Engine selection requires SearXNG")
    headers = {"Authorization": "Bearer " + record["api_key"]} if record.get("api_key") else {}
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        response = await client.get(record["api_base"].rstrip("/") + "/config", headers=headers)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("engines"), list):
        raise ValueError("Invalid instance engine metadata")
    available = {
        e.get("name")
        for e in data["engines"]
        if isinstance(e, dict) and e.get("enabled", True) and not e.get("disabled", False)
    }
    engines = sorted(set(record.get("engines", [])) & available)
    return engines, (
        "Administrator allowlist intersected with instance /config; "
        "LiteLLM 1.103.2 engines parameter mapping; " + datetime.now(UTC).isoformat()
    )
