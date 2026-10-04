# 将搜索接入应用已有 AI

开发者将客户端内置进应用，终端用户只新增服务 URL 和应用 Key。应用保留已有模型账号，搜索 provider 凭据留在服务端。[完整英文教程](integration.en.md)提供同一套协议与示例。

使用 OpenAI Responses API 的 Chat 应用，可先阅读[宿主规划、搜索执行教程](../../responses-host-planned-search.md)：包含工具调用与结果回填的具体实现、可运行示例，以及模型推理、服务端计算与可选供应商 AI 调用的原理图。

## 直接 HTTP

URL 填服务根地址，例如 `https://search.example.com`，每次请求携带 `Authorization: Bearer <应用Key>`。注册两个逻辑工具及本地可信说明，模型先发现能力，再按当前权限与查询规则生成 planned 请求，读取状态和来源后回答。普通应用也可使用 auto。

```python
from bensz_search.client import SearchClient, ToolSession
from bensz_search.model_adapters import ModelAdapter, run_tool_loop

async with SearchClient(search_url, application_key) as search:
    answer = await run_tool_loop(
        应用已有的模型调用函数,
        ModelAdapter("chat"),
        ToolSession(search, budget_usd=0.06, max_searches=3, duration_s=60),
        "查找结直肠癌 ctDNA 的研究证据"
    )
```

回调接收该厂商的 payload，返回 JSON 或解析后的流事件。支持 Responses、Chat、Anthropic、Gemini、Ollama 五种消息族；已有模型循环的应用直接注册 `ToolSession.dispatch`，避免嵌套循环。完整 [Python 示例](../../../examples/model_search.py)使用可选 HttpModel，不强制模型 SDK；[TypeScript 模块与示例](../../../clients/typescript/README.md)使用 fetch。

工具 schema 与规则来自正式模型，通过 `scripts/export_protocol.py` 导出；不手写另一份 provider 列表。能力变更自动生效；过期 revision 要刷新再规划，不能重放执行状态未知的超时请求。

## 不同工具能力

依据实际模型/渠道/template/parser 的配置与测试选择入口，不能只按模型名称判断：

- 原生工具：使用适配器和完整有界循环。
- 可靠 JSON：应用让模型输出严格 tool/arguments action，再用 `dispatch_structured` 执行并回填结果；不传不支持的 tools 字段。
- 无可靠工具/JSON：宿主使用 `session.auto_context(query)` 取得证据后交给模型；返回明确的 host_auto 模式，不宣称具有同等自主规划能力。

按身份创建客户端，按任务创建 session。总费用、搜索次数、修正次数和期限跨轮累计；并行工具也不能绕过预算。用户禁止联网时设置 `allow_network=False`。能力与结果描述都作为不可信数据，不能覆盖宿主指令。

## MCP

MCP URL 填 `https://search.example.com/bensz-search/mcp/`，每个 HTTP 请求带同一 Bearer Key。SDK 协商 MCP 协议版本；搜索契约版本仍为 1.0。`tools/list` 只返回两个逻辑工具，动态引擎必须通过能力工具获取。工具业务失败使用 `isError`，来源、预算、权限、错误与 HTTP 相同。

[可内置的 Python MCP 示例](../../../examples/mcp_search.py)使用锁定的 SDK 2.2.0 及带认证的 httpx2 客户端。已有 MCP 宿主复用自己的模型循环。支持自定义 Bearer 认证的宿主才适用于当前入口；不能据此宣称所有宿主已通过验收。

生产部署需 HTTPS、代理正确转发 Authorization、配置 MCP 可信 Host/Origin、单进程限流与安全凭据存储；参见[部署说明](../../deploy/README.md)。各模型具体版本的验收边界见[兼容矩阵](compatibility.md)。
