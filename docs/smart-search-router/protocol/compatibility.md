# 兼容与验收矩阵

记录日期：2026-10-03。服务端 LiteLLM 固定 1.103.2，MCP SDK 固定 2.2.0；模型 API/SDK 由应用选择。`pyproject.toml` 是项目包版本唯一来源。

状态分为拟支持、离线契约通过、真实闭环通过、生产环境通过。离线消息族验收不等于某个厂商/具体模型版本通过。没有实际模型凭据时不填虚构版本、成功率或生产状态。

## 消息族

| 适配族 | 同步闭环 | 流式组装 | 上下文/异常 | 真实模型 |
|---|---|---|---|---|
| OpenAI Responses | 离线契约通过 | completed 响应整体组装 | call_id、严格 schema、reasoning 保留、未完成拒绝 | 待凭据验证 |
| Chat Completions | 离线契约通过 | 多工具 index + 参数片段组装 | tool_call_id、并行、坏 JSON、reasoning_content 保留 | 待凭据验证 |
| Anthropic Messages | 离线契约通过 | 内容块 + input_json_delta | 文本/思考/签名顺序、tool_result 错误 | 待凭据验证 |
| Google Gemini | 离线契约通过 | 完整候选 parts 组装 | thoughtSignature、函数结果、schema 子集 | 待凭据验证 |
| Ollama | 离线契约通过 | NDJSON、完成标记 | message/tool_name、完整参数 | 待运行时验证 |
| Codex App Server | 动态工具 handler 离线契约通过 | 宿主负责原循环 | dynamicTools 显式开关；experimental | 待具体版本验证 |

Python 与 TypeScript 均提供消息族实现；生成 schema 来自同一源。已验证 fixture 行为：发现→提交计划→执行→来源回填→继续回答、缓存隔离、任务累计预算、坏 JSON 不检索、循环上限、超时不重放、禁止联网。

## 具体渠道与运行时

以下条目已经有可使用的通用消息适配代码和接入示例，但具体版本测试仍缺条件。状态均为**拟支持（依赖的消息族离线已通过）**；模型版本、渠道版本、权重/template/parser 与真实搜索组合必须由真实测试填写。

| 渠道 | 选择的消息族 | 必须记录的配置 | 当前真实版本记录 |
|---|---|---|---|
| OpenAI 官方 / 原生 Responses | responses / chat | 模型 ID、API/SDK 版本、推理上下文 | 未配置 |
| Anthropic 官方 | anthropic | Claude 模型、Messages API 版本、SDK | 未配置；Bedrock/Vertex 未适配认证 |
| Gemini API | gemini | 模型版本、API 版本、签名行为 | 未配置；Vertex 认证另验 |
| xAI Grok 官方 | chat / responses | 模型、渠道、工具和并行能力 | 未配置 |
| Qwen 官方 | chat | DashScope 渠道、模型版本、工具与思考模式 | 未配置 |
| DeepSeek 官方 | chat | 模型版本、reasoning_content、工具支持 | 未配置 |
| GLM 官方 | chat | 模型、服务版本、工具支持 | 未配置 |
| Kimi 官方 | chat | 模型、渠道、并行/流式支持 | 未配置 |
| MiniMax 官方 | chat 或经验证的 anthropic | 模型、具体 API 渠道及返回格式 | 未配置 |
| vLLM | chat | 服务版本、权重、chat template、tool parser | 未配置 |
| SGLang | chat | 服务版本、权重、template、parser | 未配置 |
| Ollama | ollama | 服务版本、模型权重、template | 未配置 |
| LM Studio | chat | 服务/模型版本、工具支持 | 未配置 |
| Qwen/DeepSeek/GLM/Llama/Mistral 等自托管权重 | 按宿主实际消息族 | 权重版本、runtime、template、parser 的组合 | 未配置；其它权重同样需逐组合验收 |
| Codex SDK / App Server | dynamic runtime handler 或 host_auto | SDK/runtime 版本、dynamicTools 能力、item/tool/call 格式 | experimental，未配置 |

可靠 JSON 模型可走 structured_output；不可靠模型由宿主 auto 搜索。两条备用路径有明确标记，不能视为原生工具闭环。用户只配置搜索 URL/Key 的前提是应用已有模型账号或本地运行时。

## 搜索与 MCP

- SearXNG：实例 `/config` 元信息与真实关键词搜索分别验收；不宣称完整 PubMed 布尔/字段语法、跨地区表现或全部引擎可用。
- HTTP/MCP：本机隔离 Docker、真实应用 Key 和标准 SDK 的工具发现/调用可验证真实搜索；模型仍未配置，因此不标成 MCP 宿主真实模型闭环。
- Exa、Brave、Tavily、Serper、Perplexity、OpenAI 搜索源：保持现有 adapter 与回归；本次无新真实凭据，不增加供应商成功率承诺。
- Azure、Bedrock、Vertex 等托管渠道的认证不是裸 HTTP 消息适配器负责；须由已有宿主 SDK 完成并单列验证。

## 复现真实模型验收

将已有模型配置传给 `examples/model_search.py`，使用真实搜索服务 URL/应用 Key。记录模型 ID、渠道、API/SDK 版本、日期、搜索源、调用模式、发现/计划/回填次数与结果；凭据保持外部配置，不入版本控制或 BAC。分别跑学术、代码、时效查询、坏计划/部分失败/过期能力/禁止联网场景。MCP 宿主还需记录其名称、版本与自定义认证方式。

真实模型 + mock 搜索仅验模型协议；真实搜索 + mock 模型仅验搜索；两者真实才标真实闭环。正式全球发布仍需要每个宣称支持的适配族至少一个真实模型完整闭环，不能用离线 fixture 替代。
