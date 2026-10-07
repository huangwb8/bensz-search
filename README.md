<div align="center">
  <h1>bensz-search</h1>
  <p><strong>为应用与 AI Agent 提供统一的搜索入口</strong></p>
  <p><a href="https://github.com/huangwb8/bensz-search/releases"><img alt="GitHub Release" src="https://img.shields.io/github/v/release/huangwb8/bensz-search"></a> <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-blue"> <img alt="LiteLLM 1.103.2" src="https://img.shields.io/badge/LiteLLM-1.103.2-blue"> <img alt="Docker linux/amd64" src="https://img.shields.io/badge/Docker-linux%2Famd64-blue"></p>
  <p><a href="README_EN.md">English</a> · <a href="docs/search-api-setup.md">搜索配置</a> · <a href="docs/smart-search-router/protocol/README.md">HTTP / MCP 协议</a> · <a href="docs/deploy/server-deployment.md">服务器部署</a></p>
</div>

基于 LiteLLM 1.103.2 的独立扩展，不修改 upstream 源码。管理员连接搜索源、测试服务并管理用户；成员在个人工作台搜索并创建应用访问密钥。自动搜索按任务和约束选择服务，处理超时、fallback、去重和 weighted RRF 融合。外部 AI 可先发现能力，再提交逐引擎查询计划。

