# bensz-search 跨模型协议就绪情况审计

## 审计范围与依据

2026-10-03，依据当前工作区源码，Git 基线 `ecd805370c1527ebd4b8ef460b96555e7b85ff39`，并包含审计时已有未提交改动。项目配置版本为 `0.3.0`，实际安装与锁定的 upstream 为 **LiteLLM 1.103.2 发行包**；未取得对应 upstream Git commit。当前源码与已有部署不是同一个验收对象。

用户希望应用开发者内置标准接入代码，终端用户仅配置搜索服务 URL 和 Key。应用自己的 AI 负责发现搜索能力、选择全部或部分引擎、生成每个引擎的检索式；bensz-search 负责验证、执行、去重、融合并返回标准结果。支持范围面向 OpenAI、Anthropic、Gemini、Grok、中国大陆模型及本地部署模型；无需终端用户安装插件。

本次只审计与制定计划，不实现新协议，不修改部署，不调用付费模型或真实搜索 provider。

## 总体结论

搜索执行与融合已有基础，跨项目的简单搜索 HTTP 调用已经可用。完整的跨模型 Agent 接入协议尚未完成：缺少对应用 Key 开放的能力发现、各引擎查询契约、按调用项执行的外部计划、常态返回的来源与执行状态、跨模型工具适配及符合性验证。

现有 `auto` 是服务端规则规划；调用搜索使用 OpenAI Web Search provider，不等于让外部 OpenAI 模型或其它模型获得工具能力。两条方向需要分别描述。

外部模型也不会仅从 URL 和 Key 获知使用流程；尚需工具说明、可信交互规则、能力结果回填及有界调用循环。具体拟议行为见 [AI 交互协议设计](agent-interaction-protocol-design.md)。

## 按用户流程核查

| 用户需要的行为 | 设计和实现情况 | 验证与缺口 |
|---|---|---|
| URL + Key 接入 | 原生四种搜索 POST 路由、后台应用 Key、撤销和持久化已实现 | 现有 HTTP/权限测试通过；没有可直接复用的跨模型接入模块 |
| 发现全部可用搜索引擎 | 内部 Registry、后台列表已实现；upstream 有 `GET /search/tools` 和 `/v1/search/tools` | 本次应用 Key 实测均为 403，master key 为 200；原生列表只有名称、provider、可选 description，没有语法、健康或来源信息 |
| AI 选择全部或部分引擎 | 可逐次显式指定一个工具；`auto` 按规则选择 1–3 个主工具 | 没有外部 AI 指定任意合法子集并一次执行融合的契约；fallback 可能追加其它工具 |
| AI 为各引擎生成合理、合法检索式 | 字符串/字符串列表、有限 profile 解析已有 | `PlanEntry` 没有 query；auto 把同一 `request.query` 发给各 provider。列表查询不是 provider→query 的映射 |
| 本项目调用 n 个引擎 | auto 有并行、单调用超时、全局期限、fallback、预估费用预留和基础熔断 | 执行按工具名领取，一工具一次；不能直接表达同一 SearXNG 配置下不同引擎的不同查询 |
| 去重与融合 | canonical URL、保守同文识别、RRF/weighted RRF、同来源 family 抑制重复票已实现 | 相关单元测试通过；没有跨站 DOI/PMID 同文识别，没有语义去重；来源 family 是配置先验 |
| 标准格式 | LiteLLM `SearchResponse/SearchResult` 已统一 title/url/snippet/date/last_updated | 无独立 bensz-search 协议版本；来源贡献、partial_success 多在 debug；全部空结果在 auto 路径表现为 502 |
| 模型拿结果继续工作 | 任意应用可自行发送 HTTP 请求并读取 JSON | 还没有各厂商工具定义、工具结果回填与循环控制的标准接入代码 |
| 全球使用 | 搜索请求有 country，后台和文档主要为中文 | 无完整 locale 契约、英文协议指南或跨模型兼容矩阵；公网部署与全球延迟未验收 |

## 关键源码与调用链

下表项目路径相对于仓库根目录；upstream 路径相对于已安装 `litellm/` 包。

| 层 | 路径与关键符号 | 审计发现 |
|---|---|---|
| 原生 HTTP | upstream `proxy/search_endpoints/endpoints.py:search()` / `list_search_tools()` | 搜索 POST 与工具列表 GET 都存在；列表遍历 Router 配置，不提供能力契约，也没有在该函数中按 key/team 筛选工具 |
| 输入控制 | `src/bensz_search/integration.py:SearchInputMiddleware` | auto 使用严格 `SearchRequest`；显式工具使用原生路径；禁止凭据、地址和内部 metadata 覆写 |
| 应用 Key | `src/bensz_search/admin.py:managed_api_auth()` | 自有 Key 仅允许搜索 POST；GET 能力发现被拒绝；目前 Key 获得全部启用配置的权限 |
| 原生权限 | upstream `proxy/auth/auth_checks.py:can_key_call_search_tool()` / `can_team_call_search_tool()` | auto callback 对真实工具计算权限交集；新发现与执行接口都需复用这一语义 |
| 集成接点 | `src/bensz_search/integration.py:AuthorizationCallback` / `install()` | 自动路径进入 SmartRouter；显式路径进入物理分派；保留 gateway 身份和回调 |
| 能力注册 | `src/bensz_search/models.py:ProviderCapabilities`、`registry.py:Registry`、`config/capabilities.yaml` | 有能力先验、来源 family、成本估算、超时、features；缺少查询方言与逐参数支持声明 |
| 意图与计划 | `intent.py:analyze()`、`planner.py:Planner.plan()`、`models.py:PlanEntry/SearchPlan` | 有六意图与规则评分，无 LLM planner；外部计划不可提交；每工具没有独立 query |
| 执行 | `router.py:SmartRouter.search()` | 按工具名执行、共享期限和预估预算、处理错误；没有按 call_id/engine_id 执行的契约 |
| Provider | upstream `search/main.py:asearch()`、`llms/base_llm/search/transformation.py:BaseSearchConfig` 及各 provider transformation | 已有 HTTP/鉴权/归一化 adapter；参数支持与检索语法需要逐 adapter 核查，不能仅依据供应商名称推断 |
| OpenAI 搜索源 | `src/bensz_search/openai_search.py:provider_call()` / `search()` / `normalize()` | 用 Responses 内置 web_search 取得引用来源，标记生成摘要；这是搜索 provider 扩展，不是全模型接入层 |
| 过滤与去重 | `filters.py:provider_options/filter_results()`、`fusion.py:canonical_url/same_document/fuse()` | 有时间/域名过滤、保守 URL/标题去重和 family-aware 融合；非 http(s) URL 被过滤 |
| 日志与成本 | `telemetry.py:Telemetry.record()`、`health.py:Health` | 有脱敏、有界、进程内运行指标；成本是配置估算，非实际账单、非持久化用户预算 |
| 热更新 | `admin.py:AdminRuntime.refresh()` | 重新构造 Router/Registry；当前在途请求持有旧对象；发现快照与执行一致性尚无公共约定 |

