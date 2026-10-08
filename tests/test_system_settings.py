"""Site metadata persistence, concurrent writes and management permissions."""

import secrets

import pytest
from test_admin import console as console
from test_admin import login

from bensz_search.admin_store import AdminStore
from bensz_search.settings import DEFAULT_SITE


def test_settings_permissions_and_public_metadata(console):
    assert console.get("/admin/api/settings").status_code == 401
    assert console.get("/admin/api/site").json() == DEFAULT_SITE
    headers = login(console)
    initial = console.get("/admin/api/settings").json()
    assert initial["settings"] == {**DEFAULT_SITE, "revision": 0}
    fields = {**DEFAULT_SITE, "site_name": "搜索中心", "expected_revision": 0}
    assert console.put("/admin/api/settings", json=fields).status_code == 403
    assert (
        console.put(
            "/admin/api/settings", headers={**headers, "Origin": "https://evil.example"}, json=fields
        ).status_code
        == 403
    )
    saved = console.put("/admin/api/settings", headers=headers, json=fields)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert console.get("/admin/api/site").json()["site_name"] == "搜索中心"
    assert set(console.get("/admin/api/site").json()) == set(DEFAULT_SITE)
    assert console.put("/admin/api/settings", headers=headers, json=fields).status_code == 409
    events = console.get("/admin/api/audit").json()["events"]
    assert any(e["object_type"] == "system_settings" and e["action"] == "update" for e in events)
    assert (
        console.post(
            "/admin/api/users",
            headers=headers,
            json={"username": "member", "password": "member-test-password", "role": "member"},
        ).status_code
        == 200
    )
    console.post("/admin/api/logout", headers=headers)
    headers = login(console, "member", "member-test-password")
    assert console.get("/admin/api/settings").status_code == 403
    assert console.put("/admin/api/settings", headers=headers, json=fields).status_code == 403
    assert console.get("/admin/api/site").status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("site_name", "   "),
        ("site_name", "x" * 61),
        ("default_language", "fr"),
        ("doc_url", "javascript:alert(1)"),
        ("support_url", "https://user:secret@example.org"),
        ("support_url", "https://example.org:invalid"),
        ("doc_url", "https://example.org/\nmalformed"),
    ],
)
def test_invalid_settings_leave_saved_values_unchanged(console, field, value):
    headers = login(console)
    response = console.put(
        "/admin/api/settings", headers=headers, json={**DEFAULT_SITE, "expected_revision": 0, field: value}
    )
    assert response.status_code == 422
    assert console.get("/admin/api/settings").json()["settings"]["revision"] == 0


def test_settings_survive_restart_and_reject_stale_store_write(tmp_path):
    path, secret = tmp_path / "settings.sqlite3", secrets.token_urlsafe(48)
    first = AdminStore(path, secret)
    second = AdminStore(path, secret)
    try:
        saved = first.save_system_settings({**DEFAULT_SITE, "doc_url": "https://docs.example.org"}, 0, None)
        assert second.system_settings() == saved
        with pytest.raises(ValueError, match="reload"):
            second.save_system_settings(DEFAULT_SITE, 0, None)
    finally:
        first.close()
        second.close()
    reopened = AdminStore(path, secret)
    try:
        assert reopened.system_settings() == saved
    finally:
        reopened.close()