当前发布 `v1.0.8`；官方镜像为 [`huangwb8/bensz-search:1.0.8`](https://hub.docker.com/r/huangwb8/bensz-search)，仅 `linux/amd64`，同时提供 `latest`。首次部署需要配置可用搜索源；商业服务需要自己的 API Key。

## 快速开始

需要 Docker Compose 2.24.4+、Python 3.11+，以及支持 JSON 输出的 SearXNG 实例或商业搜索凭据。Python 包支持 3.11–3.13；镜像使用 3.11。

```bash
python docs/deploy/deploy_local.py
curl --noproxy '*' http://127.0.0.1:8898/health/liveliness
curl --noproxy '*' http://127.0.0.1:8898/ready
```

脚本在私有 `docs/deploy/.env` 生成独立 master key、加密密钥和初始管理员密码，保留已有配置。打开 [管理员后台](http://127.0.0.1:8898/admin)，用初始账号 `admin` 和 `docs/deploy/.secrets/local-admin.txt` 中的密码登录；成员入口为 [用户工作台](http://127.0.0.1:8898/app)。存活检查验证进程，就绪检查验证启用配置，后台连接测试验证外部检索。

默认 SearXNG 地址为 `http://host.docker.internal:8080`，需要实际运行实例或在后台配置其他来源。本地仅绑定回环端口；服务器使用[服务器 Compose](docs/deploy/docker-compose.yml)、外部代理网络与独立 SearXNG，详见[部署说明](docs/deploy/server-deployment.md)。

## 配置与工作台

| 工作区 | 入口 | 能力 |
|---|---|---|
| 管理员后台 | `/admin` | 全局概览、Search API 配置与真实测试、用户与全体密钥管理、审计和搜索 |
| 用户工作台 | `/app` | 可用来源和个人密钥概览、搜索、接入指南、账号设置 |

管理员侧栏保留“管理员 / 用户”两个可折叠分组，组内菜单缩进并以浅色层级线提示；成员直接显示平级个人菜单。页面支持刷新与浏览器前进后退，左上角产品名下方显示运行版本，移动端保持可用。角色和密钥归属由服务端校验。

**v1.0.8** 提升后台与用户工作区的可读性：正文和输入控件为 16 px，导航与表格为 15 px，标签为 14 px，并统一行高和文字对比度；页面标题和控件高度保持一致。

**v1.0.7** 新增访问密钥永久删除：用户可删除本人密钥，管理员可删除全体密钥，有效、已撤销与已过期状态均可删除，删除立即失效并保留历史审计。同步优化侧栏导航层级、表单控件高度、筛选条对齐与弹窗操作区；见[后台使用说明](docs/smart-search-router/commercial-admin.md)。

**v1.0.5** 新增后台治理和运行观测。概览可切换本进程与近 7/30 个 UTC 日汇总；延迟分位是直方图区间上界估算，费用为配置估算。用户编辑、密钥期限与权限范围、会话管理和配置导入导出见[后台使用说明](docs/smart-search-router/commercial-admin.md)。

`v1.0.4` 新增 **bensz-search 实例递归组合**，支持循环检测、调用额度、超时与底层来源去重；见[接入说明](docs/smart-search-router/federated-search.md)。参与组合的实例需升级到支持联邦搜索的版本。

支持 **OpenAI Web Search、Exa、Brave、Tavily、Serper、Perplexity、SearXNG、bensz-search**，可配置多个同类服务。保存后即时影响新请求；编辑时 API Key 留空保留同类型密钥，换类型不继承旧密钥。数据库仅首次导入环境配置，此后以后台设置为准。见[搜索 API 教程](docs/search-api-setup.md)。

OpenAI 使用 Responses `web_search`，默认 `gpt-4.1-mini`，结果标注生成摘要；见 [OpenAI 说明](docs/smart-search-router/openai-web-search.md)。SearXNG 默认列出 11 个常用引擎，需实例实际支持并启用；按任务选择子集，历史真实验收覆盖 GitHub/PubMed。见[引擎说明](docs/smart-search-router/searxng-default-engines.md)。

## 调用搜索与 AI 接入

在用户区“我的密钥”创建应用专属 key，注入 `BENSZ_SEARCH_API_KEY`。完整值只显示一次，撤销、删除或过期立即拒绝新请求；有效、已撤销和已过期密钥均可直接删除；可选 `search` / `protocol` 权限，默认兼容两者。停用用户同时拒绝其会话和独立 key；应用 key 与登录密码分离。

```bash
curl --noproxy '*' http://127.0.0.1:8898/search \
  -H "Authorization: Bearer ${BENSZ_SEARCH_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"query":"colorectal cancer ctDNA","search_tool_name":"auto","profile":{"type":"scientific_research","domain":"biomedical"},"max_results":5,"constraints":{"latency_budget_ms":15000},"debug":true}'
```

原生响应保持 `{"object":"search","results":[...]}`。debug 增加计划、执行、错误分类、预估费用、来源重叠和融合贡献，不返回原始 query/profile_prompt。

| 入口 | 用途 |
|---|---|
| `POST /search`、`/v1/search` | 自动路由，或指定 `search_tool_name` |
| `POST /search/<name>`、`/v1/search/<name>` | 路径中的工具名称优先 |
| `GET /bensz-search/v1/capabilities` | 按 key 权限发现工具与已验证引擎 |
| `POST /bensz-search/v1/search` | `auto` 或外部 `planned`，支持零调用 `dry_run` |
| `/bensz-search/mcp/` | MCP SDK Streamable HTTP，每个请求携带 Bearer key |
| `GET /bensz-search/v1/schema` | 公开静态请求 Schema |

应用 key 可搜索及发现能力，不能访问后台或原生 LiteLLM key/config 管理路由。GET `/`、`/search` 引导至后台，搜索使用 POST。原生请求支持最多 10 项 query、1–20 个结果及 profile/constraints/fusion；具体参数、预算与鉴权见[协议规范](docs/smart-search-router/protocol/README.md)。

宿主负责模型工具闭环，服务负责鉴权、预算、实际搜索和结果归一化，provider 凭据保留在后台。Python/TypeScript 客户端支持五种模型消息族，已通过离线闭环；真实搜索与 MCP 单独验证，具体真实模型/渠道以兼容矩阵为准。

- [中文接入](docs/smart-search-router/protocol/integration.zh-CN.md) / [English integration](docs/smart-search-router/protocol/integration.en.md)
- [Responses 宿主规划搜索与算力流转](docs/responses-host-planned-search.md)
- [兼容矩阵](docs/smart-search-router/protocol/compatibility.md) / [协议验证](docs/smart-search-router/protocol/verification.md)
- [TypeScript 客户端](clients/typescript/README.md) / [Python 客户端](src/bensz_search/client.py)

## 部署与维护

本地 SQLite 使用 `search-data` named volume；服务器使用项目内 bind mounts。用户、会话、应用 key 和加密 provider 设置持久化；审计、密钥调用次数和每日用量也持久化；进程内健康、熔断和最近调用重启清空。备份数据库须同时保留匹配的 `BENSZ_SEARCH_SECRET`，不能重新生成加密密钥。

```bash
docker compose -f docs/deploy/compose.yaml up -d --build --wait
docker compose -f docs/deploy/compose.yaml ps
```

1.0.5 起自动增量迁移数据库；回退旧镜像须同时恢复升级前的数据库快照。镜像与线上验收见 [v1.0.5 发布记录](docs/deploy/releases/v1.0.5.md)与 [v1.0.8 发布记录](docs/deploy/releases/v1.0.8.md)。

服务器在 `/docker/bensz-search` 先备份旧镜像 ID、Compose、私有配置和 SQLite 数据库，再仅更新搜索服务：

```bash
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.8 docker compose -f docker-compose.yml pull search
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.8 docker compose -f docker-compose.yml up -d --no-deps --wait search
```

容器非 root，限制内存、并发、PID 和日志。当前单机单进程，未验收多实例状态共享。不要用 `down -v` 日常重启。HTTPS 部署启用 Secure Cookie，并只信任实际代理 IP 的转发头。备份、恢复和代理设置见[本地部署](docs/deploy/README.md)和[服务器部署](docs/deploy/server-deployment.md)。

## 开发与验证

```bash
sh scripts/uv.sh sync --extra dev
sh scripts/uv.sh run pytest -q
sh scripts/uv.sh run ruff check src tests demo scripts docs/deploy
sh scripts/uv.sh run ruff format --check src tests demo scripts docs/deploy
for module in src/bensz_search/static/*.js; do node --check "$module"; done
```

入口将 Python 环境、uv/pytest/Ruff 缓存固定在 `.bensz-api/`，依赖锁文件为纳入 Git 的 [`.bensz-api/uv.lock`](.bensz-api/uv.lock)。uv 本身要求根目录锁文件，入口通过临时符号链接适配并在退出后清理；请使用上述命令，同一项目不可同时运行多个入口命令。入口需要 macOS/Linux 上的 `python3`。版本唯一源为 `pyproject.toml`。60 条[路由 benchmark](tests/benchmarks/routing.json)允许多个合理 provider；测试覆盖 API、权限、融合、fallback、持久化及工作台入口。fixture 用法见[部署文档](docs/deploy/README.md)，不能以模拟结果代替真实供应商验收。

## 文档与边界

- [调用链审计](docs/smart-search-router/architecture-audit.md)：依据 LiteLLM 1.103.2 发行包，未取得 upstream Git commit。
- [后台使用与统计口径](docs/smart-search-router/commercial-admin.md) / [后台验收](docs/smart-search-router/commercial-admin-verification.md)
- [界面验收](docs/smart-search-router/series-ui-verification.md) / [早期真实产品验收](docs/smart-search-router/production-verification.md)
- [变更记录](CHANGELOG.md) / [协作规则](AGENTS.md) / [贡献账本](docs/contribution.bac)
- 问题与反馈：[GitHub Issues](https://github.com/huangwb8/bensz-search/issues)。历史计划保留原基线，当前能力以源码、协议和验证记录为准。

预估费用来自配置先验，不是供应商账单。规则 planner 支持六种意图，尚无服务端 LLM planner。外部结果不可信，生成摘要不等于证据；provider 多样性不保证底层来源独立。供应商可达性、限流和真实模型版本须逐项验证，不宣称全模型生产兼容。

仓库尚无独立 LICENSE 文件，不据此声明开源许可；LiteLLM 及其他依赖遵循各自许可。
