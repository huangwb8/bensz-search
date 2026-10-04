# SearXNG 默认搜索源修复与验证

## 原因与源码依据

2026-10-04，依据锁定的 **LiteLLM 1.103.2 发行包**，未取得对应 Git commit，不虚构 revision。原 HTTP、鉴权、预算、日志和 provider 调用链见 [架构审计](architecture-audit.md)。本次继续核查安装包中的 `llms/searxng/search/transformation.py:SearXNGSearchConfig.transform_search_request()` 与 `get_complete_url()`：adapter 已能将逗号分隔的 `engines` 透传到 GET `/search`，无需增加或修改 upstream adapter。

限制来自项目部署示例和 `docs/deploy/deploy_local.py:initialize()`，原默认值为 `github,pubmed`。`server.py:effective_config()` 读取环境配置，`admin.py:initialize_admin()` 生成首次导入记录，`admin_store.py:AdminStore.seed_providers()` 只导入一次；后台弹窗显示数据库中的 `engines`。更改环境变量不会覆盖已有后台配置。

`admin.py:AdminRuntime.capability()` 生成按意图选择的引擎子集，`SmartRouter.search()` 和协议 auto 执行将子集交给共用执行器，显式请求继续使用保存的完整列表。验证方式和应用鉴权、预算、超时、日志入口保持既有机制。

## 已实现

- 默认推荐 Google、Bing、DuckDuckGo、Brave、百度、Wikipedia、GitHub、Stack Overflow、PubMed、arXiv 与 Google News，共 11 个引擎。
- 项目默认配置引用的引擎环境变量未设置时，使用推荐列表；明确设置为空时使用实例默认。管理员自定义列表及已有数据库记录保留。
- 普通、深入网页研究和人物意图使用已配置的网页引擎，学术意图使用已配置的学术引擎，代码和新闻意图使用对应子集；缺少对应子集时沿用原列表行为。
- 后台增加“填入常用引擎”按钮，填入后仍需保存；推荐值来自服务端 catalog。新增独立 SearXNG 设置模板，明确启用对应引擎和 JSON 输出。
- 新增列表不会自动获得 `verified_engines` 证据。11 个引擎仍属于同一 SearXNG provider，不能按 11 个独立来源重复投票。

现有实例更新步骤见 [服务器部署说明](../deploy/server-deployment.md#更新已有实例的搜索源)。本次在本地项目完成，未更新线上容器、环境配置或数据库；随 1.0.1 发布。

## 已验证

针对后台、自动执行、实例元信息、部署设置及 v1 协议运行 **51 项测试，全部通过**。覆盖首次导入默认值、显式留空、后台保存完整推荐列表、自定义列表优先、再次 seed 不覆盖、四类查询的实际执行参数和部署模板一致性。provider 执行使用模拟响应，不冒充外部检索。Ruff、JavaScript 语法检查及 `git diff --check` 通过。

另对本机既有 SearXNG 执行只读 `/config` 和 7 次真实单引擎检索，未修改该实例。本机识别全部推荐名称，但 Bing 和百度未启用，因此本次未测试它们。

| 引擎 | 本次真实结果 |
|---|---|
| Stack Overflow | 10 条结果 |
| arXiv | 10 条结果 |
| DuckDuckGo | 0 条，返回 CAPTCHA |
| Brave | 0 条，返回 too many requests |
| Google、Wikipedia、Google News | 各 0 条，未返回引擎故障说明 |

这些结果仅代表本机实例在本次查询时的情况；支持或启用状态不能代替真实可用性。未通过 Docker 构建或隔离实例验证全部推荐源，不宣称完成线上升级或所有来源均可用。

## 验证证据

任务工作区为 `.bensz-api/task-20261004-2006-searxng-sources/`，共享材料包含 `baseline-tests.txt`、`final-tests.txt`、`local-engine-metadata.json` 和 `live-engine-checks.json`。贡献记录追加到唯一主账本 `docs/contribution.bac`，保留既有项目身份和全部历史。
