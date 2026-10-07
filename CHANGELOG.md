# Changelog

## [Unreleased]

### Added

- 新增应用卡死与页面切换性能诊断、分阶段优化计划：通过隔离 SQLite 锁竞争和真实 Chrome 合成 API 实验定位同步等待阻塞事件循环、重复取数与整页加载依赖；明确 dudu 缓存机制对照、性能验收和部署一致性要求，区分已复现机制与待核实的线上触发条件。

## [1.0.8] - 2026-10-07

### Changed

- 提升后台与用户工作区的文字可读性：正文和输入控件使用 16px，导航与表格正文使用 15px，表头和表单标签使用 14px，辅助说明使用 13–14px；统一正文行高并增强关键标签及搜索摘要的文字对比度，保留 28px 页面标题和 44px 控件高度。
- 同步中英文 README、部署配置、现行部署说明及产品内更新说明，校正旧版本引用；发布仍限定为 Docker Hub 单一 amd64 镜像。

## [1.0.7] - 2026-10-07

### Added

- 访问密钥支持直接永久删除：用户可删除本人密钥，管理员可删除全体密钥；有效、已撤销和已过期状态均提供删除与不可恢复确认，删除后立即失效并刷新列表，保留历史审计及原有撤销接口语义。

### Changed

- 优化侧栏导航层级：管理员的“管理员 / 用户”分组内菜单缩进并增加浅色层级线；普通用户直接显示平级个人菜单，移除多余的分组标题与折叠操作。
- 统一后台输入框、下拉框与日期控件的高度、边框和焦点样式，改善 Search API、密钥与用户列表筛选条的对齐；重新组织搜索高级选项与审计筛选布局，适配桌面、平板及手机。
- 逐页走查后台与用户区弹窗，修正运行概览按钮对齐、手机表单重复间距、服务配置工具按钮间距和抽屉底部操作裁切；统一文件上传控件及测试、重新登录的操作区。

## [1.0.5] - 2026-10-07

### Added

- 落实商业后台优化计划：运行概览展示按服务成功率、延迟直方图分位、费用估算、健康/熔断/冷却和最近 20 条调用；调试台增加高级约束、域名过滤、执行时间线、cURL 与会话内结果保留。
- 在现有 SQLite 中新增每日用量与审计日志；支持近 7/30 个 UTC 日统计、用户角色编辑/密码重置/停用、全体密钥管理、密钥期限与 Search API/协议权限范围、登录会话列表及退出其他设备、无密钥服务配置导入导出。
- 原生 ES 模块与默认转义组件、语义设计变量、暗色主题、手机卡片列表、筛选排序、配置抽屉及保存并测试、引擎同步、帮助和版本检查；新增正式三视口 UI 冒烟脚本与治理回归测试。

### Changed

- 明确产品与软件版本号只能由人类决定：AI 仅按人类明确指定的目标版本号同步修改，未指定时保留现有版本并记录到 `[Unreleased]`；SemVer 不构成自动调整版本号的授权。
- 按指定发布版本将未发布的 1.1.0 后台更新与 1.0.5 品牌区修订统一交付为 1.0.5；同步包版本、依赖锁、本地 Compose、中英文 README 与部署文档。精简发布仅推送 Docker Hub `linux/amd64` 的 `1.0.5` 和 `latest`，创建 GitHub Release 并更新服务器搜索服务。
- 统一局部刷新、焦点与滚动恢复、消息队列、字段错误、未保存变更保护，以及会话过期后的表单保留与重新登录。保留现有原生搜索和协议接口的鉴权及响应兼容性。

### Fixed

- 修复编辑/启停服务清空引擎证据：仅保留未提交证据字段，明确空值可清除，换实例失效；同步保存使用原子比较并写入，热更新串行发布。
- 修复临时测试及热更新遗留 LiteLLM 回调、原生显式多查询费用漏计、MCP 无尾斜杠入口与权限错误状态、空结果健康误判；增加并发迁移、最后管理员保护和跨入口用量回归。

