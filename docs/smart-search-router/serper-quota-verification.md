# Serper 额度错误诊断与修复

## 线上原因

2026-10-06 对线上已保存的 Serper 配置进行了只读检查：接口指向官方 `https://google.serper.dev/search`，请求携带已保存的 Key。使用结果数量 3 和 10 分别进行真实调用，两次均返回 HTTP 400，供应商正文为 `{"message":"Not enough credits"}`，没有搜索结果。因此当前失败原因是该 Key 的可用额度不足，需要在 Serper 控制台充值或更换有额度的 Key。

诊断期间没有修改线上 provider、数据库配置或部署镜像。凭据在服务器进程内解密并用于请求，没有输出或归档。供应商余额状态可能变化，此结论只对应检查时的真实响应。

## 项目错误与修复

依据锁定的 LiteLLM 1.103.2 发行包源码，未取得对应 Git revision。`litellm/llms/serper/search/transformation.py:SerperSearchConfig` 将 `max_results` 映射为 `num`；原生 Router 的搜索路径把供应商 HTTP 400 包装为 `BadRequestError`，保留 `llm_provider=serper` 和 JSON 错误文本，但异常的 `response` 已没有原始正文。

项目 `executor.py:failure_category` 原先将 HTTP 400 一律归为 `bad_request`。这既使后台测试提示含糊，也让 `execute` 提前结束当前分支，无法执行已计划的 fallback。现在仅针对 Serper、HTTP 400 和明确的 JSON `message: Not enough credits` 识别为 `quota`。真正参数错误及其他 provider 的 HTTP 400 保持既有分类。修复共用于后台测试、自动搜索和 v1 搜索执行器；原生显式 `/search` 继续保留 LiteLLM 原始错误行为。

后台测试沿用已有 `category` 字段，通过固定中文文案解释 `quota`：服务额度不足，请检查余额或充值后重试。不向浏览器返回原始异常、请求内容或凭据。自动执行器沿用既有额度故障冷却 300 秒及已授权 fallback；后台连接测试仍可直接重试。

## 验证与交付边界

- 修复前，后台测试将真实形状的 Serper 400 错误误判为 `bad_request`；执行器回归测试证明 fallback 未被调用。
- 修复后，后台、执行器、原生 HTTP 兼容与搜索协议定向测试共 58 项通过。覆盖额度分类、真正参数错误、供应商隔离、脱敏、无重复调用、fallback 和 300 秒冷却。测试使用 mock HTTP 响应，不能替代余额恢复后的真实成功搜索。
- Chrome 使用正式 HTML/CSS/JS 和合成后台 API，验证桌面 1440px 与手机 390px 的测试弹窗：额度说明可见、无横向溢出、无页面脚本错误。
- Ruff 检查、格式检查、JavaScript 语法与 Git diff 空白检查通过。三条 FastAPI 弃用提示为既有提示。

临时日志和截图位于 `.bensz-api/task-20261006-2244-serper-fix/`。源码修订版本为 1.0.4，尚未发布镜像或更新线上实例。错误提示改善需要部署修复版本；Serper 本身恢复搜索还需要可用额度，当前未验证充值后的真实成功调用。
