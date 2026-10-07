"""Optional real-browser smoke with synthetic APIs, no credentials or live providers.

Run: python3 tests/ui_smoke.py --output .bensz-api/<task>/shared/ui
Requires Playwright and Chrome (or --browser executable).
"""

import argparse
import copy
import json
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/bensz_search/static"


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        name = Path(urlsplit(path).path).name
        return str(STATIC / (name if name in {p.name for p in STATIC.iterdir()} else "index.html"))

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, *args):
        pass


def fixtures():
    now = time.time()
    providers = [
        {
            "name": "local-search",
            "provider": "searxng",
            "enabled": True,
            "api_base": "https://search.example.org",
            "timeout_ms": 8000,
            "engines": ["bing"],
            "verified_engines": ["bing"],
            "engine_evidence": "synthetic instance /config",
            "health": {"state": "healthy"},
            "has_api_key": False,
        },
        {
            "name": "remote-search",
            "provider": "bensz_search",
            "enabled": False,
            "api_base": "https://remote.example.org",
            "timeout_ms": 15000,
            "estimated_cost_usd": 0.02,
            "health": {"state": "open", "cooldown_remaining_s": 30, "last_error": "quota"},
            "has_api_key": True,
        },
        {
            "name": "web-search",
            "provider": "openai",
            "enabled": True,
            "api_base": "",
            "timeout_ms": 30000,
            "health": {"state": "degraded"},
            "has_api_key": True,
        },
    ]
    catalog = [
        {
            "provider": "searxng",
            "label": "SearXNG",
            "requires_api_key": False,
            "default_engines": ["bing", "duckduckgo"],
        },
        {"provider": "openai", "label": "OpenAI Web Search", "requires_api_key": True},
        {"provider": "bensz_search", "label": "bensz-search", "requires_api_key": True},
    ]
    event = {
        "request_id": "req-synthetic-0001",
        "timestamp": now,
        "intent": "coding",
        "providers": ["local-search"],
        "result_count": 1,
        "attempts": [{"provider": "local-search", "status": "success", "latency_ms": 120, "result_count": 1}],
        "routing_reason": ["代码来源与权威性要求匹配"],
        "estimated_cost_usd": 0.001,
        "fusion_contribution": {"providers": {"local-search": 1}},
        "marginal_gain": {"local-search": 1},
    }
    summary = {
        "requests": 12,
        "success_rate": 0.92,
        "p50_ms": 200,
        "p95_ms": 800,
        "estimated_cost_usd": 0.024,
        "fallbacks": 1,
    }
    overview = {
        "version": "1.0.5",
        "providers": providers,
        "configured_count": 3,
        "enabled_count": 2,
        "health": [{"name": p["name"], **p["health"]} for p in providers],
        "metrics": {
            "summary": summary,
            "by_provider": [{"name": "local-search", **summary}],
            "trend": [{"day": "2026-10-06", "requests": 5}, {"day": "2026-10-07", "requests": 7}],
            "recent": [event],
        },
    }
    keys = [
        {
            "id": "key-fixture",
            "name": "Agent <script>window.xss=1</script>",
            "prefix": "synthetic",
            "username": "demo",
            "user_id": 1,
            "created_at": now - 3600,
            "last_used_at": now,
            "expires_at": now + 86400,
            "scopes": ["search"],
            "usage_count": 12,
            "revoked": False,
        },
        {
            "id": "old-key",
            "name": "Old key",
            "prefix": "synthetic",
            "username": "demo",
            "user_id": 1,
            "created_at": now - 7200,
            "revoked": True,
        },
    ]
    user = {"id": 1, "username": "demo", "role": "admin", "enabled": True, "created_at": now}
    users = [user, {"id": 2, "username": "member", "role": "member", "enabled": False, "created_at": now}]
    result = {
        "results": [
            {
                "title": "Python <script>window.xss=1</script>",
                "url": "https://python.org",
                "snippet": "Synthetic result. " * 40,
                "provider": "local-search",
            }
        ],
        "debug": event,
    }
    return locals()