上游兼容设计仍适用；新协议宜作为独立 facade，通过相同的物理 provider 分派和执行组件实现，保留原生 `/search` 行为。

## paperfoot/search-cli 特性核对

本地参考源码位于 `.bensz-api/task-20261002-1415-search/shared/search-cli/`，`Cargo.toml` 标注 `0.9.0`。参考材料没有可验证 Git revision；下面是对该本地快照的比较，不声称覆盖项目最新版，也不据此推断代码复制来源。

参考链接：[paperfoot/search-cli](https://github.com/paperfoot/search-cli)。本次已有本地源码足够用于比较，未额外下载仓库。

| 参考特性 | 本项目现状 | 判断 |
|---|---|---|
| 并行 fan-out、provider adapter、统一结果 | SmartRouter + LiteLLM adapters | 对应能力已具备 |
| `engine.rs:fuse_rrf()` 与 `normalize_url()` | URL 去重 + weighted RRF + family 去相关 | 对应能力已具备，使用本项目实现 |
| `main.rs:agent-info` 自描述、providers 能力表 | 内部 Registry + upstream 简单列表 | 对外 Agent 自描述仍缺失 |
| `extra.also_found_by` 常态携带来源 | 融合 trace 在 debug | 普通响应缺来源链 |
| 版本化 envelope、partial_success/no_results、provider_failures | 默认 object/results，debug attempts | 需要公开、稳定、可机器判断的状态与错误 |
| 被忽略筛选条件的 warnings、provider_results/cancelled | 部分诊断已有 | 需要脱离 debug 的常态诊断契约 |
| 查询缓存、摘要字符上限、提前结束策略 | 无查询缓存；无统一响应上下文上限；等待至全局期限 | 可按实际质量/延迟证据逐项考虑，不能宣称已吸收全部特性 |

因此，“去重和 RRF 思想已对应实现”有源码依据；“已经吸收了 search-cli 全部高级功能”没有依据。

## 本次验证

- Python `3.11.14`；实际 LiteLLM `1.103.2`。
- 运行 core、filters、execution、integration、proxy_http、admin、openai_search 和 60 项 benchmark：**103 passed，7 warnings**。provider/模型通信采用测试替身，不构成商业搜索或跨模型真实调用验证。
- 独立 FastAPI TestClient 探测确认：两条工具列表 GET 对应用 Key 均为 403，对 master key 均为 200；列表字段为 search_provider/search_tool_name；未注册 `/bensz-search/` 路由。
- 原生 `/search` OpenAPI 没有 requestBody schema；项目严格模型拒绝按 provider 提交 `searches`。现有 `/api/docs` 不能完整表达扩展协议。
- 探测只使用任务专属测试数据和随机假密钥，没有读取部署凭据、发起真实外部检索或改变运行服务。
- 探测摘要：`.bensz-api/task-20261003-1118-protocol-audit/shared/protocol-probe.json`。
- 既有真实调用依据为 [0.2 产品验收](production-verification.md) 中的 SearXNG GitHub/PubMed；该证据不能外推为所有搜索源、模型或当前工作区的线上验收。

## 外部模型接口核查

模型兼容是调用方的工具格式与结果回填问题，搜索 provider 兼容是服务端的检索问题。二者应分别维护矩阵。

本次实际读取的官方资料支持 Responses function calling，以及 Codex App Server 的 dynamic tool 路径。后者在当前文档中明确为 **experimental**；不能把它表述为所有 Codex SDK 版本可直接接受 Responses 的 `tools` 参数。按版本做能力检测、适配和集成验收是必要工作。

相关官方页面与其它模型资料记录在 [优化计划](../plans/2026-10-03-global-llm-search-protocol.md)；官方协议资料核查不等于已经实现或验证本项目适配器。

## 交付与贡献记录

实施建议见 [全球主流 LLM 搜索接入协议优化计划](../plans/2026-10-03-global-llm-search-protocol.md)。

任务开始的主账本校验失败：既有事件导致 `project.root_hash changed within ledger`。本次保留 `docs/contribution.bac` 历史，贡献记录在 `docs/contribution-protocol-audit.bac`；主账本修复不属于本次协议规划，不把独立账本通过当作主账本通过。