- 参考 bensz-router 调整工作区品牌区：版本号移至左上角产品名下方，以灰色小字显示，替换原副标题并移除右上角版本徽章；管理员与用户工作区、手机顶部品牌区保持一致，保留动态版本、缺失提示和无障碍标签。修订版本更新为 1.0.5。

## [1.0.4] - 2026-10-07

### Added

- 原生 `bensz_search` 搜索源：后台配置远端实例与访问密钥，支持显式、auto、planned 和 MCP 共用执行；递归组合使用循环检测、层数限制、剩余 deadline、互不重叠的调用额度及子树费用估算。远端先验证联邦支持，不跟随重定向；保留叶子来源与实例路径，抑制重叠来源投票并传递部分成功。参与组合的实例需升级到支持联邦搜索的版本。

### Changed

- 将正式依赖锁文件迁至 `.bensz-api/uv.lock` 并继续纳入 Git；`scripts/uv.sh` 临时链接适配 uv 固定路径，退出后清理，拒绝并发调用和冲突锁文件。同步 Docker 构建入口、构建忽略规则、开发文档及目录约定。
- 按指定发布版本将尚未发布的 1.1.0 工作区更新与 1.0.4 修复统一交付为 1.0.4；同步包版本、锁文件、本地 Compose 镜像标签、中英文 README 和部署文档。本次精简发布只构建和推送 Docker Hub `linux/amd64` 的 `1.0.4` 与 `latest` 标签，GitHub Release 使用源码归档；不触发 GitHub Actions。

### Fixed

- 修复 Serper 将额度耗尽作为 HTTP 400 返回时被误判为 `bad_request`：按供应商与明确错误正文识别 `quota`，恢复自动搜索 fallback 和额度故障冷却，后台测试提示检查余额或充值。保留真正参数错误的分类，不向客户端返回供应商原始错误或凭据。
- 修复共用搜索执行器在嵌套请求取消时未读取原 gather 异常的问题；取消后清理并回收所有相关任务。

## [1.0.3] - 2026-10-05

### Added

- 独立 `/admin` 管理员后台与 `/app` 用户工作台，各自导航和概览；成员自动进入个人区，管理员可切换两区。个人概览展示本人密钥与可用来源，页面地址支持刷新与前进后退；沿用既有服务端权限、会话与安全头。
- 新增与中文结构、示例和能力边界一致的英文 README。

### Changed

- 首页登录入口与后台采用统一系列视觉：浅灰画布、蓝色主操作、浅色侧栏、细边框面板及中文衬线标题；增加搜索流程示意和产品介绍，保留搜索与管理接口及表单对齐。
- 侧栏上下排列“管理员 / 用户”两区，可独立折叠，区内页面直接平铺；保留导航历史、键盘操作和移动端菜单行为。
- 按指定发布版本将尚未发布的 1.0.2、1.1.0 和 1.1.1 工作区更新统一交付为 1.0.3；同步包版本、锁文件、本地 Compose 镜像标签、README 和部署文档。
- 本次精简发布只构建和推送 Docker Hub `linux/amd64` 的 `1.0.3` 与 `latest` 标签，GitHub Release 使用源码归档；不触发 GitHub Actions。

### Fixed

- 后台右上角头像旁常显当前运行服务的安装版本，移动端保留显示；`/app` 入口具有与 `/admin` 一致的安全头，成员权限继续由服务端校验。

## [1.0.1] - 2026-10-04

### Fixed

- 修复默认 SearXNG 仅配置 GitHub/PubMed 的覆盖不足：扩充为 11 个网页、百科、代码、学术和新闻来源，自动路由按意图选择已配置引擎；增加后台常用引擎填入按钮、实例设置模板和已有部署更新说明。保留自定义列表及明确留空行为，修订版本更新为 1.0.1。
- 修复服务器 HTTPS 登录被同源检查拒绝的代理配置：仅信任实际反向代理 IP 的转发头，启用 Secure Cookie；补充可信/非可信代理及跨站登录回归测试、初始化管理员说明。
- 修复浏览器首页被 LiteLLM 内嵌鉴权路由遮蔽而返回 403：优先匹配项目 GET 入口并跳转登录后台，保留搜索和管理 API 鉴权；修订版本更新为 1.0.1。服务器部署支持通过 `BENSZ_SEARCH_IMAGE` 选择修复镜像。

