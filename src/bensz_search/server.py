"""Boot the native LiteLLM proxy and install the search extension in its lifespan."""

import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import litellm
import yaml
from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from litellm.proxy import proxy_server as proxy
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth

from .admin import initialize_admin, managed_api_auth
from .admin import router as admin_router
from .integration import SearchInputMiddleware, install
from .mcp_transport import MCPTransport, create_manager
from .models import SearchResultFeedback
from .protocol import ProtocolFailure
from .protocol_http import load_team, permission_snapshot
from .protocol_http import router as protocol_router
from .registry import Registry


def effective_config():
    path = Path(os.getenv("BENSZ_SEARCH_CONFIG", "config/litellm.yaml"))
    data = yaml.safe_load(path.read_text())
    tools = []
    for tool in data.get("search_tools", []):
        if tool.get("search_tool_name") == "auto":
            raise RuntimeError("auto is reserved; remove it from the physical search_tools list")
        params = tool.get("litellm_params", {})
        credential = params.get("api_key")
        if (
            isinstance(credential, str)
            and credential.startswith("os.environ/")
            and not os.getenv(credential.split("/", 1)[1])
        ):
            continue
        if params.get("search_provider") == "searxng":
            base = params.get("api_base", "")
            if not base or (base.startswith("os.environ/") and not os.getenv(base.split("/", 1)[1])):
                continue
        tools.append(tool)
    production = os.getenv("BENSZ_SEARCH_MODE", "production") == "production"
    if not tools and not production:
        raise RuntimeError(
            "Configure at least one provider credential or SEARXNG_API_BASE; use compose demo for fixtures"
        )
    # Logical alias for original endpoint metadata/authorization, never executed as a provider.
    data["search_tools"] = tools + [
        {
            "search_tool_name": "auto",
            "litellm_params": {"search_provider": "searxng"},
            "search_tool_info": {"description": "bensz-search logical planner"},
        }
    ]
    master = data.get("general_settings", {}).get("master_key") or os.getenv("LITELLM_MASTER_KEY")
    if isinstance(master, str) and master.startswith("os.environ/"):
        master = os.getenv(master.split("/", 1)[1])
    if not isinstance(master, str) or not master.strip():
        raise RuntimeError("Set LITELLM_MASTER_KEY before starting the gateway")
    if production:
        if len(master) < 32 or master == "sk-bensz-search-local-demo":
            raise RuntimeError("Production requires a fresh LITELLM_MASTER_KEY of at least 32 characters")
        for tool in tools:
            params = tool["litellm_params"]
            resolved = {}
            for key in ("api_key", "api_base"):
                value = params.get(key, "")
                resolved[key] = (
                    os.getenv(value.split("/", 1)[1], "") if value.startswith("os.environ/") else value
                )
            if resolved["api_key"] == "demo-fixture" or urlsplit(resolved["api_base"]).hostname == "fixtures":
                raise RuntimeError("Fixture search providers are forbidden in production")
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", prefix="bensz-search-", delete=False)
    with handle:
        yaml.safe_dump(data, handle)
    return handle.name


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("bensz_search").setLevel(logging.INFO)

app = proxy.app
upstream_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    config_path = effective_config()
    old_config = os.environ.get("CONFIG_FILE_PATH")
    os.environ["CONFIG_FILE_PATH"] = config_path
    old_auth = proxy.user_custom_auth
    runtime = None
    try:
        async with upstream_lifespan(application) as state:
            registry = Registry.load(os.getenv("BENSZ_SEARCH_CAPABILITIES", "config/capabilities.yaml"))
            smart, original, callback = install(proxy, registry)
            litellm.callbacks.append(callback)
            application.state.smart_search = smart
            try:
                if os.getenv("BENSZ_SEARCH_MODE", "production") == "production":
                    runtime = initialize_admin(
                        application, proxy, registry, callback, proxy.llm_router.search_tools
                    )
                    proxy.user_custom_auth = managed_api_auth
                application.state.search_mcp = create_manager()
                async with application.state.search_mcp.run():
                    yield state
            finally:
                proxy.llm_router.asearch = original
                litellm.callbacks.remove(callback)
                proxy.user_custom_auth = old_auth
                if runtime:
                    runtime.store.close()
                application.state.admin_runtime = None
    finally:
        Path(config_path).unlink(missing_ok=True)
        if old_config is None:
            os.environ.pop("CONFIG_FILE_PATH", None)
        else:
            os.environ["CONFIG_FILE_PATH"] = old_config


