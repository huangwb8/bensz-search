# 递归实例搜索验收

验证日期：2026-10-07。发布版本 **1.0.4**，LiteLLM **1.103.2 发行包**；未取得 upstream Git commit。实现与边界见[实例组合说明](federated-search.md)。

## 结果

| 项目 | 证据与状态 |
|---|---|
| 项目回归 | `sh scripts/uv.sh run pytest -q`：**208 passed**，4 条已有 FastAPI ORJSONResponse 弃用提示 |
| 静态检查 | `sh scripts/uv.sh run ruff check src tests`、`node --check src/bensz_search/static/app.js`、`git diff --check` 均通过 |
| 协议产物 | `scripts/export_protocol.py` 重新导出；result Schema 与权威 Python 模型逐对象比较一致 |
| 多实例 | ASGI HTTP A→B→C、A→B→A、深度限制、并行子树额度、列表查询与取消通过；底层供应商使用模拟结果 |
| 来源 | 叶子 family/工具/名次与实例路径保留；重复 Brave 来源不放大贡献；来源缺失时标为未知；远端部分成功向上保留 |
| 后台与兼容接口 | 实际后台 CRUD、密钥留空保留、启停、停用测试、显式调试、应用 Key、原生 `/search` 与 `/v1/search`、v1 planned 通过 |
| 浏览器 | Chrome + Playwright，实际项目静态资源与模拟 API，1440×1000 / 390×844；类型切换、地址必填、访问密钥提示、引擎禁用、15 秒默认超时、费用估算与提交通过；无 JS 异常或横向溢出，截图已检查 |
| BAC | 主账本验证无错误，保留历史 3 条 actor/source 类型提示；本任务仅追加贡献与验证证据 |

## 未验证范围

未使用真实远端部署或真实商业供应商；未更新服务器、发布镜像或 GitHub Release。ASGI HTTP 验证不能代替跨机器网络、TLS、反向代理配置或供应商账单实测。第三方来源和预算执行仍依赖其遵循协议，费用控制是配置估算。

## 复现与材料

正式测试为 `tests/test_federated_search.py`、`tests/test_federated_admin.py`，与原有原生搜索、协议、MCP、模型适配及后台测试一起回归。临时材料统一位于 `.bensz-api/task-20261007-0736-federated-search/shared/`：`regression-tests.log`、`check_ui.py`、`ui-verification.json`、`provider-desktop.png`、`provider-mobile.png`。截图与浏览器报告使用合成配置，无真实凭据。
