"""Authenticated HTTP facade; the permission source is the existing gateway."""

import asyncio
import os

from fastapi import APIRouter, Depends, Request
from litellm.proxy import proxy_server as proxy
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth

from .integration import authorized_tools
from .protocol import ProtocolFailure, ProtocolLimits, TenantLimiter, capabilities, search
from .protocol_models import CapabilitySnapshot, ProtocolSearch, SearchEnvelope

router = APIRouter(prefix="/bensz-search/v1", tags=["bensz-search protocol v1"])


async def permission_snapshot(request, user, enforce_protocol=True):
    if enforce_protocol and os.getenv("BENSZ_SEARCH_PROTOCOL_ENABLED", "true").lower() != "true":
        raise ProtocolFailure("protocol_disabled", "Search protocol is disabled", status_code=503)
    smart = request.app.state.smart_search
    runtime = getattr(request.app.state, "admin_runtime", None)
    names = runtime.active_names() if runtime else smart.registry.configured(proxy.llm_router.search_tools)
    team = await load_team(user)
    allowed = await authorized_tools(names, user, team)
    # Pin execution to this router instance even if configuration is refreshed later.
    return smart, allowed


async def load_team(user):
    team = None
    if user.team_id:
        from litellm.proxy.auth.auth_checks import get_team_object

        team = await get_team_object(
            team_id=user.team_id,
            prisma_client=proxy.prisma_client,
            user_api_key_cache=proxy.user_api_key_cache,
            parent_otel_span=user.parent_otel_span,
            proxy_logging_obj=proxy.proxy_logging_obj,
        )
    return team


def limiter(app):
    if not hasattr(app.state, "protocol_limiter"):
        app.state.protocol_limiter = TenantLimiter()
    return app.state.protocol_limiter


async def execute_for_user(request, user, data, cancel_on_disconnect=False):
    smart, allowed = await permission_snapshot(request, user)
    limits = ProtocolLimits()
    identity = str(user.user_id or user.api_key)
    admission = limiter(request.app)
    admission.enter(identity, limits)
    task = None
    watcher = None
    try:
        task = asyncio.create_task(search(smart, data, allowed, limits, {"user": user.user_id}))

        async def watch_disconnect():
            while not task.done():
                await asyncio.sleep(0.05)
                if await request.is_disconnected():
                    task.cancel()
                    return

        if cancel_on_disconnect:
            watcher = asyncio.create_task(watch_disconnect())
        return await task
    finally:
        for job in (task, watcher):
            if job and not job.done():
                job.cancel()
        await asyncio.gather(*(j for j in (task, watcher) if j), return_exceptions=True)
        admission.leave(identity)


@router.get("/capabilities", response_model=CapabilitySnapshot)
async def get_capabilities(request: Request, user=Depends(user_api_key_auth)):
    smart, allowed = await permission_snapshot(request, user)
    return capabilities(smart, allowed)


@router.post("/search", response_model=SearchEnvelope)
async def post_search(data: ProtocolSearch, request: Request, user=Depends(user_api_key_auth)):
    return await execute_for_user(request, user, data, cancel_on_disconnect=True)


@router.get("/schema", include_in_schema=False)
async def schema():
    return ProtocolSearch.model_json_schema()
