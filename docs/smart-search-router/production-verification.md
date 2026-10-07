# 本地产品验收记录

2026-10-02，bensz-search **0.2.0** / LiteLLM **1.103.2**。本次验收按用户最新要求：先本地 Docker 部署，提供完整登录后台并配置不同 Search API，不配置远程服务器或域名。

## 源码后续更新

1.0.5 商业后台扩展了 SQLite 审计、密钥用量与每日汇总，健康和最近事件继续是进程内状态；见[商业后台说明](commercial-admin.md)。本文件以下保留此前生产验收，1.0.5 镜像与上线证据另见 [发布验收](../deploy/releases/v1.0.5.md)，不将历史供应商调用视为新版实测。

## 已交付与实际部署

- 主入口 `http://127.0.0.1:8898/admin`，默认真实生产模式，search 容器 healthy；原主项目 fixture 容器已移除。
- 登录、运行概览、六类 Search API 配置与连接测试、搜索调试、访问密钥、用户管理、个人密码与调用指南均接入实际后端。
- 管理员/成员权限在服务端强制执行；成员不读取 provider 完整配置或全局路由历史。
- SQLite 数据卷持久化身份、配置与应用 key，provider 凭据加密；session/key 使用哈希，密码使用 scrypt。
- 17 个部署包源码/静态文件 SHA256 与项目文件完全一致，避免测试新源码而部署旧页面。
- 初始登录信息在忽略的本地凭据文件中，未写入本记录、日志或贡献账本。

## 自动化与安全验证

- `pytest -q`：**91 passed**，包含 60 条路由 benchmark 及后台测试。
- `ruff check`、`ruff format --check`、`node --check`：通过。
- 后台测试覆盖 session、改密撤销、管理员/成员权限、CSRF/Origin、自有 key 隔离/撤销、原生 API key 路由限制、provider CRUD/热更新、换类型清除旧凭据、全搜索路径 body/参数限制、加密持久化、生产拒绝 fixture/环境引用。
- 安全专项独立验证覆盖范围内无未修复 P0/P1；未做公网 TLS 或全依赖漏洞扫描。
- 两条 FastAPI deprecation warning 来自原生 ORJSONResponse，不影响结果；未为消除 warning 修改 upstream。

## 真实外部检索

通过已存在的 SearXNG，原生 LiteLLM adapter 实际请求外部引擎；不是 fixture 或静态 SearchResponse。

| 检查 | 实际结果 |
|---|---|
| 后台登录 | 200 |
| SearXNG 连接测试 Python | 成功，原始结果 50 条，约 1.5 秒 |
| auto Python | 返回 5 条真实结果，包括 GitHub 仓库 |
| auto colorectal cancer ctDNA | 返回实际 PubMed 文献，按请求截断 |
| 新建应用 key → 原生 POST `/search` | 200，真实结果 |
| 撤销该 key → 再次搜索 | 401 |
| GET `/search` | 引导到后台，最终页面 200 |
| `/ready` | 200，说明有启用配置 |

学术验证链接示例：

- [Clinical impact of prospective circulating tumour DNA testing for minimal residual disease in colorectal cancer: the INTERCEPT programme experience.](https://www.ncbi.nlm.nih.gov/pubmed/42823331)
- [Preoperative Laboratory, Imaging, and Risk Assessment Before Elective Colorectal Cancer Resection: What the Clinician Must Remember.](https://www.ncbi.nlm.nih.gov/pubmed/42795834)

首次混合引擎验收发现学术请求的前排混入 GitHub，随后增加基于已配置引擎的意图筛选；修复后重复原生 key 与后台浏览器验证，学术结果全部为 PubMed 链接。

普通网页默认引擎曾出现 CAPTCHA、429 或 timeout，HTTP 200 仍为零结果。当前本机只宣称 GitHub/PubMed 实测通过。Exa/Brave/Tavily/Serper/Perplexity 的管理入口、配置热更新和既有 adapter 协议测试已具备；未提供真实商业凭据，未声明商业服务线上实测通过。

## 浏览器实际操作

Chrome 直接连接最终 8898 后台，使用真实登录与真实搜索：

| 尺寸 | 登录/概览 | 学术真实结果 | 整页横向溢出 | 脚本/控制台错误 |
|---|---|---|---|---|
| 1440 × 900 | 通过 | 5 条 PubMed | 无 | 无 |
| 1024 × 768 | 通过 | 5 条 PubMed | 无 | 无 |
| 390 × 844 | 通过 | 5 条 PubMed | 无 | 无 |

桌面实际完成 provider 新增、编辑、停用、删除并在后端生效。另有明确使用合成接口的前端专项测试覆盖所有页面、空/错误状态、键盘/菜单、恶意文本转义、安全外链、一次性 key 清理、摘要展开/收起；合成测试不作为真实检索证据。

真实浏览器发现的 Chrome pattern 兼容问题已修复。长摘要默认四行，可展开全文；前端专项验证内容完整与 aria 状态。

## 重启与身份验收

在实际 Docker 容器中保存一条停用的真实 SearXNG 配置和新应用 key，重启 search 容器后：

- 既有后台 session 仍可使用。
- provider 配置及 19000ms 超时保留。
- 重启前生成的 key 可继续执行真实 PubMed 搜索，随后撤销。
- 实际创建成员、登录、调用管理接口得到 403；测试结束删除临时账号与 provider。
- 注销后 session 请求返回 401。

数据卷重建保留也随多次镜像重建验证；未执行灾难恢复备份还原。部署/备份操作说明见 [部署说明](../deploy/README.md)。

## 证据与边界

机器摘要与截图保存在本项目任务工作区 `.bensz-api/task-20261002-1530-production-admin/shared/`，包括 `live-http.json`、`persistence-live.json`、`browser-live.json` 和 `deployed-source.json`。真实凭据与 Cookie 未进入这些摘要。

当前为单机单实例产品。配置与身份持久化，metrics/熔断为进程内状态；公网 HTTPS、多实例一致性、原生 LiteLLM DB virtual-key/spend 和商业账单未验收。该记录不将未验证能力表述为已上线。
