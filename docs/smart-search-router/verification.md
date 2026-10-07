# 第一版验收记录

本记录对应 bensz-search 0.1.0 / LiteLLM 1.103.2，运行日期 2026-10-02。

这是 0.1 历史记录。0.2 阶段曾将本地 8898 升级为带后台的真实搜索产品，GET `/search` 跳转到后台，并移除 fixture 容器；该阶段证据见 [production-verification.md](production-verification.md)，当前镜像与上线证据见 [v1.0.8 发布验收](../deploy/releases/v1.0.8.md)。下文端口、405 和镜像描述当时状态。

## 实际部署

- 镜像：`bensz-search:0.1.0`（Linux arm64）。
- 最终镜像 ID：`sha256:5af39188009c9d40d505e7d5e44f3ef9881fc537df9923f0013053051a0544e3`。
- 模拟 demo：`http://127.0.0.1:8898/search`，search 和 fixtures 两个容器。
- 真实 demo：`http://127.0.0.1:8899/search`，连接本机已有 SearXNG；未修改已有实例。
- 两个 gateway 与 fixture 均通过 Docker healthcheck。端口只绑定 loopback。

## 自动化验证

- `pytest -q`：**79 passed**，包括 60 条路由 benchmark。
- 其余测试验证融合、预算、超时/取消、fallback、熔断、key/team 权限交集、原生 proxy HTTP 及缺失 master key 的启动拒绝。
- `ruff check` 与 `ruff format --check`：通过。
- 两套 Docker Compose 配置检查与最终镜像构建：通过。
- 5 条 Pydantic warning 来自 LiteLLM 中 TypedDict ReadOnly 字段，不是失败测试。

## 模拟 HTTP demo

使用原生 LiteLLM adapter 实际发送 HTTP 到隔离的 fixture 服务；不是绕过 adapter 的静态 SearchResponse。数据明确标注为 DEMO FIXTURE。

| 场景 | HTTP 状态 | 结果数 |
|---|---|---|
| query-only | 200 | 2 |
| explicit native adapter | 200 | 2 |
| path precedence | 200 | 2 |
| academic parallel + dedup | 200 | 3 |
| news freshness | 200 | 3 |
| low-cost single | 200 | 2 |
| profile prompt | 200 | 3 |
| timeout partial | 200 | 2 |
| empty fallback | 200 | 2 |
| auth fallback | 200 | 2 |
| missing authentication | 401 | — |
| credential/base override rejected | 422 | — |
| metrics and feedback | 200 | — |

academic parallel 场景：两源各 2 条结果，URL tracking 去重后输出 3 条。超时场景返回部分结果；空结果与 auth 故障触发 fallback。所有 auto 尝试使用共享预算与截止时间；原生 hidden fallback/retry 被关闭，显式工具继续原生处理。

## 真实检索

通过最终 Docker gateway 调用原生 SearXNG adapter，结果来自实际外部引擎：

### python

返回 5 条实际结果。

- [donnemartin/system-design-primer](https://github.com/donnemartin/system-design-primer)
- [vinta/awesome-python](https://github.com/vinta/awesome-python)
- [practical-tutorials/project-based-learning](https://github.com/practical-tutorials/project-based-learning)

### colorectal cancer ctDNA

返回 20 条实际结果。

- [Clinical impact of prospective circulating tumour DNA testing for minimal residual disease in colorectal cancer: the INTERCEPT programme experience.](https://www.ncbi.nlm.nih.gov/pubmed/42823331)
- [Preoperative Laboratory, Imaging, and Risk Assessment Before Elective Colorectal Cancer Resection: What the Clinician Must Remember.](https://www.ncbi.nlm.nih.gov/pubmed/42795834)
- [Next-Generation Biomarkers and Artificial Intelligence in Colorectal Cancer: From Multi-Omic Data Integration to Clinical Application.](https://www.ncbi.nlm.nih.gov/pubmed/42795017)

显式 SearXNG 请求的 max_results=5 最终返回 20 条，属于 upstream adapter 已有的参数忽略行为，保留兼容性；auto 在统一结果上截断到请求数量。

## 可观察性与已知边界

- debug 返回 plan、实际 attempts、错误分类、来源贡献、overlap、marginal gain 和预估费用。默认响应保持 object/results。
- 日志记录完整计划及融合贡献的数值，不记录 query/profile_prompt/凭据；累计 selected:intent:provider 计数能区分选择与 fallback 尝试。
- metrics/feedback 使用原生身份校验；指标只给 admin/admin viewer，写反馈只给 admin。
- 商业六源协议路径由 fixture 验证，真实网络验收只覆盖 SearXNG。未使用或声明已验证商业 API keys。
- virtual-key 权限逻辑及 key/team 交集有离线测试；没有数据库，所以未做真实虚拟 key 持久化/spend 端到端验收。
- 预算是配置预估，不是供应商账单；状态为进程内存，重启清空。
- BAC 账本已追加贡献/工具/文件/验证记录，校验哈希链无错误；保留 actor 声明警告及本地未锚定状态，没有远程上传。

## 复现

命令和请求示例见 [README](../../README.md)。运行故障 demo 后应重新创建模拟 search 容器清空熔断；交付时已恢复正常状态。

## 浏览器访问问题复核

2026-10-02 在现有 8898 模拟部署复核，LiteLLM 版本仍为 1.103.2：

- `GET /search`：405，响应头为 `Allow: POST`，与浏览器截图一致。
- 带 demo 鉴权和 JSON query 的 `POST /search`：200，返回 `object: search` 和 2 条明确标注 `DEMO FIXTURE` 的模拟结果。
- `GET /health/liveliness`：200，返回 `"I'm alive!"`；Docker search 和 fixtures 均为 healthy。
- `GET /docs`：404，当前部署不能使用该路径作为浏览器入口。

根因为浏览器地址栏使用 GET，而搜索接口仅接受 POST。README 已补充方法限制、鉴权和可直接访问的存活检查；本次未改动接口或部署配置，也未据此宣称真实外部搜索源已通过验证。