def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    report = {
        "evidence": "real static assets, synthetic API responses; no live provider",
        "csp": "script/style/connect self; no unsafe-inline or unsafe-eval",
        "viewports": [],
        "errors": [],
        "checks": [],
    }
    with sync_playwright() as p:
        launch = {"headless": True}
        if args.browser:
            launch["executable_path"] = args.browser
        browser = p.chromium.launch(**launch)
        for width, height, name in [(1440, 900, "desktop"), (1024, 768, "tablet"), (390, 844, "mobile")]:
            data = fixtures()
            control = {
                "authenticated": False,
                "expire_once": False,
                "error": False,
                "empty": False,
                "calls": [],
            }
            page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.on(
                "console",
                lambda message: (
                    report["errors"].append(message.text)
                    if "Content Security Policy" in message.text
                    else None
                ),
            )

            def api(route, _request, data=data, control=control):
                request = route.request
                path = urlsplit(request.url).path.removeprefix("/admin/api")
                method = request.method
                if path == "/session" and not control["authenticated"]:
                    route.fulfill(status=401, json={"detail": "Session expired"})
                    return
                if control["expire_once"] and path.startswith("/providers/") and method == "PUT":
                    control["expire_once"] = False
                    route.fulfill(status=401, json={"detail": "Session expired"})
                    return
                if control["error"] and path == "/providers" and method == "GET":
                    route.fulfill(status=503, json={"detail": "Service unavailable"})
                    return
                if method in {"POST", "PUT", "DELETE"}:
                    control["calls"].append(
                        {
                            "path": path,
                            "method": method,
                            "body": request.post_data_json if request.post_data else None,
                        }
                    )
                if path in {"/login", "/session"}:
                    control["authenticated"] = True
                    payload = {
                        "user": data["user"],
                        "csrf_token": "synthetic",
                        "expires_at": time.time() + 12 * 3600,
                    }
                elif path == "/overview":
                    payload = data["overview"]
                elif path == "/providers" and method == "GET":
                    payload = {
                        "providers": [] if control["empty"] else data["providers"],
                        "catalog": data["catalog"],
                    }
                elif path == "/providers/export":
                    payload = {
                        "version": 1,
                        "providers": [
                            {
                                "name": "exported",
                                "provider": "searxng",
                                "api_base": "https://example.org",
                                "enabled": False,
                            }
                        ],
                    }
                elif path.endswith("/engines/sync"):
                    payload = {"verified_engines": ["bing"], "evidence": "synthetic /config evidence"}
                elif path.endswith("/test"):
                    payload = {
                        "ok": False,
                        "category": "quota",
                        "result_count": 0,
                        "results": [],
                        "latency_ms": 120,
                    }
                elif path == "/search":
                    payload = data["result"]
                elif path == "/keys" and method == "POST":
                    payload = {"key": "synthetic-key-not-a-credential"}
                elif path == "/keys":
                    payload = {"keys": data["keys"]}
                elif path == "/users":
                    payload = {"users": data["users"]}
                elif path == "/audit":
                    payload = {
                        "events": [
                            {
                                "id": 1,
                                "timestamp": time.time(),
                                "actor_id": 1,
                                "action": "update",
                                "object_type": "provider",
                                "object_id": "local-search",
                            }
                        ],
                        "total": 1,
                    }
                elif path == "/sessions":
                    payload = {
                        "sessions": [
                            {
                                "id": "synthetic-session",
                                "created_at": time.time(),
                                "expires_at": time.time() + 3600,
                                "current": True,
                            }
                        ]
                    }
                elif path == "/releases":
                    payload = {
                        "version": "1.0.5",
                        "documentation_url": "/api/docs",
                        "changelog_url": "/admin/changelog",
                    }
                else:
                    payload = {"ok": True}
                route.fulfill(json=copy.deepcopy(payload))

            page.route("**/admin/api/**", api)
            base = f"http://127.0.0.1:{server.server_port}"

            def shot(label, page=page, name=name):
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(args.output / f"{name}-{label}.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, label)

            def navigate(area, target, page=page, width=width):
                link = page.locator(f'[data-testid="nav-{area}-{target}"]')
                if width <= 720 and not link.is_visible():
                    page.locator('[data-action="menu"]').click()
                link.click()
                page.locator('[data-testid="page-title"]').wait_for()
                page.locator(".skeleton").wait_for(state="hidden")
                assert page.locator("#app-version").inner_text() == "v1.0.5"

            page.goto(base + "/admin/")
            page.locator("#login-form").wait_for()
            shot("login")
            page.fill("#username", "demo")
            page.fill("#password", "synthetic-password")
            page.locator('#login-form button[type="submit"]').click()
            page.locator('[data-testid="page-title"]').wait_for()
            assert page.locator("#app-version").inner_text() == "v1.0.5"
            assert page.locator(".trend-bar").count() == 2
            if width > 720:
                assert page.locator('[data-action="menu"]').is_hidden()
            assert page.locator("nav#nav-admin a").count() == 6
            assert page.locator("nav#nav-user a").count() == 6
            shot("overview")
            for bad in ["constructor", "__proto__", "toString"]:
                page.evaluate("bad => history.pushState(null, '', '/admin/#' + bad)", bad)
                page.evaluate("dispatchEvent(new PopStateEvent('popstate'))")
                page.locator(".skeleton").wait_for(state="hidden")
                assert page.locator('[data-testid="page-title"]').inner_text() == "运行概览"
            page.locator('[data-action="request-detail"]').click()
            assert page.locator(".timeline").is_visible()
            shot("request")
            page.locator('#dialog [data-action="dialog-close"]').click()
            for area, target in [
                ("admin", "providers"),
                ("admin", "keys"),
                ("admin", "users"),
                ("admin", "audit"),
                ("user", "overview"),
                ("user", "keys"),
                ("user", "settings"),
                ("user", "integration"),
                ("user", "help"),
            ]:
                navigate(area, target)
                shot(area + "-" + target)
            navigate("admin", "providers")
            page.locator('[data-action="provider-add"]').click()
            page.select_option("#provider-type", "bensz_search")
            assert page.locator("#provider-base").get_attribute("required") is not None
            assert page.locator("#searxng-options").is_hidden()
            assert page.locator("#provider-timeout").input_value() == "15000"
            page.fill("#provider-name", "new-remote")
            page.fill("#provider-base", "https://remote.example.org")
            shot("provider-drawer")
            # Session expiry preserves fields and retries the same save after login.
            page.locator('#provider-form button[value="save"]').click()
            page.locator("#dialog").wait_for(state="hidden")
            page.locator('[data-action="provider-edit"][data-value="local-search"]').click()
            page.fill("#provider-timeout", "9000")
            control["expire_once"] = True
            page.locator('#provider-form button[value="save"]').click()
            page.locator("#reauth-dialog").wait_for(state="visible")
            assert page.locator("#provider-timeout").input_value() == "9000"
            page.fill("#reauth-password", "synthetic-password")
            page.locator('#reauth-form button[type="submit"]').click()
            page.locator("#dialog").wait_for(state="hidden")
            assert control["calls"][-1]["body"]["timeout_ms"] == 9000
            assert "verified_engines" not in control["calls"][-1]["body"]
            page.locator('[data-action="provider-test"][data-value="local-search"]').click()
            assert page.locator("#test-query").get_attribute("maxlength") == "1000"
            page.locator('#test-form button[type="submit"]').click()
            page.locator("#test-results").get_by_text("额度不足，请检查余额或充值", exact=False).wait_for()
            shot("provider-test")
            page.locator('#dialog [data-action="dialog-close"]').click()
            page.locator('[data-action="provider-test"][data-value="local-search"]').click()
            assert "额度不足" in page.locator("#test-results").inner_text()
            page.locator('#dialog [data-action="dialog-close"]').click()
            navigate("admin", "search")
            page.fill("#search-query", "Python official documentation")
            page.locator("#search-form details > summary").click()
            page.fill('[name="search_domain_filter"]', "python.org, -example.com")
            page.select_option('[name="authority"]', "high")
            page.locator('#search-form button[type="submit"]').click()
            page.locator(".result").wait_for()
            assert control["calls"][-1]["body"]["constraints"]["authority"] == "high"
            assert control["calls"][-1]["body"]["search_domain_filter"] == ["python.org", "-example.com"]
            assert not page.evaluate("window.xss")
            shot("search")
            navigate("admin", "providers")
            navigate("admin", "search")
            assert page.locator(".result").is_visible()
            assert page.locator("#search-query").input_value() == "Python official documentation"
            navigate("user", "keys")
            page.locator('[data-action="key-create"]').click()
            page.fill("#key-name", "Test Agent")
            page.locator('#key-form button[type="submit"]').click()
            page.locator("#new-key").wait_for()
            shot("new-key")
            dismissed = []

            def dismiss_confirmation(d, dismissed=dismissed):
                dismissed.append(d.message)
                d.dismiss()

            page.on("dialog", dismiss_confirmation)
            page.keyboard.press("Escape")
            assert page.locator("#dialog").is_visible()
            assert dismissed
            page.remove_listener("dialog", dismiss_confirmation)
            page.locator('[data-action="key-done"]').click()
            navigate("admin", "users")
            page.locator('[data-action="user-edit"][data-value="2"]').click()
            page.fill("#new-password", "a-synthetic-new-password")
            shot("user-drawer")
            page.locator('#user-form button[type="submit"]').click()
            page.locator("#dialog").wait_for(state="hidden")
            if name == "mobile":
                page.locator('[data-action="menu"]').click()
                assert page.locator(".nav-backdrop").is_visible()
                shot("navigation")
                page.keyboard.press("Escape")
                assert page.locator(".nav-backdrop").is_hidden()
            navigate("user", "settings")
            page.fill('[name="current_password"]', "preserved-unsaved-password")

            def dismiss_unsaved(dialog):
                dialog.dismiss()

            page.on("dialog", dismiss_unsaved)
            page.evaluate(
                "history.pushState(null, '', '/admin/#providers'); dispatchEvent(new PopStateEvent('popstate'))"
            )
            assert page.url.endswith("/app/#settings")
            assert page.locator('[name="current_password"]').input_value() == "preserved-unsaved-password"
            page.remove_listener("dialog", dismiss_unsaved)
            page.locator('[data-action="sessions-revoke"]').click()
            page.locator('#confirm-form button[type="submit"]').click()
            page.locator("#dialog").wait_for(state="hidden")
            assert page.locator('[name="current_password"]').input_value() == "preserved-unsaved-password"
            page.select_option('[name="theme"]', "dark")
            shot("dark")
            page.select_option('[name="theme"]', "light")
            control["empty"] = True

            def accept_unsaved(dialog):
                dialog.accept()

            page.on("dialog", accept_unsaved)
            navigate("admin", "providers")
            page.remove_listener("dialog", accept_unsaved)
            shot("empty")
            control["empty"] = False
            navigate("admin", "users")
            control["error"] = True
            navigate("admin", "providers")
            page.get_by_text("无法加载", exact=True).wait_for()
            shot("error")
            control["error"] = False
            page.locator('[data-action="refresh"]').click()
            page.locator('[data-testid="providers-table"]').wait_for()
            page.locator('[data-action="logout"]').click()
            page.locator("#login-form").wait_for()
            data["user"]["role"] = "member"
            page.fill("#username", "demo")
            page.fill("#password", "synthetic-password")
            page.locator('#login-form button[type="submit"]').click()
            page.locator(".skeleton").wait_for(state="hidden")
            for bad in ["constructor", "__proto__", "toString"]:
                page.evaluate("bad => history.pushState(null, '', '/app/#' + bad)", bad)
                page.evaluate("dispatchEvent(new PopStateEvent('popstate'))")
                page.locator(".skeleton").wait_for(state="hidden")
                assert page.locator('[data-testid="page-title"]').inner_text() == "我的工作台"
            report["viewports"].append(
                {
                    "name": name,
                    "width": width,
                    "height": height,
                    "overflow": False,
                    "requests": len(control["calls"]),
                }
            )
            report["checks"].append(
                {
                    "viewport": name,
                    "passed": [
                        "all pages",
                        "drawers",
                        "reauth preserves form",
                        "query constraints",
                        "search/test retention",
                        "one-time key guard",
                        "XSS escaping",
                        "empty/error",
                        "theme",
                        "real sidebar navigation",
                        "admin/member prototype route fallback",
                        "cancelled navigation restores URL",
                        "session refresh preserves password form",
                        "cross-area brand version",
                    ],
                }
            )
            page.close()
        browser.close()
    server.shutdown()
    assert not report["errors"], report
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    default_browser = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    parser.add_argument("--browser", default=default_browser if Path(default_browser).exists() else None)
    run(parser.parse_args())
