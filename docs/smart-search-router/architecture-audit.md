# LiteLLM 搜索调用链审计

## 审计依据

2026-10-02，依据项目 `.bensz-api/.venv`（原根目录 `.venv`，现已迁移）中已安装且由 `uv.lock` 锁定的 **LiteLLM 1.103.2 发行包**。upstream revision 使用发行版本标识 `1.103.2`，未取得对应 Git commit，不虚构提交号。锁文件包含发行包来源及 SHA256 校验值。

`.bensz-api/task-20261002-1415-search/shared/litellm` 的参考源码标注 1.105.0，且未提供可解析 HEAD，不能用作当前部署 revision 的依据。源码路径均相对于已安装 `litellm/` 包。原审计文件误含 pyproject 配置，本次按实际源码恢复审计内容。

## HTTP 到 provider

| 层 | 源码路径与关键符号 | 实际职责 |
|---|---|---|
| HTTP | `proxy/search_endpoints/endpoints.py:search()` | 注册四个 POST `/search`、`/v1/search` 和路径工具形式；路径名优先；使用原生鉴权依赖 |
| 身份 | `proxy/auth/user_api_key_auth.py:user_api_key_auth()` | master key、原生 DB key 等身份入口；支持自定义 auth |
| 工具权限 | `proxy/auth/auth_checks.py:can_key_call_search_tool()` / `can_team_call_search_tool()` | 检查 key/team 可访问的搜索工具 |
| 公共处理 | `proxy/common_request_processing.py:ProxyBaseLLMRequestProcessing` | `base_process_llm_request()`，调用前 hooks、原生处理与日志、Router 调度 |
| Router | `router.py:Router._asearch_with_fallbacks()` | 绑定 Search API 到 Router 的 retry/fallback 基础设施 |
| 工具选择 | `router_utils/search_api_router.py:SearchAPIRouter` | `get_matching_search_tools()`、`async_search_with_fallbacks()`、`async_search_with_fallbacks_helper()`；按同名工具配置选择并解析 provider 参数 |
| 搜索入口 | `search/main.py:asearch()` / `search()` | 统一参数和 async 执行，选择原生搜索 adapter |
| Provider | `llms/<provider>/search/transformation.py` | HTTP 方法、鉴权、请求变换、响应归一化 |
| 结果模型 | `llms/base_llm/search/transformation.py:SearchResponse` / `SearchResult` | `object: search`、统一 title/url/snippet/date 等字段 |

原生 `query` 为字符串或列表，统一参数还包括 max_results、search_domain_filter、max_tokens_per_page、country。provider-specific 参数由原生 adapter 处理；不同 adapter 的支持程度并不完全相同。

## Provider abstraction 与支持范围

`llms/base_llm/search/transformation.py:BaseSearchConfig` 定义搜索配置接口；HTTP 方法、完整 URL、环境/headers、请求与响应变换由各 provider 子类实现。项目复用这些 adapter，不另写商业服务协议。

`types/utils.py:SearchProviders` 在 1.103.2 中列出 perplexity、tavily、parallel_ai、exa_ai、brave、google_pse、dataforseo、firecrawl、fastcrw、searxng、linkup、duckduckgo、searchapi、serper、you_com、apiserpent、tinyfish、agentcore、nimble、bing_grounding。枚举不含 OpenAI。后台提供六类原生配置：Exa、Brave、Tavily、Serper、Perplexity、SearXNG，并在 0.3 增加项目适配的 OpenAI Web Search。

SearXNG 的 `SearXNGSearchConfig` 用 GET JSON 协议，将原始结果转换为 SearchResult。统一 max_results 被其当前 adapter 忽略；auto 路径在归一化后截断，原生显式 HTTP 请求保留 upstream 行为。

## 已有路由与新增能力

LiteLLM Router 已经支持同工具名匹配、retry/fallback 和原生回调。它没有实现本项目的六意图异构任务规划、跨工具 weighted RRF、同 source_family 抑制重复票和按任务选择 SearXNG 引擎。重复实现原生同名路由没有必要。

本项目接点为 `integration.py:SearchInputMiddleware`、`AuthorizationCallback` 和 `install()`。入口补默认 auto；callback 交集 key/team 的真实工具权限；初始化后的 `Router.asearch` 对 auto 进入 SmartRouter，显式调用经过 `openai_search.py:provider_call()` 分派，既有 provider 继续原生 Router。auto 物理请求禁用内部隐藏 fallback/retry，统一执行预算和截止时间。

## OpenAI Web Search 补充审计