### Changed

- 服务器搜索和 SearXNG 容器统一使用已有外部网络 `npm_default`，取消项目默认网络。
- 调整服务器部署为 `docker-compose.yml`、`latest` 镜像、固定容器名和仅 `expose`；数据使用项目内 bind mounts，独立部署 SearXNG，迁移持久化服务地址并保留原数据备份。新增对应服务器部署模板与说明。

## [1.0.0] - 2026-10-04

### Added

- 新增 Responses 宿主规划搜索教程与 AI 算力流转原理图，说明能力发现、planned/auto、工具结果回填、累计限制、凭据与费用边界，并在 README 和中文接入指南添加入口。
- 落实全球搜索协议：新增 v1 能力/查询/计划/结果 Schema、HTTP facade 与 MCP SDK Streamable HTTP 入口，共用 Key/team 权限、配置快照、执行与结果逻辑。
- 增加外部逐调用计划、显式查询 fallback、dry run、默认状态/来源/费用依据、限制与租户限流；SearXNG 管理员实例引擎同步与验证依据。
- 增加 Python/TypeScript 客户端及 Responses/Chat/Anthropic/Gemini/Ollama 有界循环、流式完整组装、上下文保留、结构化/host auto 备用路径及受控 Codex experimental handler。
- 增加 DOI/PMID/arXiv 保守去重、来源别名/日期冲突/内容类型和体积限制，补齐中英文教程、模型矩阵、部署容量边界与验收记录；未有凭据的模型保持待验证。

- 补充 AI 与 bensz-search 的交互协议设计，明确模型可见工具说明、动态能力清单、发现/规划/执行/复核循环、职责边界与跨轮预算；同步全球接入计划和审计，新增能力仍为拟议设计。
- 新增跨模型搜索协议现状审计与全球主流 LLM 接入优化计划，明确能力发现、外部 AI 分引擎查询、标准结果、无插件接入及 OpenAI/Anthropic/Gemini/Grok/中国大陆与自托管模型适配的阶段、兼容边界和验收条件；本次仅交付审计与计划。
- 增加 OpenAI Responses `web_search` 项目适配器，支持后台加密配置、模型/上下文/输出上限、连接测试、显式搜索与自动路由/融合/fallback；提取真实引用及来源、URL 去重、域名/地区过滤，标记生成摘要，保持 `/search` 响应兼容。
- 补充 OpenAI 协议与鉴权回归测试、配置示例、源码审计及 Docker/浏览器验收记录。

- 新增 Exa、Brave、Tavily、Serper、Perplexity 与 SearXNG 的搜索 API 添加教程，说明密钥获取、后台字段、地址规则、连接验证、首次导入及应用调用，并在 README 和部署说明添加入口。

### Changed

- 将根目录 `Prompts.md` 加入 Git 忽略规则，移除本地 Git 提交历史中的文件版本，保留本地内容；远程历史同步需强制推送重写后的分支。
- 新功能版本从唯一配置源更新为 0.4.0；旧规则路由改用共用执行器，保留原生显式调用与后台行为。
- 原生工具清单也按 Key/team 交集过滤；新协议错误响应统一脱敏 envelope，HTTP/MCP 断连取消子任务。

- 明确全球 LLM 接入计划中搜索 API/工具契约与 MCP 的分工：直接 HTTP 和 MCP 入口共享搜索服务逻辑，MCP 生态接入纳入 P1，并补充工具发现、无插件交付、版本边界与两种入口一致性验收；同步 AI 交互设计。
- 统一贡献记录到 `docs/contribution.bac`，归入两份任务账本的完整历史并删除独立文件；同步文档引用，明确后续任务只追加主账本。
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
