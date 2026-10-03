# 全球搜索协议实施与验证

实施日期：2026-10-03。基于既有全球接入计划直接实现，没有重新编写实施计划或进行根因审计。Git 原始基线 `ecd805370c1527ebd4b8ef460b96555e7b85ff39`；保留任务开始时已存在的文档与贡献账本改动。LiteLLM 固定 1.103.2 发行包，未修改 upstream。

## 阶段交付与边界

| 阶段 | 源码交付 | 验收状态 |
|---|---|---|
| P0 契约 | 正式模型、OpenAPI/Schema、逻辑工具、查询契约、安全错误 | 离线与实际网关通过；两个客户端共享规范 |
| P0 发现与执行 | facade、权限快照、逐 call 验证、共用执行器、状态/来源 | 离线整体验证零调用、旧接口回归、Docker 真实 SearXNG 通过 |
| P0 模型闭环 | Python/TS 五种消息族、同步/流式、有界状态机、备用路径 | 消息族与 Qwen/DeepSeek 渠道 wire fixture 通过；真实模型未配置 |
| P1 MCP | 标准 SDK 入口、两工具、相同服务逻辑、内置客户端示例 | 实际 SDK 宿主 + 真实搜索通过；真实模型宿主闭环待凭据 |
| P1 全球扩展 | 模型/渠道/runtime 矩阵、Codex experimental handler、中英文指南 | 离线格式与能力开关通过；版本组合均明确待真实验收 |
| P1 运营 | 租户限流、并发/期限、体积、质量/延迟 benchmark、部署边界 | 确定性 fixture 与取消/隔离测试通过；不承诺真实生产吞吐量 |
| P2 按证据扩展 | DOI/PMID/arXiv 保守去重、版本分离、别名与类型 | 有针对性的回归通过；无搜索缓存/提前结束的质量依据，按原计划不引入 |

真实模型凭据检查仅记录是否存在，没有输出凭据。当前没有 OpenAI、Anthropic、Gemini、Grok、Qwen 或 DeepSeek 模型测试凭据。因此“每适配族一个真实模型闭环”和“MCP 宿主真实模型闭环”仍未达到，不能宣称全球模型发布验收完成。全部可以本地落地的代码与文档已经交付；[兼容矩阵](compatibility.md)逐项保留验证级别。

## 自动验证

正式测试位于 `tests/test_protocol*.py`、`tests/test_model_adapters.py` 和 `tests/test_engine_metadata.py`，并运行所有原有测试。TypeScript 正式测试位于 `clients/typescript/test/client.mjs`。

覆盖发现无配置/unknown/熔断/权限、Key 撤销、热更新 revision、整体验证、不同引擎查询、显式 fallback、失败费用、零结果、部分成功、超时/取消、租户限流、DOI/PMID/arXiv、日期冲突、生成摘要、体积限制、宿主禁止联网、身份缓存、流参数组装和思考上下文。HTTP/MCP 比较使用确定性 I/O，真实搜索不以实时相同结果作为协议一致性的要求。

```bash
sh scripts/uv.sh run pytest -q
sh scripts/uv.sh run ruff check src tests scripts examples
sh scripts/uv.sh run python scripts/export_protocol.py
npm ci --prefix clients/typescript --cache .bensz-api/npm-cache --ignore-scripts
npm test --prefix clients/typescript
```

最终全量回归 **154 项 Python 测试、15 项 TypeScript 测试通过**；Ruff、diff 空白检查与新增文档的本地链接检查通过。上游 ORJSONResponse 弃用提示不影响通过，未修改 upstream 来消除提示。开发环境同步后恢复原先已有的浏览器工具依赖，保持工作区既有工具可用。

## 真实 Docker 与搜索

使用新镜像在临时端口 18998 / 最终复核端口 18999 启动独立容器，采用全新随机管理员密码、加密 secret 与 master Key，无生产数据卷。没有替换或修改原有生产容器。新应用 Key 登录管理创建，SearXNG allowlist 与实例 `/config` 交集同步后，HTTP 同次执行 PubMed、GitHub 与 Google News 三个不同 query。

| 调用 | 执行状态 | 结果数 | provider 延迟 |
|---|---|---|---|
| PubMed：`colorectal cancer ctDNA` | success | 5 | 4069.40 ms |
| GitHub：`python httpx` | success | 5 | 1109.36 ms |
| Google News：`OpenAI` | empty | 0 | 786.91 ms |

该次 HTTP 200，业务 `success`（已执行调用均健康，有总体结果），融合结果 10 条，总耗时 4076.56 ms，响应 16367 字节。SearXNG 费用配置为 0；这表示未配置单次服务费用估算，不代表运营成本为零。Google News 本次零结果已在 execution 记录，不能将其视为时效召回成功。

原生 `/search` 仍 HTTP 200。实际 MCP SDK 协商协议、发现两个工具、获取相同 revision，再执行一次 PubMed 计划，业务 success、3 条真实结果、1 次实际调用。没有在 MCP 内部再请求一遍 HTTP 搜索。此测试是真实搜索 + SDK 宿主，未使用真实模型，不升级为完整模型闭环。

任务原始报告、构建日志与临时环境保存在 `.bensz-api/task-20261003-1433-global-protocol/shared/`，凭据文件忽略入库，不写 BAC。最终镜像健康检查为 healthy；验收完成后已停止临时容器并删除随机凭据文件。

## 模拟质量与延迟

`scripts/benchmark_protocol.py` 使用六个学术/代码/新闻、多语言标签样本，各重复十次。每源固定 20 ms 延迟，比较并发 1 与并发 3。两模式各 60 个请求，无真实搜索、无真实模型和真实账单；不将模拟标签精度外推到真实搜索质量。

| 指标 | 并发 1 | 并发 3 |
|---|---|---|
| p50 | 46.55 ms | 24.09 ms |
| p95 | 52.73 ms | 26.40 ms |
| 标签精度 | 0.60 | 0.60 |
| 配置独立来源族 | 2 | 2 |
| 平均响应体 | 6899 字节 | 6899 字节 |
| 配置费用估算 / 请求 | 0.007 USD | 0.007 USD |

并发改善延迟且保持同等标签质量、费用和来源覆盖；真实 provider 的相关性、地区/语言表现、费用估算误差与吞吐量仍需正式环境数据。暂不增加提前结束或搜索结果缓存，避免没有质量基线时减少来源或引入隔离风险。

```bash
sh scripts/uv.sh run python scripts/benchmark_protocol.py \
  --output .bensz-api/task-your-time-protocol/shared/benchmark.json
```

## 状态持久化结论

现有 SQLite 保存身份与 provider 配置。能力 revision 绑定配置代次；重启后客户端刷新即可恢复。限流、熔断、统计是进程内状态；不保存对话或后台付费任务。当前单实例边界明确，无多实例吞吐量需求证据；继续使用轻量存储。只有取得跨实例规模、恢复任务或供应商计费需求后，才评估共享 admission/circuit 状态与权限隔离缓存。
