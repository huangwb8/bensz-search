# OpenAI Web Search

## 后台配置

在 **搜索引擎 → 添加 Search API** 选择 **OpenAI Web Search**，填写唯一服务名称和 OpenAI API Key。服务地址留空使用 `https://api.openai.com/v1`；兼容网关填写包含 `/v1` 的 API base，网关必须实际支持 Responses API 和内置 `web_search`。不要填写 `/responses` 结尾的完整 endpoint。

默认模型 `gpt-4.1-mini`。可以填写账号有权限且支持 `web_search` 的其他 OpenAI 模型；模型名字不保证账号可访问。搜索上下文为 low/medium/high，默认 medium；输出上限默认 2048 token，可配置 128–8192。建议超时 30000ms，复杂查询可增至 60000ms。保存后点击 **测试**，确认返回真实标题和链接，再启用自动路由。

启停、编辑和删除即时生效。凭据加密保存、不回显，编辑时 API Key 留空保留原值。多个 OpenAI 配置默认归入 `openai_aggregate` 来源族，底层搜索来源不保证与其他服务独立。

## 调用

已有 bensz-search 访问密钥继续使用，供应商密钥仅配置在服务器。显式调用示例：

```json
{
  "query": "Python official documentation",
  "search_tool_name": "openai-main",
  "max_results": 5,
  "search_domain_filter": ["python.org", "-excluded.example"],
  "country": "GB"
}
```

支持 `/search`、`/v1/search` 与路径工具形式；`openai-main` 是后台保存的名称。省略 search_tool_name 或填 auto，可参与自动选择、结果融合和 fallback。自动模式仍按权限、预算估算与健康选择，启用不保证每次被调用。需要更长等待时设置 `constraints.latency_budget_ms`；它仍受 provider 超时约束。

统一 `query` 支持最多十个字符串，逐个执行独立搜索并共享一次总超时，最终去重。域名包含与排除分别发送到 allowed_domains/blocked_domains，并在本地再次过滤；country 映射为 approximate user_location。`max_tokens_per_page` 接受但无网页正文提取能力，不映射为模型输出限制。

## 返回与费用边界

响应仍为 `{"object":"search","results":[...]}`，结果来自已完成 web_search 的结构化引用和完整来源列表。引用排在仅被查阅的来源前，同 URL 去重；无结构化来源则空结果，自动路径触发 fallback。未搜索或未完成的 Responses 判为无效响应。

- `title`、`url` 保留实际来源；来源无标题时以域名展示。
- `snippet_kind: generated_summary` 的 snippet 是引用前的模型回答片段，后台显示“AI 生成摘要”，不是网页原文。
- `snippet_kind: source_only` 只有来源链接，snippet 为空。
- 不虚构发布日期/更新时间，严格 day/week/month/year 时效要求会过滤没有日期的来源。
- max_results 是返回数量上限；来源、引用或过滤后结果可能少于请求数量。
- 每个 query 限制一次内置工具调用、关闭 SDK 重试并设置输出 token 上限；使用 `store: false`。
- OpenAI 收取工具及模型 token 费用。默认每 query 估算 $0.015 是可调整路由先验，不是费用保证或供应商账单。更换模型、上下文大小或输出上限时，应通过管理员 API 同步 `estimated_cost_usd`。默认 auto 总预算 $0.02；更低预算可能排除 OpenAI，多 query 预算按数量相乘。

已有数据库通过后台新增服务；`.env` 仅首次导入，不会重启时自动新增。

## 实现与验证依据

LiteLLM 锁定 1.103.2，SearchProviders 不含 OpenAI，项目独立适配 `litellm.aresponses`，未修改 upstream。官方协议已于 2026-10-03 读取：[OpenAI Web search](https://developers.openai.com/api/docs/guides/tools-web-search)。测试覆盖 LiteLLM 实际 Responses HTTP 请求与模拟响应，以及后台配置、原生四种搜索入口、权限、超时、来源转换和 fallback。全量 107 项测试、Docker 镜像与隔离端到端、浏览器交互通过，详见 [验收记录](openai-web-search-verification.md)。没有进行真实付费 OpenAI 调用，账号权限及外部可用性以后台连接测试为准。

主 BAC 账本初期因仓库 remote 改变而出现根哈希冲突，阶段性证据曾暂存独立账本。本次沿用原账本项目身份，并在新增事件中披露当前上下文哈希，记录需求及交付汇总；仅纠正本任务新输入事件的身份绑定，此前历史保持不变。后续账本整理已将阶段性完整历史归入 [唯一贡献账本](../contribution.bac)，删除独立文件；主账本校验无错误。
