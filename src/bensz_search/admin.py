"""Authenticated management API and native LiteLLM runtime configuration."""

import asyncio
import hmac
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

import litellm
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from litellm.proxy._types import UserAPIKeyAuth
from pydantic import Field, field_validator, model_validator

from . import __version__
from .admin_store import AdminStore, digest
from .integration import install
from .models import SearchRequest, StrictModel
from .openai_search import DEFAULT_MODEL, provider_call
from .registry import Registry
from .router import SearchFailed, failure_category

CATALOG = [
    {
        "provider": "openai",
        "label": "OpenAI Web Search",
        "requires_api_key": True,
        "default_api_base": "https://api.openai.com/v1",
    },
    {
        "provider": "exa_ai",
        "label": "Exa",
        "requires_api_key": True,
        "default_api_base": "https://api.exa.ai",
    },
    {"provider": "brave", "label": "Brave", "requires_api_key": True, "default_api_base": ""},
    {
        "provider": "tavily",
        "label": "Tavily",
        "requires_api_key": True,
        "default_api_base": "https://api.tavily.com",
    },
    {
        "provider": "serper",
        "label": "Serper",
        "requires_api_key": True,
        "default_api_base": "https://google.serper.dev",
    },
    {
        "provider": "perplexity",
        "label": "Perplexity",
        "requires_api_key": True,
        "default_api_base": "https://api.perplexity.ai",
    },
    {"provider": "searxng", "label": "SearXNG", "requires_api_key": False, "default_api_base": ""},
]


