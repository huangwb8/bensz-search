import httpx
import pytest

from bensz_search.engine_metadata import verified_instance_engines


async def test_instance_metadata_intersection_excludes_disabled_and_unallowed(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "engines": [
                    {"name": "github", "enabled": True},
                    {"name": "pubmed", "disabled": True},
                    {"name": "arxiv", "enabled": True},
                    {"name": "bing", "enabled": False},
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "bensz_search.engine_metadata.httpx.AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    engines, evidence = await verified_instance_engines(
        {
            "provider": "searxng",
            "api_base": "http://instance.local",
            "api_key": "private-key",
            "engines": ["github", "pubmed", "bing"],
        }
    )
    assert engines == ["github"]
    assert requests[0].url.path == "/config"
    assert "private-key" not in evidence and "instance.local" not in evidence


async def test_non_searxng_cannot_claim_selectable_engines():
    with pytest.raises(ValueError):
        await verified_instance_engines({"provider": "brave"})
