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
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from bensz_search.settings import DEFAULT_SITE

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
    personal_usage = {
        "summary": {**summary, "requests": 3},
        "by_provider": [{"name": "web-search", **summary, "requests": 3, "statuses": {"success": 3}}],
        "trend": [{"day": "2026-10-07", "requests": 3}],
        "recent": [],
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
            data["settings"] = {**DEFAULT_SITE, "revision": 0}
            control = {
                "authenticated": False,
                "expire_once": False,
                "error": False,
                "empty": False,
                "calls": [],
                "usage_days": [],
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
                            "query": parse_qs(urlsplit(request.url).query),
                            "method": method,
                            "body": request.post_data_json if request.post_data else None,
                        }
                    )
                if path == "/site":
                    payload = {key: value for key, value in data["settings"].items() if key != "revision"}
                elif path == "/settings" and method == "GET":
                    payload = {
                        "settings": data["settings"],
                        "deployment": {
                            "version": "1.0.5",
                            "session_lifetime_hours": 12,
                            "secure_cookies": False,
                        },
                    }
                elif path == "/settings" and method == "PUT":
                    fields = request.post_data_json
                    if fields.pop("expected_revision") != data["settings"]["revision"]:
                        route.fulfill(
                            status=409, json={"detail": "系统设置已被其他管理员更新，请重新加载后保存"}
                        )
                        return
                    data["settings"] = {**fields, "revision": data["settings"]["revision"] + 1}
                    payload = data["settings"]
                elif path in {"/login", "/session"}:
                    control["authenticated"] = True
                    payload = {
                        "user": data["user"],
                        "csrf_token": "synthetic",
                        "expires_at": time.time() + 12 * 3600,
                    }
                elif path == "/workspace":
                    payload = {
                        k: data["overview"][k]
                        for k in ("version", "providers", "enabled_count", "configured_count")
                    }
                elif path.startswith("/requests/"):
                    payload = data["overview"]["metrics"]["recent"][0]
                elif path == "/overview":
                    payload = data["overview"]
                elif path == "/usage/me":
                    control["usage_days"].append(parse_qs(urlsplit(request.url).query)["days"][0])
                    payload = data["personal_usage"]
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
                    params = parse_qs(urlsplit(request.url).query)
                    offset, limit = int(params.get("offset", [0])[0]), int(params.get("limit", [200])[0])
                    payload = {
                        "keys": data["keys"][offset : offset + limit],
                        "total": len(data["keys"]),
                        "limit": limit,
                        "active_count": sum(
                            not k.get("revoked")
                            and (not k.get("expires_at") or k["expires_at"] > time.time())
                            for k in data["keys"]
                        ),
                    }
                elif path.startswith("/keys/") and method == "DELETE":
                    key_id = path.removeprefix("/keys/")
                    if parse_qs(urlsplit(request.url).query).get("permanent") == ["true"]:
                        data["keys"] = [key for key in data["keys"] if key["id"] != key_id]
                    else:
                        for key in data["keys"]:
                            if key["id"] == key_id:
                                key["revoked"] = True
                    payload = {"ok": True}
                elif path == "/users":
                    payload = {"users": data["users"], "total": len(data["users"]), "limit": 50}
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
                page.wait_for_function(
                    "() => document.querySelector('#load-status')?.getAttribute('aria-busy') !== 'true'"
                )
                assert page.locator("#app-version").inner_text() == "v1.0.5"

            def delete_key(key_id, global_scope=False, page=page, control=control):
                action = page.locator(f'[data-action="key-delete"][data-value="{key_id}"]')
                action.locator("xpath=ancestor::details").locator("summary").click()
                calls_before = len(control["calls"])
                action.click()
                assert "无法恢复" in page.locator("#dialog").inner_text()
                page.locator('#confirm-form [data-action="dialog-close"]').click()
                assert len(control["calls"]) == calls_before
                assert action.count() == 1
                action.click()
                page.locator('#confirm-form button[type="submit"]').click()
                page.locator("#dialog").wait_for(state="hidden")
                action.wait_for(state="detached")
                call = control["calls"][-1]
                assert call["path"] == f"/keys/{key_id}" and call["method"] == "DELETE"
                assert call["query"] == {
                    "permanent": ["true"],
                    **({"scope": ["all"]} if global_scope else {}),
                }

            page.goto(base + "/admin/")
            page.locator("#login-form").wait_for()
            shot("login")
            page.fill("#username", "demo")
            page.fill("#password", "synthetic-password")
            page.locator('#login-form button[type="submit"]').click()
            page.locator('[data-testid="page-title"]').wait_for()
            assert page.locator("#app-version").inner_text() == "v1.0.5"
            page.locator(".trend-bar").first.wait_for()
            assert page.locator(".trend-bar").count() == 2
            if width > 720:
                assert page.locator('[data-action="menu"]').is_hidden()
            assert page.locator("nav#nav-admin a").count() == 7
            assert page.locator("nav#nav-user a").count() == 6
            if width <= 720:
                page.locator('[data-action="menu"]').click()
            assert page.locator('[data-action="nav-group"]').count() == 2
            for area in ["admin", "user"]:
                toggle = page.locator(f'[data-action="nav-group"][data-value="{area}"]')
                title_x = toggle.evaluate(
                    "node => node.getBoundingClientRect().x + parseFloat(getComputedStyle(node).paddingLeft)"
                )
                item_x = page.locator(f"#nav-{area} a > span").first.bounding_box()["x"]
                assert item_x - title_x >= 16, (name, area, title_x, item_x)
                toggle.focus()
                page.keyboard.press("Enter")
                assert toggle.get_attribute("aria-expanded") == "false"
                assert page.locator(f"#nav-{area}").is_hidden()
                assert page.locator(f"#nav-{'user' if area == 'admin' else 'admin'}").is_visible()
                page.keyboard.press("Enter")
                assert toggle.get_attribute("aria-expanded") == "true"
                assert page.locator(f"#nav-{area}").is_visible()
            shot("admin-navigation")
            if width <= 720:
                page.keyboard.press("Escape")
            shot("overview")
            for bad in ["constructor", "__proto__", "toString"]:
                page.evaluate("bad => history.pushState(null, '', '/admin/#' + bad)", bad)
                page.evaluate("dispatchEvent(new PopStateEvent('popstate'))")
                page.wait_for_function(
                    "() => document.querySelector('#load-status')?.getAttribute('aria-busy') !== 'true'"
                )
                assert page.locator('[data-testid="page-title"]').inner_text() == "运行概览"
            page.locator('[data-action="request-detail"]').click()
            page.locator(".timeline").wait_for()
            assert page.locator(".timeline").is_visible()
            shot("request")
            page.locator('#dialog [data-action="dialog-close"]').click()
            navigate("admin", "system")
            assert page.locator('[data-testid="page-title"]').inner_text() == "系统设置"
            assert (
                page.locator('[data-testid="nav-admin-providers"]').inner_text().strip("› \n") == "搜索引擎"
            )
            assert "搜索调试台" not in page.locator("#nav-admin").inner_text()
            assert "管理员密钥" in page.locator("#nav-admin").inner_text()
            page.fill("#site-name", "搜索中心")
            page.locator('[data-action="system-tab"][data-value="appearance"]').click()
            page.select_option("#theme", "dark")
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            shot("system-appearance")
            page.locator('[data-action="system-tab"][data-value="security"]').click()
            assert "/bensz-search/mcp" in page.locator("#system-security").inner_text()
            shot("system-security")
            page.locator('[data-action="system-tab"][data-value="site"]').click()
            assert page.input_value("#site-name") == "搜索中心"
            page.fill("#doc-url", "https://docs.example.org")
            page.locator('#system-form button[type="submit"]').click()
            page.wait_for_function("() => document.querySelector('#system-form').textContent.includes('r1')")
            assert page.title() == "系统设置 · 搜索中心"
            shot("system-site")
            page.fill("#site-name", "保留草稿")
            data["settings"]["revision"] = 2
            page.locator('#system-form button[type="submit"]').click()
            page.locator("#system-form .form-error").filter(has_text="其他管理员").wait_for()
            assert page.input_value("#site-name") == "保留草稿"
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator('#system-form [data-action="refresh"]').click()
            page.wait_for_function("() => document.querySelector('#system-form').textContent.includes('r2')")
            assert page.input_value("#site-name") == "搜索中心"
            page.locator('[data-action="system-tab"][data-value="appearance"]').click()
            page.select_option("#theme", "light")
            if args.system_only:
                report["viewports"].append(
                    {
                        "name": name,
                        "width": width,
                        "height": height,
                        "checks": [
                            "renamed navigation",
                            "settings tabs and draft preservation",
                            "browser theme",
                            "save and brand update",
                            "revision conflict and reload",
                            "deployment status",
                            "no horizontal overflow",
                        ],
                    }
                )
                page.close()
                continue
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
            navigate("admin", "keys")
            assert page.locator('[data-action="key-delete"]').count() == 2
            assert page.locator('[data-action="key-revoke"][data-value="old-key"]').count() == 0
            delete_key("key-fixture", global_scope=True)
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
            page.locator('[data-action="refresh"]').first.click()
            page.wait_for_function(
                "() => document.querySelector('#load-status')?.getAttribute('aria-busy') !== 'true'"
            )
            shot("empty")
            control["empty"] = False
            navigate("admin", "users")
            control["error"] = True
            navigate("admin", "providers")
            page.locator('[data-action="refresh"]').first.click()
            page.locator("#load-status").get_by_text("服务暂时不可用，请稍后重试。", exact=False).wait_for()
            shot("error")
            control["error"] = False
            page.locator('[data-action="refresh"]').first.click()
            page.locator('[data-testid="providers-table"]').wait_for()
            page.locator('[data-action="logout"]').click()
            page.locator("#login-form").wait_for()
            data["user"]["role"] = "member"
            page.fill("#username", "demo")
            page.fill("#password", "synthetic-password")
            page.locator('#login-form button[type="submit"]').click()
            page.wait_for_function(
                "() => document.querySelector('#load-status')?.getAttribute('aria-busy') !== 'true'"
            )
            for bad in ["constructor", "__proto__", "toString"]:
                page.evaluate("bad => history.pushState(null, '', '/app/#' + bad)", bad)
                page.evaluate("dispatchEvent(new PopStateEvent('popstate'))")
                page.wait_for_function(
                    "() => document.querySelector('#load-status')?.getAttribute('aria-busy') !== 'true'"
                )
                assert page.locator('[data-testid="page-title"]').inner_text() == "我的工作台"
            if width <= 720:
                page.locator('[data-action="menu"]').click()
            assert page.locator('[data-action="nav-group"]').count() == 0
            assert page.locator("#nav-admin").count() == 0
            assert page.locator("nav#nav-user a").count() == 6
            nav_x = page.locator("#navigation").bounding_box()["x"]
            link_x = page.locator("#nav-user a").first.bounding_box()["x"]
            assert abs(link_x - nav_x) < 1, (name, nav_x, link_x)
            assert page.locator('[data-testid="nav-user-overview"]').get_attribute("aria-current") == "page"
            shot("member-navigation")
            if width <= 720:
                page.keyboard.press("Escape")
            usage = page.locator('[data-testid="personal-provider-usage"]')
            assert usage.get_by_text("web-search", exact=True).count() == 1
            assert usage.get_by_text("local-search", exact=True).count() == 0
            assert page.locator('[name="user-metrics-window"]').input_value() == "7d"
            page.select_option('[name="user-metrics-window"]', "30d")
            page.locator('[data-testid="personal-metric-scope"]').get_by_text("近 30", exact=False).wait_for()
            assert control["usage_days"][-1] == "30"
            shot("member-usage-30d")
            saved_usage = data["personal_usage"]
            data["personal_usage"] = {"summary": {"requests": 0}, "by_provider": [], "trend": []}
            page.locator('[data-action="refresh"]').first.click()
            usage.get_by_text("暂无服务统计", exact=True).wait_for()
            shot("member-usage-empty")
            data["personal_usage"] = saved_usage
            navigate("user", "keys")
            delete_key("old-key")
            assert page.locator('[data-action="key-delete"]').count() == 0
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
                        "active/revoked key deletion, cancellation, owner/admin scope and list refresh",
                        "XSS escaping",
                        "empty/error",
                        "theme",
                        "real sidebar navigation",
                        "admin nested navigation and keyboard group toggles",
                        "member flat navigation without group toggles",
                        "admin/member prototype route fallback",
                        "cancelled navigation restores URL",
                        "session refresh preserves password form",
                        "cross-area brand version",
                        "personal provider usage, 7/30 day selection and empty state",
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
    parser.add_argument(
        "--system-only", action="store_true", help="Run the system settings checks in all three viewports"
    )
    default_browser = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    parser.add_argument("--browser", default=default_browser if Path(default_browser).exists() else None)
    run(parser.parse_args())
