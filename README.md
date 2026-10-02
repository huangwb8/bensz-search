# bensz-search

面向 AI Agent 的智能搜索服务，基于 **LiteLLM 1.103.2 独立扩展**。提供中文登录后台、Search API 管理与测试、真实搜索调试、访问密钥和用户管理。保留原生 `POST /search`；`search_tool_name: auto` 增加任务规划、超时、fallback、去重和 weighted RRF 融合。LiteLLM 源文件改动为零。

## 本地部署

需要 Docker Compose 2.24.4+ 与 Python 3.11+。已有支持 JSON 输出的 SearXNG 可直接接入，本机初始化默认地址为 `http://host.docker.internal:8080`。

```bash
python docs/deploy/deploy_local.py
```

脚本生成随机管理员密码、独立加密密钥和服务 master key，保存到不纳入 Git 的 `docs/deploy/.env`。已有配置不会被覆盖。默认运行真实服务，不运行模拟 provider；Docker 只绑定本机端口。

- **后台**：[http://127.0.0.1:8898/admin](http://127.0.0.1:8898/admin)
- 初始账号 `admin`，初始密码见 `docs/deploy/.secrets/local-admin.txt` 或 `docs/deploy/.env` 的 `BENSZ_SEARCH_ADMIN_PASSWORD`。
- [存活检查](http://127.0.0.1:8898/health/liveliness)：检查进程响应。
- [就绪检查](http://127.0.0.1:8898/ready)：检查是否有启用配置；外部可用性通过后台连接测试确认。
- [API 文档](http://127.0.0.1:8898/api/docs)：原生 LiteLLM OpenAPI。

首次登录后可在“个人设置”修改密码；修改后初始密码失效。已有用户数据库不会在重启时用 `docs/deploy/.env` 的初始密码覆盖账号。

### 配置不同 Search API

后台支持 **Exa、Brave、Tavily、Serper、Perplexity、SearXNG**。可配置多条同类型服务，名称必须唯一。每条配置可编辑地址、凭据、引擎及超时，启停或删除；保存后立即用于新的搜索请求，无需重启。

- 商业服务需要真实 API Key；地址留空使用原生 adapter 默认值。
- SearXNG 需要服务地址及 JSON 输出，可指定逗号分隔的引擎。管理员可以连接内网实例。
- 编辑时 API Key 留空保留同类型原密钥，换类型时不会沿用旧凭据。
- “测试”执行真实查询，显示结果数、延迟及失败类别；有 HTTP 响应但无结果仍判为失败。
- 生产模式拒绝 fixture 配置与公开 demo master key。

首次启动从 `config/litellm.yaml` 和 `docs/deploy/.env` 导入服务，之后以后台数据库为准；修改 `docs/deploy/.env` 不会覆盖后台设置。凭据加密保存，接口只返回是否已配置，不返回完整 provider key。

本机已验证来源为 SearXNG 的 GitHub / PubMed，默认初始化选择这两个引擎。后台可以换成实例上实际可用的网页或新闻引擎。公共引擎可能 CAPTCHA/限流，不能以空结果当作成功。配置包含 PubMed 时，学术自动请求优先使用学术引擎；代码意图优先使用已配置的 GitHub 等引擎。没有商业 key 时，不宣称商业源已实测通过。

### 用户与访问密钥

管理员管理服务并创建/删除后台用户；成员可搜索、管理自己的 key 和修改密码。服务端强制执行权限，成员看不到完整连接配置或其他用户的路由历史。

登录使用 HttpOnly / SameSite Cookie、跨站请求保护和登录限速。密码使用 scrypt 哈希，session 与访问 key 不以明文保存。在“访问密钥”创建应用专属 key，完整值只显示一次，撤销立即生效。后台密码与应用 key 分离。

## 调用搜索 API

将后台生成的 key 注入应用环境变量，发送 POST 请求：

```bash
curl --noproxy '*' http://127.0.0.1:8898/search \
  -H "Authorization: Bearer ${BENSZ_SEARCH_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "colorectal cancer ctDNA",
    "search_tool_name": "auto",
    "profile": {"type": "scientific_research", "domain": "biomedical"},
    "max_results": 5,
    "constraints": {"latency_budget_ms": 15000},
    "debug": true
  }'
```

默认响应保留 `{"object":"search","results":[...]}`。debug 增加意图、计划、理由、attempts、错误类别、延迟、预估费用、来源 overlap 和融合贡献，不包含原始 query/profile_prompt。

| 调用 | 行为 |
|---|---|
| `POST /search` 或 `/v1/search`，只有 query | 默认工具 auto |
| body `search_tool_name: "<配置名称>"` | 显式调用，保留 provider-specific 搜索参数 |
| `POST /search/<名称>` 或 `/v1/search/<名称>` | 路径参数优先 |
| `search_tool_name: "auto"` 或 `/search/auto` | 智能规划、融合与 fallback |
| `GET /` 或 `/search` | 引导到后台，执行搜索使用 POST |
| `GET /smart-search/metrics` | 仅原生 proxy admin/admin viewer |
| `POST /smart-search/feedback` | 仅原生 proxy admin |

后台应用 key 仅允许原生搜索 POST 接口，不能访问 LiteLLM 的 key/config 管理路由；可搜索全部启用配置。master key 不作为普通应用凭据。自有 key 由 SQLite 持久化，未启用原生 LiteLLM DB virtual-key/spend 持久化。

自动请求支持 query（字符串或最多 10 项列表）、max_results（1–20）、search_domain_filter、max_tokens_per_page、country，以及 profile/profile_prompt/constraints/debug/fusion。客户端不得覆盖服务凭据、api_base、headers 或内部 metadata。所有搜索路径与后台写请求限制到 128KB。

constraints：freshness 为 auto/any/day/week/month/year；authority/recall/precision/semantic/source_diversity/latency/cost 为 auto/low/medium/high。latency_budget_ms 为 100–60000，cost_budget_usd 为 0–10。数字预算覆盖类别预算，模型见 [models.py](src/bensz_search/models.py)。

## 数据与维护

SQLite 位于 Docker `search-data` 数据卷，用户、session、provider 和应用 key 在重启/重建后保留。`docs/deploy/.env` 的 `BENSZ_SEARCH_SECRET` 是加密密钥，必须与数据库一起备份，不能在重启时重新生成。

```bash
# 重建镜像，保留数据
docker compose -f docs/deploy/compose.yaml up -d --build --wait
docker compose -f docs/deploy/compose.yaml ps
```

备份时停止服务，复制整个 `/app/data` 并妥善保存 `docs/deploy/.env`，然后重新启动。不要用 `docker compose -f docs/deploy/compose.yaml down -v` 日常重启，它会删除数据卷。详见 [部署说明](docs/deploy/README.md)。

默认非 root 容器、移除 Linux capabilities、禁止权限提升，限制内存/并发/PID/日志。本次是单机单进程部署；运行指标、熔断、历史重启清空，配置与身份持久化。公网 HTTPS 和多节点部署需另行配置，本地无需域名服务器。

## 开发与验证

```bash
sh scripts/uv.sh sync --extra dev
sh scripts/uv.sh run pytest -q
sh scripts/uv.sh run ruff check src tests demo scripts docs/deploy
sh scripts/uv.sh run ruff format --check src tests demo scripts docs/deploy
```

开发命令统一使用 `scripts/uv.sh`，入口将虚拟环境固定在 `.bensz-api/.venv/`，uv 依赖缓存放在 `.bensz-api/uv-cache/`；pytest 与 Ruff 配置分别将缓存固定在 `.bensz-api/.pytest_cache/` 和 `.bensz-api/.ruff_cache/`。直接执行原生 `uv sync` / `uv run` 不会加载该入口设置，会使用 uv 默认的根目录 `.venv/`。

60 条路由 benchmark 位于 [routing.json](tests/benchmarks/routing.json)，允许多个合理 provider。其余测试覆盖原生 API、权限、融合、fallback、登录/CSRF/撤销、配置热更新、加密和持久化。真实外部检索及后台浏览器证据见 [0.2 验收记录](docs/smart-search-router/production-verification.md)。

### 协议开发用模拟环境

fixture 仅用于开发测试，使用独立项目/端口避免覆盖真实服务：

```bash
BENSZ_SEARCH_PORT=8900 LITELLM_MASTER_KEY=sk-bensz-search-local-demo \
  docker compose -f docs/deploy/compose.yaml -p bensz-search-fixtures -f docs/deploy/compose.demo.yaml up -d --build --wait
LITELLM_MASTER_KEY=sk-bensz-search-local-demo \
  sh scripts/uv.sh run python scripts/demo.py --base-url http://127.0.0.1:8900
```

模拟结果标注 `DEMO FIXTURE`。旧 8899 live demo 独立于当前 8898 产品部署，不作为主入口。

## 文档与边界

- [Upstream 审计](docs/smart-search-router/architecture-audit.md)、[设计](docs/smart-search-router/proposed-design.md)、[当前实施计划](docs/plans/2026-10-02-production-admin.md)。
- 六意图：general、news、academic、deep、people、coding。profile_prompt 使用有限规则，未提供完整自然语言 planner。
- 预估成本是配置先验，不是供应商账单；严格 freshness 过滤无日期结果；authority 是排序偏好，不能保证证据等级。
- SQLite 适合当前单实例，未验收多节点或原生 LiteLLM virtual-key DB/Redis 模式。
- 升级 LiteLLM 前重新审计、更新 lock，并验证后台/API 和实际检索；扩展不修改 upstream 源码。

## English overview

**bensz-search** is a task-aware search service on LiteLLM 1.103.2 with no upstream source changes. Version 0.2 adds a Chinese console with authenticated users, encrypted persistent provider settings, live tests, search playground and revocable API keys.

Run `python docs/deploy/deploy_local.py`, open `http://127.0.0.1:8898/admin`, and read initial credentials from the ignored `docs/deploy/.secrets/local-admin.txt`. The default deployment performs real retrieval through an existing SearXNG instance; commercial providers require operator-supplied keys. Configuration and identities persist in a Docker volume. Telemetry/circuit breakers remain process-local. Remote hosting and TLS are outside this local deployment.
