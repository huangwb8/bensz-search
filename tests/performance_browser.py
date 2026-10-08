"""Browser timings under delayed synthetic APIs, navigation races and partition errors."""

import argparse
import asyncio
import copy
import json
import threading
import time
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright
from ui_smoke import Handler, fixtures


def stats(rows):
    rows = sorted(rows)
    return {
        "samples": len(rows),
        "p50_ms": round(rows[int((len(rows) - 1) * 0.5)], 2),
        "p95_ms": round(rows[int((len(rows) - 1) * 0.95)], 2),
        "max_ms": round(max(rows), 2),
    }


async def run(args):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    data = fixtures()
    counts, cancelled = Counter(), Counter()
    control = {"timeout": False, "logged": True}
    errors, long_tasks = [], []
    async with async_playwright() as playwright:
        launch = {"headless": True}
        if args.browser:
            launch["executable_path"] = args.browser
        browser = await playwright.chromium.launch(**launch)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("requestfailed", lambda request: cancelled.update([urlsplit(request.url).path]))
        await page.add_init_script("""window.longTasks = []; new PerformanceObserver(list => {
            window.longTasks.push(...list.getEntries().map(e => e.duration));
        }).observe({type: 'longtask', buffered: true});""")

        async def api(route):
            request = route.request
            path = urlsplit(request.url).path.removeprefix("/admin/api")
            counts[path] += 1
            if path == "/site":
                await asyncio.sleep(0.35)
                payload = {"site_name": "Configured Search", "default_language": "en"}
            elif path in {"/session", "/login"}:
                if not control["logged"] and path == "/session":
                    await route.fulfill(status=401, json={})
                    return
                control["logged"] = True
                payload = {"user": data["user"], "csrf_token": "synthetic", "expires_at": 9999999999}
            elif path == "/logout":
                control["logged"] = False
                payload = {"ok": True}
            else:
                try:
                    await asyncio.sleep(5.2 if control["timeout"] and path == "/usage/me" else 0.35)
                    if path == "/workspace":
                        payload = {
                            k: data["overview"][k]
                            for k in ["version", "providers", "configured_count", "enabled_count"]
                        }
                    elif path == "/overview":
                        payload = data["overview"]
                    elif path == "/providers":
                        payload = {"providers": data["providers"], "catalog": data["catalog"]}
                    elif path == "/keys":
                        params = parse_qs(urlsplit(request.url).query)
                        offset = int(params.get("offset", [0])[0])
                        limit = int(params.get("limit", [50])[0])
                        payload = {
                            "keys": data["keys"][offset : offset + limit],
                            "total": len(data["keys"]),
                            "active_count": 1,
                            "limit": limit,
                        }
                    elif path == "/users":
                        payload = {"users": data["users"], "total": len(data["users"]), "limit": 50}
                    elif path == "/usage/me":
                        payload = data["personal_usage"]
                    elif path == "/sessions":
                        payload = {"sessions": []}
                    else:
                        payload = {"ok": True}
                except Exception:
                    cancelled[path] += 1
                    return
            try:
                await route.fulfill(json=copy.deepcopy(payload))
            except Exception:
                cancelled[path] += 1

        await page.route("**/admin/api/**", api)
        boot_started = time.monotonic()
        await page.goto(base + "/admin/#search")
        await page.locator("#search-query").wait_for()
        boot_ms = (time.monotonic() - boot_started) * 1000
        assert boot_ms < 300, boot_ms
        await page.locator('#search-form button[type="submit"]:enabled').wait_for()
        assert (
            await page.locator('[data-testid="nav-admin-system"] span').first.inner_text()
            == "System settings"
        )
        assert await page.locator("[data-site-name]").first.inner_text() == "Configured Search"
        for target in ["overview", "providers", "keys", "users", "search"]:
            await page.locator(f'[data-testid="nav-admin-{target}"]').click()
            await page.wait_for_function(
                "() => document.querySelector('#load-status')?.getAttribute('aria-busy') !== 'true'"
            )
        warm, cold = [], []
        before = sum(counts.values())
        # Measure browser DOM event -> usable content entirely inside the browser.
        for index in range(100):
            target = ["keys", "providers", "search", "users"][index % 4]
            await page.evaluate(
                "target => { window.navStarted = performance.now(); document.querySelector(`[data-testid=nav-admin-${target}]`).click(); }",
                target,
            )
            await page.wait_for_function(
                "target => location.hash === '#' + target && !!document.querySelector('[data-testid=page-title]')",
                arg=target,
            )
            warm.append(await page.evaluate("performance.now() - window.navStarted"))
        warm_requests = sum(counts.values()) - before
        # Each re-login clears identity caches; the target form must not await 350ms config.
        await page.locator('[data-testid="nav-admin-search"]').click()
        for _ in range(100):
            await page.locator('[data-action="logout"]').click()
            await page.locator("#login-form").wait_for()
            await page.fill("#username", "demo")
            await page.fill("#password", "synthetic-password")
            await page.evaluate(
                "() => { window.navStarted = performance.now(); document.querySelector('#login-form button[type=submit]').click(); }"
            )
            await page.locator("#search-query").wait_for()
            cold.append(await page.evaluate("performance.now() - window.navStarted"))
            await page.locator('#search-form button[type="submit"]:enabled').wait_for()
        # Cancel unread navigation requests, preserve the final page and draft.
        await page.fill("#search-query", "Preserved draft")
        for _ in range(20):
            for target in ["keys", "users", "overview", "search"]:
                await page.locator(f'[data-testid="nav-admin-{target}"]').evaluate("node => node.click()")
                await asyncio.sleep(0.025)
        await asyncio.sleep(0.5)
        assert await page.locator("#search-query").input_value() == "Preserved draft"
        assert await page.locator('[data-testid="nav-admin-search"]').get_attribute("aria-current") == "page"
        # One timed-out personal statistic must leave the welcome and provider panel usable.
        control["timeout"] = True
        await page.locator('[data-testid="nav-user-overview"]').click()
        await page.locator(".personal-welcome").wait_for()
        await asyncio.sleep(5.5)
        assert await page.locator(".personal-welcome").is_visible()
        assert await page.locator('#load-status button[data-action="refresh"]').is_visible()
        assert await page.get_by_text("local-search", exact=True).count() >= 1
        control["timeout"] = False
        # Public list API work and DOM output remain bounded at larger sizes.
        lists = []
        for amount in [100, 1000, 5000]:
            data["keys"] = [
                {"id": str(i), "name": f"Key {i}", "prefix": "public", "scopes": ["search"], "created_at": i}
                for i in range(amount)
            ]
            await page.locator('[data-testid="nav-admin-keys"]').click()
            await page.locator('[data-action="refresh"]').first.click()
            await page.wait_for_function(
                "() => document.querySelector('#load-status')?.getAttribute('aria-busy') !== 'true'"
            )
            rows = await page.locator("#table-results tbody tr").count()
            assert rows == 50, (amount, rows)
            lists.append({"source_rows": amount, "rendered_rows": rows})
        long_tasks = await page.evaluate("window.longTasks")
        await browser.close()
    server.shutdown()
    report = {
        "api_delay_ms": 350,
        "cold_document_to_form_ms": round(boot_ms, 2),
        "public_metadata": "nonblocking; configured name and default language applied",
        "warm": stats(warm),
        "cold_form": stats(cold),
        "warm_requests": warm_requests,
        "cancelled": dict(cancelled),
        "large_lists": lists,
        "long_tasks_ms": long_tasks,
        "errors": errors,
        "partition_timeout": "other sections remained usable",
        "rapid_navigation_rounds": 20,
    }
    args.output.write_text(json.dumps(report, indent=2))
    assert not errors, errors
    assert report["warm"]["p95_ms"] <= 100, report["warm"]
    assert report["cold_form"]["p95_ms"] <= 150, report["cold_form"]
    assert warm_requests == 0, warm_requests
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    parser.add_argument("--browser", default=chrome if Path(chrome).exists() else None)
    asyncio.run(run(parser.parse_args()))