class Login(StrictModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


class NewUser(Login):
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(default="member", pattern=r"^(admin|member)$")


class PasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class ProviderInput(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    provider: str
    enabled: bool = True
    api_key: str = Field(default="", max_length=4096)
    api_base: str = Field(default="", max_length=2048)
    engines: list[str] = Field(default_factory=list, max_length=30)
    verified_engines: list[str] = Field(default_factory=list, max_length=30)
    engine_evidence: str | None = Field(default=None, max_length=1000)
    search_model: str = Field(
        default=DEFAULT_MODEL, min_length=1, max_length=128, pattern=r"^(openai/)?[a-zA-Z0-9_.-]+$"
    )
    search_context_size: str = Field(default="medium", pattern=r"^(low|medium|high)$")
    max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    timeout_ms: int = Field(default=10000, ge=100, le=60000)
    source_family: str | None = Field(default=None, min_length=1, max_length=64)
    estimated_cost_usd: float | None = Field(default=None, ge=0, le=10)

    @field_validator("name")
    @classmethod
    def reserved_name(cls, value):
        if value == "auto":
            raise ValueError("auto is reserved")
        return value

    @field_validator("engines")
    @classmethod
    def engine_names(cls, value):
        if any(not re.fullmatch(r"[a-zA-Z0-9_ .-]{1,80}", engine) for engine in value):
            raise ValueError("Invalid engine name")
        return value

    @model_validator(mode="after")
    def known_provider(self):
        if self.provider not in {row["provider"] for row in CATALOG}:
            raise ValueError("Unsupported search provider")
        if self.provider == "searxng" and not self.api_base:
            raise ValueError("SearXNG requires an API base URL")
        if self.verified_engines and (
            self.provider != "searxng"
            or not self.engine_evidence
            or not set(self.verified_engines) <= set(self.engines)
        ):
            raise ValueError("Verified engines require SearXNG, an enabled engine subset and evidence")
        if self.api_key == "demo-fixture":
            raise ValueError("Fixture providers cannot be used in the management console")
        if self.api_base:
            url = urlsplit(self.api_base)
            try:
                _ = url.port
            except ValueError as error:
                raise ValueError("Invalid API base URL") from error
            if (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("API base must be an HTTP(S) URL without credentials, query or fragment")
            if url.hostname.lower() == "fixtures" or self.api_key == "demo-fixture":
                raise ValueError("Fixture providers cannot be used in the management console")
        return self


class TestQuery(StrictModel):
    query: str = Field(default="Python", min_length=1, max_length=1000)


class KeyInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)


class AdminRuntime:
    def __init__(self, app, proxy, store, templates, callback):
        self.app, self.proxy, self.store, self.templates, self.callback = (
            app,
            proxy,
            store,
            templates,
            callback,
        )

    def capability(self, record):
        template = next(p for p in self.templates.providers.values() if p.provider == record["provider"])
        updates = {
            key: record[key]
            for key in ("timeout_ms", "source_family", "estimated_cost_usd")
            if record.get(key) is not None
        }
        if record["provider"] == "searxng":
            configured = set(record.get("engines", []))
            groups = {
                "academic": ["pubmed", "arxiv", "google scholar", "semantic scholar"],
                "coding": ["github", "gitlab", "stackoverflow"],
                "news": ["bing news", "google news", "brave.news"],
            }
            updates["intent_engines"] = {
                intent: [engine for engine in engines if engine in configured]
                for intent, engines in groups.items()
                if configured.intersection(engines)
            }
            updates["verified_engines"] = record.get("verified_engines", [])
            updates["engine_evidence"] = record.get("engine_evidence")
        return template.model_copy(update=updates)

    @staticmethod
    def tool(record):
        params = {"search_provider": record["provider"]}
        for key in ("api_key", "api_base"):
            if record.get(key):
                params[key] = record[key]
        if record.get("engines"):
            params["engines"] = ",".join(record["engines"])
        if record["provider"] == "openai":
            params.update(
                search_model=record.get("search_model", DEFAULT_MODEL),
                search_context_size=record.get("search_context_size", "medium"),
                max_output_tokens=record.get("max_output_tokens", 2048),
                timeout=record["timeout_ms"] / 1000,
            )
        return {"search_tool_name": record["name"], "litellm_params": params}

    def refresh(self):
        records = self.store.providers(private=True)
        registry = Registry({r["name"]: self.capability(r) for r in records}) if records else self.templates
        tools = [self.tool(r) for r in records if r["enabled"]]
        tools.append({"search_tool_name": "auto", "litellm_params": {"search_provider": "searxng"}})
        replacement = litellm.Router(model_list=[], search_tools=tools, num_retries=0)
        telemetry = self.app.state.smart_search.telemetry
        health = self.app.state.smart_search.health
        self.proxy.llm_router = replacement
        smart, _, _ = install(self.proxy, registry)
        smart.telemetry = telemetry
        smart.health = health
        smart.planner.health = health
        self.callback.registry = registry
        self.app.state.smart_search = smart

    def active_names(self):
        return {r["name"] for r in self.store.providers() if r["enabled"]}


def get_runtime(request: Request):
    runtime = getattr(request.app.state, "admin_runtime", None)
    if runtime is None:
        raise HTTPException(503, "Management console is not configured")
    return runtime


def same_origin(request):
    origin = request.headers.get("origin")
    expected = str(request.base_url).rstrip("/")
    if (origin and origin.rstrip("/") != expected) or request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site requests are not allowed")


def current_session(request: Request, runtime=Depends(get_runtime)):
    result = runtime.store.session(request.cookies.get("bensz_session", ""))
    if result is None:
        raise HTTPException(401, "请先登录")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        same_origin(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), result["csrf_token"]):
            raise HTTPException(403, "Invalid CSRF token")
    return result


def administrator(session=Depends(current_session)):
    if session["user"]["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return session


async def managed_api_auth(request: Request, api_key: str | None):
    runtime = get_runtime(request)
    token = api_key or ""
    master = getattr(runtime.proxy, "master_key", None) or os.environ.get("LITELLM_MASTER_KEY", "")
    if master and hmac.compare_digest(token, master):
        return UserAPIKeyAuth(api_key=digest(token), user_role="proxy_admin")
    # Custom auth returns before upstream's role checks: explicitly confine managed keys.
    path = request.url.path
    is_search = path in {"/search", "/v1/search"} or any(
        path.startswith(prefix) and "/" not in path[len(prefix) :] for prefix in ("/search/", "/v1/search/")
    )
    is_protocol = (
        (path == "/bensz-search/v1/capabilities" and request.method == "GET")
        or (path == "/search/tools" and request.method == "GET")
        or (path == "/bensz-search/v1/search" and request.method == "POST")
        or (path.rstrip("/") == "/bensz-search/mcp" and request.method in {"POST", "GET", "DELETE"})
    )
    if not is_protocol and (not is_search or request.method != "POST"):
        raise HTTPException(403, "Managed access keys are only valid for search requests")
    record = runtime.store.authenticate_key(token)
    if record is None:
        raise HTTPException(401, "Invalid or revoked access key")
    return UserAPIKeyAuth(
        api_key=digest(token),
        user_id=str(record["user_id"]),
        user_role="internal_user",
        object_permission={
            "object_permission_id": record["id"],
            "search_tools": ["auto", *sorted(runtime.active_names())],
        },
    )


router = APIRouter(prefix="/admin/api", tags=["bensz-search console"])
login_attempts = defaultdict(deque)


@router.post("/login")
async def login(data: Login, request: Request, response: Response, runtime=Depends(get_runtime)):
    same_origin(request)
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    # Bound the rate-limit map as well as the attempts in each entry.
    for key in list(login_attempts):
        while login_attempts[key] and login_attempts[key][0] < now - 300:
            login_attempts[key].popleft()
        if not login_attempts[key]:
            del login_attempts[key]
    if len(login_attempts) >= 10000 or len(login_attempts[address]) >= 5:
        raise HTTPException(429, "登录尝试过多，请五分钟后重试")
    login_attempts[address].append(now)
    result = await asyncio.to_thread(runtime.store.login, data.username, data.password)
    if result is None:
        raise HTTPException(401, "用户名或密码错误")
    login_attempts.pop(address, None)
    token, public = result
    response.set_cookie(
        "bensz_session",
        token,
        max_age=43200,
        httponly=True,
        samesite="strict",
        secure=os.getenv("BENSZ_SEARCH_COOKIE_SECURE", "false").lower() == "true",
        path="/admin",
    )
    return public


@router.get("/session")
def session(session=Depends(current_session)):
    return session


@router.post("/logout")
def logout(
    request: Request, response: Response, session=Depends(current_session), runtime=Depends(get_runtime)
):
    runtime.store.logout(request.cookies.get("bensz_session", ""))
    response.delete_cookie("bensz_session", path="/admin")
    return {"ok": True}


@router.get("/overview")
def overview(session=Depends(current_session), runtime=Depends(get_runtime)):
    providers = runtime.store.providers()
    metrics = runtime.app.state.smart_search.telemetry.snapshot()
    if session["user"]["role"] != "admin":
        providers = [{key: record[key] for key in ("name", "provider", "enabled")} for record in providers]
        metrics = {"scope": "process", "persistent": False, "counters": {}, "recent": []}
    return {
        "version": __version__,
        "mode": "production",
        "configured_count": len(providers),
        "enabled_count": sum(r["enabled"] for r in providers),
        "providers": providers,
        "metrics": metrics,
    }


@router.get("/providers")
def providers(session=Depends(administrator), runtime=Depends(get_runtime)):
    return {"providers": runtime.store.providers(), "catalog": CATALOG}


def save_provider(data, runtime, updating=False):
    previous = next((p for p in runtime.store.providers() if p["name"] == data.name), None)
    if not updating and previous:
        raise HTTPException(409, "配置名称已存在")
    if updating and not previous:
        raise HTTPException(404, "配置不存在")
    needs_key = data.provider != "searxng"
    if (
        needs_key
        and not data.api_key
        and not (previous and previous["has_api_key"] and previous["provider"] == data.provider)
    ):
        raise HTTPException(422, "该搜索服务需要 API Key")
    record = data.model_dump(exclude={"api_key"})
    capability = runtime.capability(record)
    record["source_family"] = capability.source_family
    record["estimated_cost_usd"] = capability.estimated_cost_usd
    replacement_key = data.api_key or None
    if previous and previous["provider"] != data.provider and not data.api_key:
        replacement_key = ""
    runtime.store.save_provider(record, replacement_key)
    runtime.refresh()
    return {"ok": True}


@router.post("/providers")
def create_provider(data: ProviderInput, session=Depends(administrator), runtime=Depends(get_runtime)):
    return save_provider(data, runtime)


@router.put("/providers/{name}")
def update_provider(
    name: str, data: ProviderInput, session=Depends(administrator), runtime=Depends(get_runtime)
):
    if data.name != name:
        raise HTTPException(422, "配置名称不能修改")
    return save_provider(data, runtime, updating=True)


@router.delete("/providers/{name}")
def delete_provider(name: str, session=Depends(administrator), runtime=Depends(get_runtime)):
    if not runtime.store.delete_provider(name):
        raise HTTPException(404, "配置不存在")
    runtime.refresh()
    return {"ok": True}


@router.post("/providers/{name}/test")
async def test_provider(
    name: str, data: TestQuery, session=Depends(administrator), runtime=Depends(get_runtime)
):
    record = next((p for p in runtime.store.providers(private=True) if p["name"] == name), None)
    if record is None:
        raise HTTPException(404, "配置不存在")
    started = time.monotonic()
    try:
        # Disabled configurations remain testable; they are not inserted into the live router.
        temporary = litellm.Router(model_list=[], search_tools=[runtime.tool(record)], num_retries=0)
        result = await asyncio.wait_for(
            provider_call(temporary, temporary.asearch)(
                search_tool_name=name, query=data.query, max_results=3, num_retries=0
            ),
            record["timeout_ms"] / 1000,
        )
        rows = result.results[:3]
        return {
            "ok": bool(rows),
            "result_count": len(result.results),
            "results": [r.model_dump() for r in rows],
            "category": "success" if rows else "empty",
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
    except Exception as error:
        return {
            "ok": False,
            "result_count": 0,
            "results": [],
            "category": failure_category(error),
            "latency_ms": round((time.monotonic() - started) * 1000),
        }


@router.post("/providers/{name}/engines/sync")
async def sync_provider_engines(name: str, session=Depends(administrator), runtime=Depends(get_runtime)):
    from .engine_metadata import verified_instance_engines

    record = next((p for p in runtime.store.providers(private=True) if p["name"] == name), None)
    if record is None:
        raise HTTPException(404, "配置不存在")
    try:
        engines, evidence = await verified_instance_engines(record)
    except Exception:
        raise HTTPException(502, "无法验证实例引擎信息；未更改已保存的配置") from None
    # Do not overwrite a concurrent provider edit with this older fetched snapshot.
    current = next((p for p in runtime.store.providers(private=True) if p["name"] == name), None)
    if current != record:
        raise HTTPException(409, "配置已变化，请重新同步")
    public = {k: v for k, v in record.items() if k not in {"api_key", "has_api_key"}}
    public.update(verified_engines=engines, engine_evidence=evidence)
    runtime.store.save_provider(public)
    runtime.refresh()
    return {
        "verified_engines": engines,
        "evidence": evidence,
        "query_semantics": "keyword passthrough; domain field syntax remains unknown",
    }


@router.post("/search")
async def search(data: SearchRequest, session=Depends(current_session), runtime=Depends(get_runtime)):
    active = runtime.active_names()
    if data.search_tool_name != "auto":
        if data.search_tool_name not in active:
            raise HTTPException(403, "搜索服务未启用")
        record = next(p for p in runtime.store.providers() if p["name"] == data.search_tool_name)
        try:
            result = await asyncio.wait_for(
                runtime.app.state.smart_search.call(
                    search_tool_name=data.search_tool_name,
                    query=data.query,
                    max_results=data.max_results,
                    search_domain_filter=data.search_domain_filter,
                    country=data.country,
                    max_tokens_per_page=data.max_tokens_per_page,
                    num_retries=0,
                ),
                min(record["timeout_ms"], data.constraints.latency_budget_ms or 15000) / 1000,
            )
            result.results = result.results[: data.max_results]
            return result.model_dump()
        except Exception as error:
            raise HTTPException(502, "搜索失败：" + failure_category(error)) from None
    try:
        result = await runtime.app.state.smart_search.search(data, active)
        return result.model_dump()
    except SearchFailed as error:
        raise HTTPException(error.status_code, str(error)) from None


@router.get("/keys")
def keys(session=Depends(current_session), runtime=Depends(get_runtime)):
    return {"keys": runtime.store.keys(session["user"]["id"])}


@router.post("/keys")
def create_key(data: KeyInput, session=Depends(current_session), runtime=Depends(get_runtime)):
    return runtime.store.create_key(session["user"]["id"], data.name)


@router.delete("/keys/{key_id}")
def revoke_key(key_id: str, session=Depends(current_session), runtime=Depends(get_runtime)):
    if not runtime.store.revoke_key(session["user"]["id"], key_id):
        raise HTTPException(404, "访问密钥不存在")
    return {"ok": True}


@router.get("/users")
def users(session=Depends(administrator), runtime=Depends(get_runtime)):
    return {"users": runtime.store.users()}


@router.post("/users")
async def create_user(data: NewUser, session=Depends(administrator), runtime=Depends(get_runtime)):
    try:
        return await asyncio.to_thread(runtime.store.create_user, data.username, data.password, data.role)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "用户名已存在") from None


@router.delete("/users/{user_id}")
def delete_user(user_id: int, session=Depends(administrator), runtime=Depends(get_runtime)):
    if user_id == session["user"]["id"]:
        raise HTTPException(409, "不能删除当前登录用户")
    if not runtime.store.delete_user(user_id):
        raise HTTPException(404, "用户不存在")
    return {"ok": True}


@router.post("/password")
async def change_password(
    data: PasswordChange, response: Response, session=Depends(current_session), runtime=Depends(get_runtime)
):
    valid = await asyncio.to_thread(
        runtime.store.change_password, session["user"]["id"], data.current_password, data.new_password
    )
    if not valid:
        raise HTTPException(400, "当前密码不正确")
    response.delete_cookie("bensz_session", path="/admin")
    return {"ok": True, "reauthenticate": True}


def initialize_admin(app, proxy, registry, callback, configured_tools):
    secret = os.getenv("BENSZ_SEARCH_SECRET", "")
    password = os.getenv("BENSZ_SEARCH_ADMIN_PASSWORD", "")
    username = os.getenv("BENSZ_SEARCH_ADMIN_USERNAME", "admin")
    if len(secret) < 32 or len(password) < 12:
        raise RuntimeError("Set BENSZ_SEARCH_SECRET (32+ chars) and BENSZ_SEARCH_ADMIN_PASSWORD (12+ chars)")
    store = AdminStore(os.getenv("BENSZ_SEARCH_DATA_DIR", "data") + "/admin.sqlite3", secret)
    store.bootstrap(username, password)
    seeds = []
    for tool in configured_tools:
        params = tool["litellm_params"]
        if tool["search_tool_name"] == "auto":
            continue
        capability = next(
            (p for p in registry.providers.values() if p.provider == params["search_provider"]), None
        )
        if capability is None:
            continue

        def resolve(value):
            if isinstance(value, str) and value.startswith("os.environ/"):
                return os.getenv(value.split("/", 1)[1], "")
            return value

        engines = resolve(params.get("engines", ""))
        seeds.append(
            {
                "name": tool["search_tool_name"],
                "provider": params["search_provider"],
                "enabled": True,
                "api_key": resolve(params.get("api_key", "")),
                "api_base": resolve(params.get("api_base", "")),
                "engines": [engine.strip() for engine in engines.split(",") if engine.strip()]
                if isinstance(engines, str)
                else engines,
                "search_model": resolve(params.get("search_model", DEFAULT_MODEL)) or DEFAULT_MODEL,
                "search_context_size": params.get("search_context_size", "medium"),
                "max_output_tokens": params.get("max_output_tokens", 2048),
                "timeout_ms": int(params.get("timeout", 15) * 1000),
                "source_family": capability.source_family,
                "estimated_cost_usd": capability.estimated_cost_usd,
            }
        )
    store.seed_providers(seeds)
    runtime = AdminRuntime(app, proxy, store, registry, callback)
    app.state.admin_runtime = runtime
    runtime.refresh()
    return runtime
