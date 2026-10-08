<div align="center">
  <h1>bensz-search</h1>
  <p><strong>A shared search endpoint for applications and AI agents</strong></p>
  <p><a href="https://github.com/huangwb8/bensz-search/releases"><img alt="GitHub Release" src="https://img.shields.io/github/v/release/huangwb8/bensz-search"></a> <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-blue"> <img alt="LiteLLM 1.103.2" src="https://img.shields.io/badge/LiteLLM-1.103.2-blue"> <img alt="Docker linux/amd64" src="https://img.shields.io/badge/Docker-linux%2Famd64-blue"></p>
  <p><a href="README.md">中文</a> · <a href="docs/search-api-setup.md">Search setup</a> · <a href="docs/smart-search-router/protocol/README.md">HTTP / MCP protocol</a> · <a href="docs/deploy/server-deployment.md">Server deployment</a></p>
</div>

A standalone extension on LiteLLM 1.103.2 with no upstream source changes. Administrators configure and test providers and manage users; members search and create application keys in a personal workspace. Automatic search selects providers from task requirements and constraints, with timeouts, fallback, deduplication and weighted RRF fusion. External AI hosts can discover capabilities and submit individual engine queries.

Current release: `v1.0.9`. The official image is [`huangwb8/bensz-search:1.0.9`](https://hub.docker.com/r/huangwb8/bensz-search), available for `linux/amd64` only, with a matching `latest` tag. Operators must configure usable providers; commercial services require their own API Key.

## Quick start

Requires Docker Compose 2.24.4+, Python 3.11+, and a SearXNG instance with JSON output or commercial search credentials. The Python package supports 3.11–3.13; the image uses 3.11.

```bash
python docs/deploy/deploy_local.py
curl --noproxy '*' http://127.0.0.1:8898/health/liveliness
curl --noproxy '*' http://127.0.0.1:8898/ready
```

The script creates independent master/encryption keys and an initial administrator password in private `docs/deploy/.env`, preserving existing settings. Open the [administrator console](http://127.0.0.1:8898/admin), then sign in as `admin` with the password in `docs/deploy/.secrets/local-admin.txt`. Members use the [personal workspace](http://127.0.0.1:8898/app). Liveness checks the process, readiness checks enabled configuration, and console connection tests verify external retrieval.

The default SearXNG URL is `http://host.docker.internal:8080`; run a real instance or configure another provider in the console. Local deployment binds only to loopback. Server deployments use [server Compose](docs/deploy/docker-compose.yml), an external proxy network and an independent SearXNG instance; see [deployment instructions](docs/deploy/server-deployment.md).

## Configuration and workspaces

| Workspace | Entry | Features |
|---|---|---|
| Administrator console | `/admin` | Global overview, search engines and live tests, users, administrator keys (all users), audit logs, search debugging and [system settings](docs/smart-search-router/system-settings.md) |
| Personal workspace | `/app` | Available providers, personal keys, per-engine personal usage and trends for the last 7/30 days, search, integration and account settings |

Administrators keep two collapsible navigation groups whose items are indented with a light hierarchy line; members see a flat personal menu without group headings. Pages support refresh and browser history, the brand area shows the running version, and mobile navigation remains available. The server enforces roles and key ownership.

**v1.0.9** adds session resource caching and independent page sections, SQLite/usage persistence in bounded worker threads, search admission control and paginated key/user lists to reduce synchronous waits during searches. It also adds personal usage trends and persistent system settings. Performance figures come from isolated experiments; see [implementation and validation](docs/smart-search-router/performance-implementation.md) for conditions and results.

**v1.0.8** improves console and personal workspace readability: body text and inputs use 16 px, navigation and table rows use 15 px, and labels use 14 px, with consistent line heights and clearer text contrast. Page title size and control height are preserved.

**v1.0.7** adds permanent key deletion: users can delete their own keys and administrators can delete any user's keys in active, revoked or expired state; deletion is immediate while audit history is preserved. It also refines sidebar hierarchy, control heights, filter alignment and dialog actions; see the [console guide](docs/smart-search-router/commercial-admin.md).

**v1.0.5** adds console governance and operational metrics. The overview supports process metrics and the last 7/30 UTC calendar days. Latency percentiles use histogram bucket upper bounds, and costs are estimates rather than provider bills. See the [console guide](docs/smart-search-router/commercial-admin.md) for user lifecycle, expiring/scoped keys, sessions and configuration import/export.

`v1.0.4` adds native bensz-search providers: compose remote instances recursively with cycle detection, bounded calls and deadlines, and leaf-source deduplication. Configure the remote base URL and an independent application key in Search API. All participating instances must support federation. See [configuration and limits](docs/smart-search-router/federated-search.md).

Supports **OpenAI Web Search, Exa, Brave, Tavily, Serper, Perplexity, SearXNG and bensz-search**, including multiple instances per provider type. Saved settings apply to new requests immediately. Leaving an API Key blank preserves it for the same provider type; changing type does not inherit credentials. Environment configuration is imported only when the database is initialized. See the [search setup guide](docs/search-api-setup.md).

OpenAI uses Responses `web_search`, defaults to `gpt-4.1-mini`, and labels generated summaries; see the [OpenAI guide](docs/smart-search-router/openai-web-search.md). SearXNG defaults list 11 common engines that must be supported and enabled by the instance; task routing selects subsets. Historical live verification covers GitHub/PubMed. See [engine settings](docs/smart-search-router/searxng-default-engines.md).

## Search and AI integration

Create an application key in the console and inject it as `BENSZ_SEARCH_API_KEY`. Its full value is shown once; revocation and deletion are immediate. Active, revoked and expired keys can be permanently deleted. Keys support optional `search` and `protocol` scopes; both are enabled by default. Expired/revoked keys and disabled users are rejected immediately. Application keys and login passwords are separate.

```bash
curl --noproxy '*' http://127.0.0.1:8898/search \
  -H "Authorization: Bearer ${BENSZ_SEARCH_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"query":"colorectal cancer ctDNA","search_tool_name":"auto","profile":{"type":"scientific_research","domain":"biomedical"},"max_results":5,"constraints":{"latency_budget_ms":15000},"debug":true}'
```

Native responses retain `{"object":"search","results":[...]}`. Debug adds plans, attempts, error categories, estimated costs, source overlap and fusion contributions, without returning the raw query/profile_prompt.

| Endpoint | Purpose |
|---|---|
| `POST /search`, `/v1/search` | Automatic routing or an explicit `search_tool_name` |
| `POST /search/<name>`, `/v1/search/<name>` | The tool name in the path takes precedence |
| `GET /bensz-search/v1/capabilities` | Discover tools and verified engines allowed by the key |
| `POST /bensz-search/v1/search` | `auto` or external `planned` search; zero-call `dry_run` |
| `/bensz-search/mcp/` | MCP SDK Streamable HTTP with Bearer authentication on every request |
| `GET /bensz-search/v1/schema` | Public static request Schema |

Application keys can search and discover capabilities, but cannot access console or native LiteLLM key/config administration. GET `/` and `/search` redirect to the console; search uses POST. Native requests support up to 10 queries, 1–20 results, and profile/constraints/fusion. See the [protocol reference](docs/smart-search-router/protocol/README.md) for parameters, budgets and authentication.

The host manages model tool loops; the service manages authentication, budgets, retrieval and normalized results. Provider credentials stay in the console. Python/TypeScript clients support five model message families with offline tool-loop tests. Live search and MCP are verified separately; consult the matrix for specific live models/channels.

- [中文接入](docs/smart-search-router/protocol/integration.zh-CN.md) / [English integration](docs/smart-search-router/protocol/integration.en.md)
- [Responses host-planned search and compute flow](docs/responses-host-planned-search.md)
- [Compatibility matrix](docs/smart-search-router/protocol/compatibility.md) / [Protocol verification](docs/smart-search-router/protocol/verification.md)
- [TypeScript client](clients/typescript/README.md) / [Python client](src/bensz_search/client.py)

## Deployment and maintenance

Local SQLite storage uses the `search-data` named volume; server deployments use project-local bind mounts. Users, sessions, application keys and encrypted provider settings persist. Audit logs, key call counts and daily usage also persist. Process health, circuit breakers and recent request history reset on restart. Back up the database with its matching `BENSZ_SEARCH_SECRET`; do not regenerate the encryption key.

```bash
docker compose -f docs/deploy/compose.yaml up -d --build --wait
docker compose -f docs/deploy/compose.yaml ps
```

Since 1.0.5 the service applies incremental database migrations automatically. Rolling back to an older image also requires restoring the pre-upgrade database snapshot. See the [v1.0.5 release verification](docs/deploy/releases/v1.0.5.md) and the [v1.0.9 release verification](docs/deploy/releases/v1.0.9.md).

For server upgrades, back up the previous image ID, Compose file, private settings and SQLite databases in `/docker/bensz-search`, then update only the search service:

```bash
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.9 docker compose -f docker-compose.yml pull search
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.9 docker compose -f docker-compose.yml up -d --no-deps --wait search
```

Containers run as non-root with memory, concurrency, PID and log limits. Deployment is currently a single process on one host; shared multi-instance state is unverified. Do not use `down -v` for routine restarts. HTTPS hosting requires Secure Cookie settings and forwarded-header trust restricted to actual proxy IPs. See [local deployment](docs/deploy/README.md) and [server deployment](docs/deploy/server-deployment.md) for backups, recovery and proxy settings.

## Development and verification

```bash
sh scripts/uv.sh sync --extra dev
sh scripts/uv.sh run pytest -q
sh scripts/uv.sh run ruff check src tests demo scripts docs/deploy
sh scripts/uv.sh run ruff format --check src tests demo scripts docs/deploy
for module in src/bensz_search/static/*.js; do node --check "$module"; done
```

The wrapper keeps the Python environment and uv/pytest/Ruff caches in `.bensz-api/`; the versioned dependency lockfile is [`.bensz-api/uv.lock`](.bensz-api/uv.lock). Because uv requires a root lockfile, the wrapper creates a temporary symlink and removes it on exit. Use the commands above and run only one wrapper command at a time per project. The wrapper requires `python3` on macOS/Linux. `pyproject.toml` is the authoritative version. The 60-case [routing benchmark](tests/benchmarks/routing.json) accepts multiple reasonable providers. Tests cover API compatibility, permissions, fusion, fallback, persistence and workspace entries. See [deployment documentation](docs/deploy/README.md) for fixtures; mock results do not establish live supplier availability.

## Documentation and limits

- [Call-chain audit](docs/smart-search-router/architecture-audit.md): based on the LiteLLM 1.103.2 release package; its upstream Git commit was not obtained.
- [Console guide and metric definitions](docs/smart-search-router/commercial-admin.md) / [Console verification](docs/smart-search-router/commercial-admin-verification.md)
- [UI verification](docs/smart-search-router/series-ui-verification.md) / [Earlier live product verification](docs/smart-search-router/production-verification.md)
- [Changelog](CHANGELOG.md) / [Collaboration rules](AGENTS.md) / [Contribution ledger](docs/contribution.bac)
- Questions and feedback: [GitHub Issues](https://github.com/huangwb8/bensz-search/issues). Historical plans retain their original baselines; current capabilities follow source, protocol and verification evidence.

Cost estimates are configuration priors, not supplier bills. The rule planner supports six intents; there is no server-side LLM planner. External results are untrusted and generated summaries are not evidence. Provider diversity does not guarantee independent underlying sources. Availability, rate limits and specific live model versions require individual verification; universal production model compatibility is not claimed.

The repository has no standalone LICENSE file; no open-source license is claimed. LiteLLM and other dependencies retain their respective licenses.
