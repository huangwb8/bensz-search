# Changelog

## [Unreleased]

### Added

- 新增跨模型搜索协议现状审计与全球主流 LLM 接入优化计划，明确能力发现、外部 AI 分引擎查询、标准结果、无插件接入及 OpenAI/Anthropic/Gemini/Grok/中国大陆与自托管模型适配的阶段、兼容边界和验收条件；本次仅交付审计与计划。
- 增加 OpenAI Responses `web_search` 项目适配器，支持后台加密配置、模型/上下文/输出上限、连接测试、显式搜索与自动路由/融合/fallback；提取真实引用及来源、URL 去重、域名/地区过滤，标记生成摘要，保持 `/search` 响应兼容。
- 补充 OpenAI 协议与鉴权回归测试、配置示例、源码审计及 Docker/浏览器验收记录。

- 新增 Exa、Brave、Tavily、Serper、Perplexity 与 SearXNG 的搜索 API 添加教程，说明密钥获取、后台字段、地址规则、连接验证、首次导入及应用调用，并在 README 和部署说明添加入口。

### Changed

- 新功能版本更新为 0.3.0；后台显式调试请求传递统一域名、地区及页面 token 参数；服务启停保留 OpenAI 模型和输出限制。

- 统一后台输入框、下拉框与主要按钮为 44px，修复搜索筛选控件高度不一致、查询按钮错位、长标签和帮助文案造成的同行错位；统一移动端表单间距、弹窗布局与禁用态。修订版本更新为 0.2.1。
- 将本地 Python 环境、pytest 与 Ruff 缓存迁入 `.bensz-api/`；配置测试/检查缓存路径，增加固定虚拟环境和依赖缓存路径的开发入口 `scripts/uv.sh`，同步 Docker 环境路径、开发命令和目录约定。
- 将 Docker 部署文件、初始化脚本、环境变量示例和部署说明统一迁移到 `docs/deploy/`，私有 `.env` 与 `.secrets/` 同步迁入并继续忽略入库；修正构建上下文、配置路径与文档命令，保留已有凭据与数据卷。
- 在项目目录约定中明确 Docker 部署相关代码和脚本的托管位置。

## [0.2.0] - 2026-10-02

### Added

- Chinese login console with provider management/tests, search playground, access keys and user management.
- SQLite persistence, encrypted credentials, scrypt passwords, protected sessions and revocable application keys.
- Administrator/member permissions, CSRF/origin checks and bounded login attempts.
- Provider runtime updates, multiple configurations per provider and intent-specific SearXNG engines.
- Real local deployment initializer, persistent data volume, readiness and container resource limits.

### Changed

- Main port 8898 runs the real product; fixtures require an explicit development deployment.
- Browser entries redirect to the console; native POST search remains compatible.
- Application keys are confined to search routes; credential/network overrides and oversized bodies are rejected on all search paths.
- Updated project instructions for the user-requested management console.
- Restored the architecture audit from installed 1.103.2 source; the prior file incorrectly contained project configuration.
- 清理参考源码与依赖缓存中的嵌套 Git 元数据，归档备份并保留源码；规定项目只保留根 Git 仓库，关闭项目工作区的嵌套仓库自动发现。

## [0.1.0] - 2026-10-02

- Added upstream audit, proposed design and staged implementation plan.
- Added deterministic six-intent smart search with six configurable provider profiles.
- Reused LiteLLM Search adapters and native explicit routing without upstream changes.
- Added bounded parallel execution, estimated cost reservations, timeout/fallback and process-local circuit breakers.
- Added canonical URL deduplication and source-family-aware RRF/weighted RRF.
- Preserved gateway authentication and intersected key/team permissions for auto/fallback tools.
- Added debug diagnostics, structured telemetry and administrative feedback counters.
- Added 60 routing benchmark cases, offline/HTTP tests, Docker packaging and separate synthetic/live demos.
- Included Prisma runtime error types to preserve native authentication errors without adding a database.
