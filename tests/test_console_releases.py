"""Release hints are bounded, cached, public and never suggest a downgrade."""

import httpx
import pytest
from test_admin import console as console
from test_admin import login


@pytest.mark.parametrize("tag,newer", [("v99.0.0", True), ("v0.0.1", False)])
def test_release_feed_is_public_cached_and_ordered(console, monkeypatch, tag, newer):
    login(console)
    calls = []

    async def send(client, request, **kwargs):
        calls.append(request)
        assert str(request.url) == "https://api.github.com/repos/huangwb8/bensz-search/releases/latest"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert not request.content
        return httpx.Response(200, json={"tag_name": tag}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    for _ in range(2):
        response = console.get("/admin/api/releases")
        assert response.status_code == 200
        assert response.json()["update_available"] is newer
        assert response.json()["update_check"] == "checked"
    assert len(calls) == 1
    notes = console.get(response.json()["changelog_url"])
    assert notes.status_code == 200
    assert "1.0.5" in notes.text


def test_release_feed_failure_keeps_console_available(console, monkeypatch):
    login(console)

    async def send(client, request, **kwargs):
        raise httpx.ConnectError("synthetic failure; no outgoing credentials", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    response = console.get("/admin/api/releases")
    assert response.status_code == 200
    assert response.json()["update_check"] == "unavailable"
    assert response.json()["latest_version"] is None
    assert not response.json()["update_available"]
    assert "synthetic failure" not in response.text
