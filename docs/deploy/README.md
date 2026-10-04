# 本地产品部署与维护

对应 bensz-search 1.0.0 / LiteLLM 1.103.2，部署范围为单机 Docker。当前项目要求先在本机验证，未配置公网入口。

## 部署文件与运行目录

Dockerfile、Compose 配置、部署脚本和环境变量示例统一位于本目录。以下命令均从项目根目录执行；脚本可从任意工作目录调用。私有配置和初始登录信息统一保存在 `docs/deploy/.env` 与 `docs/deploy/.secrets/`，均忽略入库；已有配置与数据卷继续沿用。Compose 自动从部署目录读取 `docs/deploy/.env`，Shell 中同名环境变量仍优先。

- `Dockerfile`：以项目根目录为构建上下文。
- `Dockerfile.dockerignore`：Dockerfile 专属忽略规则，排除私有配置、缓存和文档。
- `compose.yaml`：默认真实服务；`compose.demo.yaml`：模拟测试；`compose.live.yaml`：独立 live demo。
- `deploy_local.py`：生成私有配置并部署；`.env.example`：环境变量示例。

单独构建镜像使用 `docker build -f docs/deploy/Dockerfile -t bensz-search:1.0.0 .`。

## 初始化与登录

运行 `python docs/deploy/deploy_local.py`。脚本仅在 `docs/deploy/.env` 不存在时生成凭据，不覆盖已有内容，然后构建真实服务并等待健康。默认连接本机已有 `8080` SearXNG，不修改其设置；需要该实例启用 JSON、GitHub/PubMed 引擎。

后台 `http://127.0.0.1:8898/admin`；初始登录信息保存在项目忽略的 `docs/deploy/.secrets/local-admin.txt`。管理员在个人设置改密后，文件中的初始密码不再有效。只有首次空库时使用环境中的 bootstrap 账号，重启不重置密码。

没有 SearXNG 时，先运行 `python docs/deploy/deploy_local.py --init-only`，把 `docs/deploy/.env` 的 `SEARXNG_API_BASE` 清空，再执行部署。后台仍可登录添加商业 API，未启用 provider 时 `/ready` 返回 503。

## 配置与运行

Search API 页面支持六类原生 adapter 和 OpenAI Web Search 项目适配器，多条同类型配置。保存、启停和删除会建立新的 Router/Registry，下一次请求立即使用新配置，不需要手动重启。旧请求允许完成；配置更新重置熔断状态。连接测试可以测试尚未启用的服务，但不会把它加入自动路由。

各供应商的密钥获取入口、服务地址填写值和测试步骤见[搜索 API 添加教程](../search-api-setup.md)。

`docs/deploy/.env` 与 `config/litellm.yaml` 仅作为第一次导入来源；后续改动通过后台保存。服务凭据用独立 `BENSZ_SEARCH_SECRET` 加密，后台不回显完整 key。服务地址只允许无嵌入凭据/查询参数的 HTTP(S) URL；内网地址供受信管理员接入自己的服务。

SearXNG 的 HTTP 200 可能同时含引擎故障和空结果。测试页根据实际结果判成功；可在 SearXNG 实例检查 CAPTCHA/限流，后台更换到真实可用引擎，或添加有凭据的商业源。本机的免费配置覆盖已验证的 GitHub/PubMed，不宣称覆盖全部网页场景。

OpenAI 可直接在后台添加，填写 Key、支持 `web_search` 的模型和 30000ms 超时；默认地址 `https://api.openai.com/v1`。首次空库也可通过 `OPENAI_API_KEY`、`OPENAI_SEARCH_API_BASE` 和 `OPENAI_SEARCH_MODEL` 导入；已有数据库使用后台新增。模型生成摘要与来源链接分开标注，真实调用需账号额度。参见 [OpenAI 接入说明](../smart-search-router/openai-web-search.md)。

## 身份与 API 调用

管理员可增删后台用户，成员不能修改 provider/用户。登录为 12 小时 session，注销或改密后撤销会话；改密不自动撤销独立应用 key，需在访问密钥页面撤销。删除用户级联删除其会话和 key。

后台生成的 key 仅能 POST 到搜索路径，默认允许当前全部启用服务；不开放原生 LiteLLM 管理路由，不提供按用户账单或原生 virtual-key DB 管理。应用应使用专属 key 而非 master key。完整 key 仅在生成时展示，列表仅保存哈希/前缀，撤销立即生效。

Cookie 为 HttpOnly/SameSite Strict；写接口检查 CSRF 与 Origin。当前纯本机 HTTP 设置 `BENSZ_SEARCH_COOKIE_SECURE=false`，将来部署 HTTPS 时设置 true。登录限速、运行指标和熔断均为单进程，当前部署不启用多 worker。

## 持久化、备份和恢复

数据库位于容器 `/app/data/admin.sqlite3`，Docker named volume 为 `bensz-search_search-data`。加密检查会在密钥不匹配时拒绝启动，避免静默丢失凭据。

为避免正在写入的 SQLite/WAL 不一致，本机备份采用短暂停机复制。以下文件都保留在项目内，不上传：

