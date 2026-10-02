# bensz-search 第一版实施计划

## 通俗解释：究竟发生了什么

当前搜索调用需要 Agent 自己决定去哪搜，研究任务想查多家还要自行去重。像查一本书时同时询问图书馆和书店，Agent 是读者，provider 是不同信息来源，Router 负责选择和汇总。完成后，简单问题仍可指定一家；复杂问题用 auto 就能获得带来源和选择理由的统一结果。

## 专业判断与目标

LiteLLM 已有统一 adapter、工具权限及 fallback；缺少异构搜索任务规划和融合。第一版在独立包中补齐这些能力，保留原生显式 API，并验证真实 proxy 鉴权与 Docker 运行。使用固定 LiteLLM 1.103.2；不修改 upstream 源码。

范围：六类意图、六个能力档案、单源/多源、三种融合、全局期限/预算、fallback/熔断、debug/指标/feedback、60 条路由 benchmark。暂不增加 UI、数据库、ML/RL 或通用 workflow DSL。

## 改进方向与小提交顺序

以下是可审阅的提交边界；实际创建 Git commit 需用户另行要求，开发不自动提交。

| 边界 | 要解决的问题及交付 | 验收 |
|---|---|---|
| 1 | 审计与架构基线，解释为何采用 extension | 三份文档准确标注 upstream 函数 |
| 2 | 定义请求、任务、计划、能力和配置 | 无效约束被拒绝；缺凭据工具不参与 |
| 3 | 实现确定性分类和预算/多源规划 | 单源精确查询、跨 family 高召回 |
| 4 | 实现 URL 去重与三种 RRF | 独立源投票有效；Google family 不重复投票 |
| 5 | 实现执行、全局期限、fallback、熔断 | auth 不重试，部分成功可用，成本不过度 fan-out |
| 6 | 接入原生 proxy lifespan 和权限 callback | 显式行为保持；auto/fallback 不越权 |
| 7 | 增加脱敏日志、指标和 feedback | debug 可解释；默认结果保留原格式 |
| 8 | 加入 60 条 benchmark、故障与兼容性测试 | 允许 reasonable provider set，不作唯一选项判断 |
| 9 | 打包 Docker、README、可重复 demo | 本地镜像上线，HTTP demo 通过，真实检索独立验证 |

## 如何确认完成

先写高风险算法/执行/权限的失败测试，再实现相应模块。benchmark 覆盖 general/news/academic/coding/people/deep，每条保存 expected intent、preferred/acceptable/invalid provider choices。

Docker demo 覆盖：query-only、explicit、auto single、auto parallel、profile_prompt、URL 去重、debug、auth/timeout/empty fallback、未授权请求、指标/反馈。模拟数据明确标注；真实 SearXNG 验证另记结果，不把 fixture 当成真实检索。商业 API 如无 key，只验证协议路径和配置，不宣称已实测供应商。

## 风险与恢复

- LiteLLM 暂无正式 SearchPlan plugin；lifespan 和实例方法接入必须有版本测试，升级不可只修改版本号。
- 所有 auto 子请求的 retries/fallbacks 由 planner 控制；显式请求继续沿用原生规则。
- 能力与价格是配置先验；预算以估计执行，不保证供应商最终收费。
- 无数据库模式不支持持久化 virtual key/spend；持久化能力须使用标准 LiteLLM DB/Redis 部署。
- 回滚可改回原生 `litellm.proxy.proxy_server:app` 并删除 extension 配置；显式 search_tools 配置继续适用。
