<div align="center">
  <h1>bensz-search</h1>
  <p><strong>A shared search endpoint for applications and AI agents</strong></p>
  <p><a href="https://github.com/huangwb8/bensz-search/releases"><img alt="GitHub Release" src="https://img.shields.io/github/v/release/huangwb8/bensz-search"></a> <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-blue"> <img alt="LiteLLM 1.103.2" src="https://img.shields.io/badge/LiteLLM-1.103.2-blue"> <img alt="Docker linux/amd64" src="https://img.shields.io/badge/Docker-linux%2Famd64-blue"></p>
  <p><a href="README.md">中文</a> · <a href="docs/search-api-setup.md">Search setup</a> · <a href="docs/smart-search-router/protocol/README.md">HTTP / MCP protocol</a> · <a href="docs/deploy/server-deployment.md">Server deployment</a></p>
</div>

A standalone extension on LiteLLM 1.103.2 with no upstream source changes. Administrators configure and test providers and manage users; members search and create application keys in a personal workspace. Automatic search selects providers from task requirements and constraints, with timeouts, fallback, deduplication and weighted RRF fusion. External AI hosts can discover capabilities and submit individual engine queries.

Current release: `v1.0.3`. The official image is [`huangwb8/bensz-search:1.0.3`](https://hub.docker.com/r/huangwb8/bensz-search), available for `linux/amd64` only, with a matching `latest` tag. Operators must configure usable providers; commercial services require their own API Key.

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
| Administrator console | `/admin` | Global overview, Search API configuration and live tests, users, search and personal keys |
| Personal workspace | `/app` | Available providers and personal key overview, search, integration and account settings |

Administrators see vertically arranged, independently collapsible administrator/member navigation sections; members see only their personal section. Pages support refresh and browser history, the top bar shows the running version, and mobile navigation remains available. The server enforces roles and key ownership.

Supports **OpenAI Web Search, Exa, Brave, Tavily, Serper, Perplexity and SearXNG**, including multiple instances per provider type. Saved settings apply to new requests immediately. Leaving an API Key blank preserves it for the same provider type; changing type does not inherit credentials. Environment configuration is imported only when the database is initialized. See the [search setup guide](docs/search-api-setup.md).

OpenAI uses Responses `web_search`, defaults to `gpt-4.1-mini`, and labels generated summaries; see the [OpenAI guide](docs/smart-search-router/openai-web-search.md). SearXNG defaults list 11 common engines that must be supported and enabled by the instance; task routing selects subsets. Historical live verification covers GitHub/PubMed. See [engine settings](docs/smart-search-router/searxng-default-engines.md).

## Search and AI integration

Create an application key in the console and inject it as `BENSZ_SEARCH_API_KEY`. Its full value is shown once; revocation is immediate. Application keys and login passwords are separate.

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

Local SQLite storage uses the `search-data` named volume; server deployments use project-local bind mounts. Users, sessions, application keys and encrypted provider settings persist. Metrics, circuit breakers and request history reset on restart. Back up the database with its matching `BENSZ_SEARCH_SECRET`; do not regenerate the encryption key.

```bash
docker compose -f docs/deploy/compose.yaml up -d --build --wait
docker compose -f docs/deploy/compose.yaml ps
```

For server upgrades, back up the previous image ID, Compose file and private settings in `/docker/bensz-search`, then update only the search service:

```bash
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.3 docker compose -f docker-compose.yml pull search
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.3 docker compose -f docker-compose.yml up -d --no-deps --wait search
```

Containers run as non-root with memory, concurrency, PID and log limits. Deployment is currently a single process on one host; shared multi-instance state is unverified. Do not use `down -v` for routine restarts. HTTPS hosting requires Secure Cookie settings and forwarded-header trust restricted to actual proxy IPs. See [local deployment](docs/deploy/README.md) and [server deployment](docs/deploy/server-deployment.md) for backups, recovery and proxy settings.

## Development and verification

```bash
sh scripts/uv.sh sync --extra dev
sh scripts/uv.sh run pytest -q
sh scripts/uv.sh run ruff check src tests demo scripts docs/deploy
sh scripts/uv.sh run ruff format --check src tests demo scripts docs/deploy
node --check src/bensz_search/static/app.js
```

The wrapper keeps the Python environment and uv/pytest/Ruff caches in `.bensz-api/`. `pyproject.toml` is the authoritative version; `uv.lock` fixes dependencies. The 60-case [routing benchmark](tests/benchmarks/routing.json) accepts multiple reasonable providers. Tests cover API compatibility, permissions, fusion, fallback, persistence and workspace entries. See [deployment documentation](docs/deploy/README.md) for fixtures; mock results do not establish live supplier availability.

## Documentation and limits

- [Call-chain audit](docs/smart-search-router/architecture-audit.md): based on the LiteLLM 1.103.2 release package; its upstream Git commit was not obtained.
- [UI verification](docs/smart-search-router/series-ui-verification.md) / [Earlier live product verification](docs/smart-search-router/production-verification.md)
- [Changelog](CHANGELOG.md) / [Collaboration rules](AGENTS.md) / [Contribution ledger](docs/contribution.bac)
- Questions and feedback: [GitHub Issues](https://github.com/huangwb8/bensz-search/issues). Historical plans retain their original baselines; current capabilities follow source, protocol and verification evidence.

Cost estimates are configuration priors, not supplier bills. The rule planner supports six intents; there is no server-side LLM planner. External results are untrusted and generated summaries are not evidence. Provider diversity does not guarantee independent underlying sources. Availability, rate limits and specific live model versions require individual verification; universal production model compatibility is not claimed.

The repository has no standalone LICENSE file; no open-source license is claimed. LiteLLM and other dependencies retain their respective licenses.
