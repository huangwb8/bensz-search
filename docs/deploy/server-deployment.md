# 服务器部署

当前镜像与上线验证见 [v1.0.9 发布验收](releases/v1.0.9.md)；下文保留原迁移与修复阶段的历史证据。

## Compose 与访问方式

服务器工作目录为 `/docker/bensz-search`，使用 [docker-compose.yml](docker-compose.yml)。默认镜像为 `huangwb8/bensz-search:latest`，当前发布版本为 `1.0.9`（仅 `linux/amd64`），可在 `.env` 用 `BENSZ_SEARCH_IMAGE` 选择镜像；搜索容器名为 `bensz-search`，独立 SearXNG 容器名为 `bensz-search-searxng`。

两项服务分别 `expose` 8000 和 8080，不发布宿主机端口。两个容器均只连接已有的外部网络 `npm_default`，不创建项目默认网络。反向代理上游填写 `http://bensz-search:8000`；搜索服务访问 `http://bensz-search-searxng:8080`。

从工作目录执行：

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml up -d --wait
docker compose -f docker-compose.yml ps
```

## 项目内持久化

| 相对路径 | 容器内路径 | 内容 |
| --- | --- | --- |
| `./search-data` | `/app/data` | SQLite 用户、访问密钥、加密 provider 配置、用量/审计/站点设置及公共 `assets/` bundle |
| `./searxng` | `/etc/searxng` | 本实例的独立设置 |
| `./searxng-cache` | `/var/cache/searxng` | SearXNG 缓存 |

这些路径以 Compose 所在目录为基准，全部位于 `/docker/bensz-search`。搜索数据目录属主为 `10001:10001`，必须可被搜索容器写入。

私有 `.env` 沿用已有加密密钥、登录和访问配置。首次部署需要按 `.env.example` 设置凭据，并按 `.env.example` 配置 `SEARXNG_ENGINES=google,bing,duckduckgo,brave,baidu,wikipedia,github,stackoverflow,pubmed,arxiv,google news`。SearXNG 的 `settings.yml` 必须具有独立随机 `server.secret_key`、`use_default_settings: true`、HTML/JSON 格式，并启用所选的常用引擎，参考 [实例设置模板](searxng-settings.yml.example)。该实例仅供容器内部调用，设置 `server.limiter: false`。不要复制其他项目的私有配置或 secret。

HTTPS 经 Nginx Proxy Manager 转发时，在 `.env` 设置 `BENSZ_SEARCH_COOKIE_SECURE=true`，并将 `FORWARDED_ALLOW_IPS` 设置为代理容器在 `npm_default` 上的实际 IP（支持逗号分隔多个可信代理）。代理须传递原始 Host 和 `X-Forwarded-Proto`。Uvicorn 默认只信任回环地址，未配置时会把公网 HTTPS 登录当作 HTTP Origin，导致 `Cross-site requests are not allowed`。不要使用 `*` 信任所有来源；代理 IP 变化后更新该配置并重建搜索容器。

首次管理员用户名与密码分别由 `.env` 的 `BENSZ_SEARCH_ADMIN_USERNAME` 和 `BENSZ_SEARCH_ADMIN_PASSWORD` 初始化，仅在空数据库生效；登录后改密，修改 `.env` 或重启不会重置已有密码。登录密码与应用访问密钥不同，应用密钥在后台“访问密钥”页面创建。

Compose 显式设置 SearXNG 地址；同时更新 `.env` 保持一致。已有数据库只在第一次导入环境配置，迁移时还必须更新持久化 provider 的 `api_base`，不能仅修改环境变量。切换实例后，旧实例的引擎验证依据不能自动继承，可在后台重新同步与测试。

### 更新已有实例的搜索源

1. 在现有 `searxng/settings.yml` 合并模板中的 `engines` 配置，保留实例现有 secret 和其他设置，然后执行 `docker compose restart searxng`。首次安装才复制整份模板，并将 secret 占位值替换为独立随机值。
2. 在 `.env` 更新 `SEARXNG_ENGINES`，供未来首次导入使用。已运行的后台需另行编辑 SearXNG 服务，点击 **填入常用引擎**，按可用情况调整后 **保存配置**；新按钮需要运行包含此修复的搜索镜像，旧界面可手动填入同一列表。保存后即时更新路由，不重建数据库。
3. 使用连接测试及搜索调试检查网页、代码、论文与新闻查询。`/config` 同步仅确认实例支持和启用状态，真实查询才能确认当前可用性。失败引擎可从列表移除；要回退时恢复原列表并保存。

此次仓库修复不代表线上容器已更新；以下历史验收仍对应其原部署与引擎配置。

## 迁移与恢复

迁移前在本目录 `.secrets/deployment-<UTC时间>/` 备份原 Compose、`.env` 和数据。停止搜索服务后复制命名卷到 `./search-data`，校验文件哈希，再更新数据库服务地址。保留用户、会话、访问密钥及加密凭据，执行 SQLite 完整性检查后启动。

原 Compose 从工作目录移入私有备份，避免同时留下默认候选配置；原命名卷保留供恢复。恢复时停止新搜索容器，恢复原 Compose 和匹配的环境文件，再启动原服务与原卷。迁移后的新写入需要另行备份，旧卷只代表迁移前状态。日常维护不执行 `down -v`。

1.0.5 新增 SQLite 表与列，保留旧账号、会话、密钥和加密凭据。升级前使用 SQLite backup 或停机复制备份每个数据库，并检查副本完整性；回退到旧代码必须恢复升级前的数据库和匹配配置，不能直接复用迁移后的库。具体升级证据见 [v1.0.5 发布记录](releases/v1.0.5.md)。

更新搜索服务（发布前在本目录私有备份中保留旧镜像 ID、Compose 和 `.env`；命令只更新 `search`，已有 SearXNG 服务保持运行）：

```bash
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.9 docker compose -f docker-compose.yml pull search
BENSZ_SEARCH_IMAGE=huangwb8/bensz-search:1.0.9 docker compose -f docker-compose.yml up -d --no-deps --wait search
```

使用服务器本地构建的修复镜像时，改用 `docker compose -f docker-compose.yml up -d --pull never --wait`，不执行 `pull`。待注册表镜像包含相应修复并验证后，再调整 `BENSZ_SEARCH_IMAGE`。

## 浏览器首页修复

2026-10-04 发现公网与容器内部首页返回 `Managed access keys are only valid for search requests`：LiteLLM 自带的 GET `/` 鉴权路由先于项目首页匹配。项目现在将浏览器 GET 入口前置，首页跳转 `/admin`；后台 API 仍使用登录会话，Search API 仍使用访问密钥。

历史首页修复阶段服务器使用本地构建的 `huangwb8/bensz-search:1.0.1-rn3`，通过 `.env` 的 `BENSZ_SEARCH_IMAGE` 固定选择；此标签没有发布到镜像注册表。[Dockerfile.patch](Dockerfile.patch) 用既有部署镜像重建项目包，适用于依赖与基础镜像兼容的应用修复。构建上下文为项目根目录，示例：

```bash
docker build -f docs/deploy/Dockerfile.patch --build-arg BASE_IMAGE=huangwb8/bensz-search:pre-rootfix-20261004 -t huangwb8/bensz-search:1.0.1-rn3 .
```

修复前 Compose 与环境配置备份位于服务器项目 `.secrets/browser-root-fix-20261004/`；原镜像保留为 `huangwb8/bensz-search:pre-rootfix-20261004`，本地 `latest` 也保留原镜像。恢复时复制匹配的 Compose 与环境备份，再执行 `up -d --pull never --wait`。如果本地 `latest` 后续已变化，先将保留的原镜像重新标记为本地 `latest`。用户数据与搜索配置无需回滚。

## 已验证状态

2026-10-04 已在授权服务器完成上述迁移：

- 两项容器均为 `healthy`，无宿主机端口映射，三项挂载均为项目内 bind mounts。
- 根据用户补充要求，将两个容器的网络统一为 `npm_default`，移除项目默认网络配置。
- 数据复制逐文件哈希一致，SQLite `integrity_check` 为 `ok`；用户、会话、访问密钥、加密凭据及元数据保持一致。
- `/health/liveliness`、`/ready`、v1 能力发现均返回 HTTP 200。
- 经本项目独立 SearXNG 完成真实 GitHub/PubMed 原生搜索；v1 搜索返回 `success` 和 3 条结果。此次验证使用真实外部检索。
- 外部 SearXNG 容器继续服务原项目；搜索服务已切换到本实例。后续将其他应用接入 bensz-search 不包含在本次迁移中。

初次迁移仅从容器内部验证 API；公网访问的补充验证见下文。`latest` 会随发布变化，初次迁移搜索镜像 digest 为 `sha256:b131155a4697102dd65a7e1673462d6df01f15201e0dfcdd247f871a2314fb2a`，SearXNG 为 `sha256:76b0bf285aca014c7191fc4d9234c4bfb358624ac33d8883833d496c059ec072`。

首页修复后补充验证：

- `https://search.benszresearch.com/` 返回 303，跳转 `/admin` 后为 HTTP 200 HTML；JS/CSS 均返回 200。
- 未登录 `/admin/api/session` 返回 401；无密钥 `/search/tools` 和 POST `/search` 返回 401，鉴权仍生效。
- 两个容器均为 `healthy` 且仅连接 `npm_default`；内部 `/ready` 和 SearXNG `/healthz` 均为 200，搜索包版本为 1.0.1。
- 首页修复阶段的本地后台与搜索协议测试共 17 项通过，Ruff 通过；当时公网验证覆盖页面加载与鉴权边界，未执行真实登录或新的外部搜索。

随后修复 HTTPS 登录代理配置，并从外部 HTTPS 客户端完成真实管理员登录（200）、Secure Cookie 与会话检查（200）、CSRF 退出（200）及退出后会话拒绝（401）；跨站登录仍返回 403。增加代理回归测试后共 19 项通过，Ruff 通过。初始配置凭据与当前管理员匹配，验证使用的临时会话已退出，未修改账号密码或执行外部搜索。
