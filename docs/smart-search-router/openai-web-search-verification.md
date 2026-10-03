# OpenAI Web Search 验收记录

2026-10-03，项目 **0.3.0**，upstream 为锁定的 **LiteLLM 1.103.2 发行包**，未修改 upstream 源码。

## 已通过

| 验证 | 证据与结果 |
|---|---|
| 全量回归 | `sh scripts/uv.sh run pytest -q`：107 passed；包括原有 60 条路由 benchmark |
| 代码与脚本检查 | Ruff check、Ruff format、`node --check src/bensz_search/static/app.js`、`git diff --check` 通过 |
| Responses 协议 | 使用真实 LiteLLM Responses HTTP 转换与 httpx MockTransport，检查 `/v1/responses`、服务端凭据、模型、强制 web_search、域名/地区、sources、工具/输出上限和 store=false |
| 错误与重试 | 模拟 HTTP 401、429、500，验证分类为 auth、rate_limit、unavailable，且每次只发一个请求 |
| 来源转换 | 引用优先、完整来源、去重、危险或无效 URL 过滤、生成摘要标记、缺失日期、不把回答中的普通 URL 当来源 |
| 执行边界 | query list、共享超时与取消、缺失 Key 不调用、失败 fallback、allowlist、保留旧 provider 原生调用 |
| 后台及原生入口 | 配置加密保存、不回显 Key、热更新、禁用配置可测试；四种搜索路径、auto、撤销应用 Key 和客户端地址覆盖拒绝 |
| Docker | 生产/fixture Compose 配置解析、`bensz-search:0.3.0` 镜像构建通过 |
| 隔离 Docker 端到端 | 使用临时生产容器、临时配置和模拟 Responses HTTP 服务；验证配置导入、连接测试、原生显式与自动搜索；测试完成移除临时容器 |
| 浏览器 | Playwright 使用本机 Chrome，无头模式检查模型/上下文/输出上限保存及启停后保留；搜索结果含可点击来源和“AI 生成摘要” |

隔离 Docker 验证共执行 **4 次模拟 Responses HTTP 调用，0 次真实 provider 调用**。新增正式测试主要位于 `tests/test_openai_search.py` 与 `tests/test_admin.py`。本次没有更新主生产容器。

## 已实现但未真实验收

真实 OpenAI 账号权限、额度、支持模型和外部服务可用性需运营者配置 Key 后在后台测试。供应商账单不等同于路由估算；指定数量、发布时间或底层来源独立性无法保证。严格时效请求过滤无日期来源，返回可能少于 max_results。

使用方式见 [接入说明](openai-web-search.md)。现有数据卷升级时保留，已有数据库使用后台新增 OpenAI 配置。

## 贡献记录

任务开始检查主 `docs/contribution.bac`，发现根哈希冲突，BAC 拒绝追加。初期证据保存于 [独立账本](../contribution-openai-web-search.bac)。检查确认仓库路径未变而 remote 改变，默认工具重新采集上下文会得到与初始账本不同的项目哈希。新增记录使用原账本身份，同时在 payload 中披露当前上下文哈希；仅纠正本任务刚追加的未锚定输入事件，逐项确认之前全部事件保持不变。主账本已记录本次需求、AI 产出、文件变更和验证汇总。两份账本校验均无错误，历史 actor 类型提示属于记录元数据警告。