2026-10-03，继续依据 **LiteLLM 1.103.2 发行包**。`search/main.py:search()` 先执行 `SearchProviders(search_provider)`，因此不能直接配置 OpenAI 后依赖原生 Search adapter。`responses/main.py:aresponses()`、`llms/openai/responses/transformation.py:OpenAIResponsesAPIConfig` 和 `llms/custom_httpx/llm_http_handler.py:async_response_api_handler()` 已支持 Responses、tools、tool_choice、include、max_tool_calls 及输出限制。

项目在初始化后的 Router 实例增加分派，不改枚举、全局 provider 注册和 upstream 文件。OpenAI 配置使用 `search_provider: openai` 与 `search_model`，避免与原生 Router 用作工具别名的 `model` 冲突。凭据和网络地址只读服务端配置；物理请求经 `litellm.aresponses` 保留 Responses callbacks，外围 Search endpoint 的鉴权、公共 hooks 和日志仍保留。自动请求仍由 SmartRouter 预留估算成本并控制 fallback；显式 OpenAI 请求受配置超时限制，不提供原生 Search Router 的同名跨 provider retry/fallback。

协议依据：[官方 Web search 文档](https://developers.openai.com/api/docs/guides/tools-web-search)，2026-10-03 已实际读取。使用 `web_search`、强制 `tool_choice: required`、`include: [web_search_call.action.sources]`；只转换结构化 url_citation 和 sources。模型生成摘要带 `snippet_kind: generated_summary`，只有链接的来源带 `source_only`，不补造日期或网页正文。最多一次内置工具调用、配置输出上限、不存储 Responses 对话。搜索结果数量是上限，模型和工具实际账单不可由能力表估算精确约束。

## bensz-search 实例搜索源补充审计

2026-10-07，依据同一 **LiteLLM 1.103.2 发行包**与当前项目源码。`bensz_search` 同样不属于 upstream SearchProviders 枚举；沿用 `openai_search.py:provider_call` 的实例级分派入口，调用独立 `federated_search.py:search`，不修改 upstream。远端先经 v1 capabilities 验证联邦支持与权限，再执行 v1 auto 搜索；使用服务端独立配置的访问密钥，不传递本地用户和 metadata。

`integration.py:SearchInputMiddleware` 包装 `federation.py:FederationMiddleware`，为原生、v1、MCP 和后台调试绑定调用链上下文；`executor.py:execute` 共用截止时间、估算预留、熔断与互不重叠的子树调用额度。`fusion.py:fuse` 与 `protocol_results.py:normalize_results` 保留远端叶子来源并抑制重复 source family 贡献。原生 `/search` 结果字段是兼容的增量；v1 Source 增加可选路径与叶子工具字段，静态协议文件同步生成。真实第三方费用、来源独立性与协议遵守不属于可证明边界，见[实例组合说明](federated-search.md)。

## 鉴权、预算和日志边界

原生 HTTP 的公共处理保留回调与日志路径，物理 provider 调用复用 LiteLLM 的运行机制。项目成本上限是每逻辑请求的配置估算，不能等同于供应商账单，也不是跨用户全局预算。

重要接点：`proxy/auth/user_api_key_auth.py` 的 `user_custom_auth` 分支直接返回 UserAPIKeyAuth，默认不会自动执行后续原生角色检查。因此 0.2 的 `admin.py:managed_api_auth()` 自行限制应用 key 到搜索 POST 路由，明确返回当前启用工具权限，拒绝原生 key/config 管理路由。自有身份由 SQLite 持久化，不宣称复用了尚未验收的 LiteLLM DB virtual-key/spend 持久化。

`telemetry.py:Telemetry` 是脱敏进程内指标与有界历史，provider 凭据/查询不进入结构化事件；后台成员不读取全局历史。配置与用户保存到 SQLite，运行指标与熔断仍在内存。

## 0.2 产品扩展与同步方式

`server.py` 安装原生 lifespan 后启动后台身份/配置存储，`AdminRuntime.refresh()` 为修改后的配置建立新 Router/Registry，更新 callback 和 SmartRouter，保留原生 adapters。静态前端与后台 session 使用单独路径，原生 POST 搜索保持兼容；拒绝客户端的凭据/网络地址覆写是当前生产安全边界。

不修改 upstream 源文件。升级时以新发行包重新审计上述 HTTP、auth、Router、callback、lifespan 和模型接点，再运行后台权限/原生 API 测试与真实检索。发行包版本与临时参考源码必须分开记录。