```bash
mkdir -p docs/deploy/.secrets/backups
chmod 700 docs/deploy/.secrets/backups
docker compose -f docs/deploy/compose.yaml stop search
docker compose -f docs/deploy/compose.yaml cp search:/app/data docs/deploy/.secrets/backups/search-data
cp docs/deploy/.env docs/deploy/.secrets/backups/env.backup
chmod 600 docs/deploy/.secrets/backups/env.backup
docker compose -f docs/deploy/compose.yaml start search
```

已有备份时改用新的备份子目录，避免目录层级嵌套或覆盖。恢复时停止服务，将备份目录中的数据库和 WAL/SHM（若存在）复制回 `/app/data`，恢复对应 `docs/deploy/.env` 中的加密密钥，确认文件属主可被容器 uid 10001 读写，然后启动。恢复不是本次验收实际执行的操作。

更新代码使用 `docker compose -f docs/deploy/compose.yaml up -d --build --wait`，保留数据卷。不要使用 `down -v` 做日常重启。日志限制每文件 10MB、3 个轮转；容器限制 1GB 内存、128 PID 和 64 并发。

## 版本与验证边界

版本唯一维护于 `pyproject.toml`，镜像标签对应 1.0.0。依赖由 `uv.lock` 固定，upstream 未修改。升级前运行后台/原生 API 测试、routing benchmark 和真实搜索，不能只改依赖版本范围。

`/health/liveliness` 是进程检查；`/ready` 是配置检查；后台“测试”才验证外部检索。当前已通过的本机验收见 [production-verification.md](../smart-search-router/production-verification.md)。商业源无凭据时只验证配置链路，公网 TLS、多节点和原生 LiteLLM DB 模式未验收。

2026-10-02 部署目录迁移验证：生产、fixture 和 live 的 Compose 配置均可解析；生产服务参数、环境变量名、端口和数据卷与迁移前一致。部署目录 `.env` 的读取和端口变量插值、脚本的幂等初始化及文件权限、迁移后的 Docker 镜像构建均通过。私有配置迁移时校验了文件内容与权限，继续被 Git 和构建上下文忽略。

## 全球搜索协议与 MCP

新版镜像提供 HTTP `/bensz-search/v1/capabilities` 与 `/bensz-search/v1/search`，以及独立 MCP `/bensz-search/mcp/`。应用 Key 可访问这些入口；后台仍需登录会话。先读[协议与接入教程](../smart-search-router/protocol/README.md)，不要把 MCP URL 当作直接 HTTP API 根地址。

默认最多 10 个物理调用（包括 fallback），每请求 3 个并发，每租户 4 个同时搜索请求、每分钟 60 个搜索请求；单条片段 2000 字符，结果体 128000 字节。环境变量列于 `.env.example`。默认单进程，进程内限流和熔断没有跨实例共享；不要仅增加 uvicorn workers 来扩大承诺容量。Docker 网关并发限制 64、内存 1GB 是部署保护边界，不能当成已验证的真实 provider 吞吐量。

远程部署在网关前配置 HTTPS，保留 Authorization、MCP-Protocol-Version、Accept 和 Content-Type。反向代理请求体上限至少 128KB，读超时应高于最长 provider 期限（建议 75 秒）；禁用 MCP 位置的代理缓冲。配置 `BENSZ_SEARCH_MCP_ALLOWED_HOSTS` 为实际公网 Host（有端口时包含端口），浏览器宿主还需将实际 Origin 加入 `BENSZ_SEARCH_MCP_ALLOWED_ORIGINS`。不开放任意 wildcard origin 或带凭据的公共 CORS。

```nginx
location /bensz-search/ {
    proxy_pass http://127.0.0.1:8898;
    proxy_set_header Host $http_host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header MCP-Protocol-Version $http_mcp_protocol_version;
    proxy_read_timeout 75s;
    proxy_buffering off;
    client_max_body_size 128k;
}
```

选择靠近用户和搜索源的区域，分别验证模型渠道与 provider 的地域可达性；不自动翻译用户 query，不用 country 替代语言。不同区域实例拥有自己的 URL、访问密钥和轻量存储。当前没有多实例状态共享需求的实测依据，保持单实例状态边界；扩容前测量真实 p50/p95、限流、来源覆盖及供应商账单，再决定共享机制。

保留凭据加密及 SQLite 数据卷备份策略。日志/指标不记录查询或结果正文；没有服务器搜索结果缓存。应用宿主负责对话数据保留、模型请求内容和客户端能力缓存；搜索源有自己的数据处理政策。公开 Web 应用通过后端请求，桌面应用使用系统安全存储，不能内置共享 provider/管理员密钥。

`BENSZ_SEARCH_MCP_ENABLED=false` 只停用 MCP；`BENSZ_SEARCH_PROTOCOL_ENABLED=false` 停用新搜索业务入口。旧原生搜索继续可用。未知结果的计费请求不会自动重放，目前没有持久任务恢复或幂等计费承诺。

独立 Docker + HTTP/MCP 真实 SearXNG 验收与模拟性能基线见[验证报告](../smart-search-router/protocol/verification.md)。模型凭据缺失时只标注离线契约通过，不能据此发布“全部模型兼容”。
