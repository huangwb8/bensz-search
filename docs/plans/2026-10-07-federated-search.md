# bensz-search 实例递归组合

## 目标与边界

后台新增 `bensz_search` 类型，通过远端实例的 v1 HTTP 协议执行自动搜索，参与本地显式调用、auto、planned、融合与 fallback。远端独立校验配置的访问密钥，不传递本地用户身份或凭据。不做远端引擎展开、注册发现、部署或发布。

## 调用链审计

依据项目当前工作区与 LiteLLM **1.103.2 发行包**，未取得 upstream commit。`server.py:effective_config` 生成原生 search_tools；`integration.py:SearchInputMiddleware` 验证 HTTP 输入，`AuthorizationCallback` 复用 Key/team 权限；`install` 包装 Router.asearch。`openai_search.py:provider_call` 已有独立适配器分流入口，原生供应商仍走 LiteLLM。`admin.py:AdminRuntime` 管理加密配置与运行时刷新，`test_provider` 和显式调试直接调用适配器。

`router.py:SmartRouter.search` 和 `protocol.py:search` 共用 `executor.py:execute`：一个截止时间、并发限制、保守费用预留与 `health.py` 熔断。v1 HTTP/MCP 经 `protocol_http.py:execute_for_user` 校验租户权限与限流；结果通过 `fusion.py:fuse` 和 `protocol_results.py:normalize_results` 去重并输出来源。日志只记录状态，不记录查询与供应商错误正文。

## 实现步骤

- 新增独立联邦上下文与 HTTP 适配器，严格验证传输头、限制路径长度、检测实例重复，关闭重定向并限制响应体。
- 执行器传递剩余时间、划分有限调用额度；远端费用预算限定在该分支的本地估算预留内。费用仍是配置估算，不保证真实账单。
- 接入 provider 目录、配置模板、显式与自动执行、后台提示；保留本地请求选项与查询原文。
- 结果来源扁平化并保留实例路径、叶子工具与原始名次；按底层 source family 抑制重复投票。远端来源声明可信度仍未知。
- 验证多实例 HTTP 调用、A→B→A、层数/并发调用额度、超时与取消、错误/fallback、来源重叠、后台 CRUD 与旧接口。同步文档、协议产物、版本与 BAC。

## 验收与限制

无新凭据时，使用内存 ASGI 多实例与模拟底层搜索；明确区分 HTTP 链路验证与真实供应商调用。统一截止时间在各实例按接收时剩余时间重建，父端取消/超时是最终边界。调用额度保守分配，未用额度不回收，可能少搜；旧版本没有传输约束，无法承诺全链额度，因此跨实例参与方应升级。实例 ID 多进程一致，节点之间不同。