app.router.lifespan_context = lifespan
app.add_middleware(SearchInputMiddleware, default_tool=os.getenv("BENSZ_SEARCH_DEFAULT_TOOL", "auto"))

static_path = Path(__file__).parent / "static"
app.include_router(admin_router)
app.include_router(protocol_router)
app.mount("/bensz-search/mcp", MCPTransport(), name="bensz-search-mcp")
if static_path.exists():
    app.mount("/admin/static", StaticFiles(directory=static_path), name="admin-static")

# Reuse upstream API documentation, give the main browser entry to the product console.
app.router.routes[:] = [
    route
    for route in app.router.routes
    if getattr(route, "name", "") != "swagger_ui_html" and getattr(route, "path", "") != "/search/tools"
]


@app.get("/search/tools", tags=["search"])
async def native_tools(request: Request, user=Depends(user_api_key_auth)):
    from .integration import authorized_tools

    smart, allowed = await permission_snapshot(request, user, enforce_protocol=False)
    aliases = await authorized_tools({"auto"}, user, await load_team(user))
    return {
        "object": "list",
        "data": [
            {"search_tool_name": name, "search_provider": smart.registry.providers[name].provider}
            for name in sorted(allowed)
        ]
        + ([{"search_tool_name": "auto", "search_provider": "searxng"}] if aliases else []),
    }


@app.get("/", include_in_schema=False)
@app.get("/search", include_in_schema=False)
@app.get("/v1/search", include_in_schema=False)
async def browser_entry():
    return RedirectResponse("/admin", status_code=303)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi import Response

    return Response(status_code=204)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def console():
    return FileResponse(static_path / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/docs", include_in_schema=False)
async def api_docs():
    return get_swagger_ui_html(openapi_url=app.openapi_url, title="bensz-search API")


@app.get("/ready", include_in_schema=False)
async def readiness():
    runtime = getattr(app.state, "admin_runtime", None)
    if runtime:
        count = len(runtime.active_names())
    else:
        count = len(getattr(proxy.llm_router, "search_tools", [])) - 1
    ready = count > 0 and hasattr(app.state, "smart_search")
    return JSONResponse(
        {
            "status": "ready" if ready else "not_ready",
            "active_providers": max(0, count),
            "scope": "configuration; use provider tests to verify external retrieval",
        },
        status_code=200 if ready else 503,
    )


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError):
    # Validation errors can echo provider keys/passwords in their input payloads.
    if request.url.path.startswith("/bensz-search/"):
        field = ".".join(str(x) for x in error.errors()[0]["loc"])
        return JSONResponse(
            ProtocolFailure("invalid_plan", "Invalid search request", field).envelope().model_dump(),
            status_code=422,
        )
    return JSONResponse(
        {
            "detail": "; ".join(
                ".".join(str(part) for part in e["loc"]) + ": " + e["msg"] for e in error.errors()
            )
        },
        status_code=422,
    )


@app.exception_handler(ProtocolFailure)
async def protocol_error(request: Request, error: ProtocolFailure):
    return JSONResponse(
        error.envelope().model_dump(), status_code=error.status_code, headers={"Cache-Control": "no-store"}
    )


@app.get("/smart-search/metrics", dependencies=[Depends(user_api_key_auth)])
async def metrics(user=Depends(user_api_key_auth)):
    if getattr(user, "user_role", None) not in {"proxy_admin", "proxy_admin_viewer"}:
        raise HTTPException(403, "Router metrics require a proxy admin")
    return app.state.smart_search.telemetry.snapshot()


@app.post("/smart-search/feedback", dependencies=[Depends(user_api_key_auth)])
async def feedback(data: SearchResultFeedback, user=Depends(user_api_key_auth)):
    # Feedback is administrative until tenant-scoped storage is implemented.
    if getattr(user, "user_role", None) != "proxy_admin":
        raise HTTPException(403, "Router feedback requires a proxy admin in this release")
    try:
        app.state.smart_search.telemetry.feedback(data)
    except KeyError:
        raise HTTPException(404, "request_id not in recent history") from None
    return {"accepted": True, "persistent": False}
