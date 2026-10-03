# Search protocol v1

[English integration guide](integration.en.md) · [中文接入指南](integration.zh-CN.md) · [Compatibility matrix](compatibility.md) · [Verification](verification.md)

协议版本 `1.0`，交互版本 `1.0`，包版本从根 `pyproject.toml` 读取；MCP 协议由 SDK 独立协商。公开机器契约由 `scripts/export_protocol.py` 从正式模型生成：

- [OpenAPI](v1/openapi.json)：直接 HTTP 接入。
- [搜索请求 JSON Schema](v1/search.schema.json)、[能力清单 Schema](v1/capabilities.schema.json)、[结果 Schema](v1/result.schema.json)。
- [逻辑工具及可信交互规则](v1/tools.json)：客户端和 MCP 共用；厂商格式转换只在宿主进行。

| 入口 | 鉴权 | 用途 |
|---|---|---|
| `GET /bensz-search/v1/capabilities` | Bearer 应用 Key / 原生 Key | 当前权限下的工具、引擎、查询规则、健康与限制 |
| `POST /bensz-search/v1/search` | 同上 | `auto` 规则计划或 `planned` 外部计划；`dry_run` 零 provider 调用 |
| `/bensz-search/mcp/` | 每个 HTTP 请求携带同一 Bearer Key | SDK Streamable HTTP、无状态 JSON 响应；两个逻辑工具 |
| `GET /bensz-search/v1/schema` | 公开 | 无实例配置或凭据的静态请求 Schema |
| 原生四种 POST 搜索路径 | 原有鉴权 | 继续返回 LiteLLM 格式；不强制协议 envelope |

## 能力与查询规则

`tool_id` 是配置实例，`provider_type` 是 adapter，`engine_id` 是经过验证的可选择底层引擎。未公开底层引擎的聚合源只提供工具级调用。禁用或未授权工具不出现在发现结果中，执行再次按 Key/team 交集检查。应用 Key 不能访问后台、LiteLLM 管理接口；`/search/tools` 也进行相同权限过滤。

能力分数是配置先验。未调用的 provider 健康为 `unknown`，熔断显示冷却状态；发现不自动发起付费探测。能力快照缓存 30 秒，revision 绑定权限子集、能力与配置代次；启停或凭据轮换后的旧计划返回 HTTP 409 `stale_capabilities`。缓存过期应刷新；期限过期但配置未变化的 revision 仍可执行，执行时的当前鉴权始终生效。

默认只支持关键词和自然语言。布尔表达式、引号和领域字段语法标为 unknown，不能把 PubMed 引擎名等同于完整 PubMed 语法已验证。SearXNG 底层选择需要管理员 allowlist、实例 `/config` 与 adapter `engines` 映射三者的依据。管理员可调用 `POST /admin/api/providers/{name}/engines/sync`，同步已配置地址，不接受调用方提供新 URL；失败或配置同时变化不覆盖保存记录。也可通过管理员配置 `verified_engines` 与证据，维护者负责保证证据真实。凭据与内部地址不会进入公开证据说明。

| 选项 | 新协议处理 |
|---|---|
| `query_language` | 描述输入语言，查询原样发送；返回 advisory warning |
| `result_language` | SearXNG `language` / Serper `hl`；其它 adapter 拒绝不支持项 |
| `country` | Exa / Perplexity / Serper 的已核对映射；其它 adapter 拒绝，不以语言替代地区 |
| `safe_search` | SearXNG `safesearch` / Serper `safe`；其它 adapter 拒绝 |
| 域名 / 时间 | 服务端保守过滤并返回 warning；缺日期的时效候选剔除；原生时间提示可辅助召回 |
| `response_language` | 目前说明固定英文；请求其它说明语言返回 warning，不自动翻译 query |

映射依据是锁定的 LiteLLM 1.103.2 `llms/{provider}/search/transformation.py`。真实供应商语义验证状态见兼容矩阵。

## 计划、预算与失败

```json
{
  "mode": "planned",
  "registry_revision": "revision-from-capabilities",
  "calls": [
    {"call_id": "papers", "tool_id": "searxng", "engine_id": "pubmed", "query": "colorectal cancer ctDNA", "max_results": 5},
    {"call_id": "code", "tool_id": "searxng", "engine_id": "github", "query": "ctDNA pipeline", "max_results": 5}
  ],
  "constraints": {"latency_budget_ms": 15000, "cost_budget_usd": 0.02},
  "fusion": "weighted_rrf",
  "max_results": 10
}
```

只有发现已宣告这些 ID 时示例才合法。每项 query 必须是单个非空字符串，不接受列表或任意 provider kwargs。未知字段、重复 call_id、非法参数、未知引擎、无权限与超预算主调用在整体验证阶段拒绝，零 provider 调用；返回稳定错误码和字段位置。最大全部物理调用 10 项，包括 fallback；并发默认 3，不能把同工具多 query 当作一次免费批量请求。

每项可声明 `fallbacks`，每个替代调用有自己的 `call_id/tool_id/query/options`。planned 默认只执行明确列出的项；`fallback_on_empty=false`，正常空结果不触发替代，也不惩罚 provider 健康。auto 继续复用规则规划与受限替代。费用在开始物理调用前预留，失败和替代都计入；剩余预算不足的替代以 `budget_exceeded` 跳过。dry run 返回主调用估算与全声明调用的最高估算，后者可能超过预算，此时替代会受预算限制。估算不能保证供应商账单，模型型搜索费用尤其需要运营者更新配置。

单次调用受共用期限、并发与熔断控制；取消会取消子任务且不继续发起替代。HTTP/MCP 套接字断开也监测取消。无状态 MCP 不提供跨请求持久任务或恢复队列；宿主应取消底层请求，跨请求的取消通知不承担计费任务恢复语义。

| 业务 status | 含义 |
|---|---|
| `validated` | dry run，不调用 provider |
| `success` | 已尝试调用均健康并有结果 |
| `partial_success` | 有结果，同时存在失败、超时或受限跳过 |
| `no_results` | 健康调用全部无结果 |
| `failed` | 无可用结果，且存在执行失败或请求错误 |

新响应默认包含 request_id、revision、逐项 execution、来源与原排名、内容类型、别名、warning、费用依据和约束说明；不依赖 debug。provider 错误只返回脱敏分类，不回传原始异常。无效请求使用 HTTP 4xx；已执行搜索的失败使用 HTTP 200 + `status=failed`，MCP 使用 `isError=true` 封装相同业务 envelope。

## 去重与内容边界

保留跟踪参数清理、保守同文档识别与 family-aware weighted RRF。同源族多次查询只取最大排名贡献，不能增加独立来源票。新协议在正规元数据或权威 URL 提供 DOI/PMID/arXiv 标识时补强去重；arXiv 明确版本保持分开，不凭标题跨站合并。URL 别名、来源日期与摘要类型保留，日期冲突发出 warning。

snippet 默认最多 2000 字符，总结果体默认最多 128000 字节；截断有 `truncated` 标记。生成摘要保持 `generated_summary`，Exa 正文片段为 `page_excerpt`，普通摘要为 `search_summary`，空片段为 `link_only`；有可信 adapter 标记时保留其页面摘录类型。融合分数只表示排序贡献，不代表事实可信度。全部外部内容明确标为 `untrusted_external_content`。

P2 已交付保守标识去重。未引入搜索结果缓存或提前结束：当前没有证明这些策略保持租户隔离和来源覆盖的真实基线；能力缓存已经按客户端身份隔离，不跨租户复用。此选择符合原计划的按证据扩展门槛。
