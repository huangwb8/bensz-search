# 前端表单对齐验收

## 变更范围

2026-10-03，基于 revision `ecd805370c1527ebd4b8ef460b96555e7b85ff39`，修复后台表单对齐，修订版本为 0.2.1。业务修改集中于 `src/bensz_search/static/styles.css`，沿用原有字体、配色、页面和交互。

- 输入框、下拉框、主要按钮统一为 44px；紧凑按钮为 32px。
- 下拉框使用受控外观和内联箭头，消除浏览器原生控件尺寸差异。
- 同排字段通过 subgrid 共享标签、控件和帮助文案行；保留普通 grid/flex 降级布局。
- 搜索表单通过 gap 管理分组间距，移动端查询框和按钮自然堆叠。
- 统一长文本换行、禁用态、复选框尺寸和弹窗操作区换行。

## 浏览器验证

使用本机 Chrome 与正式项目静态资源，API 响应为明确标识的合成数据。修改前后使用相同视口和数据，分别保存 36 和 57 张截图。

| 检查 | 1440 × 900 | 1024 × 768 | 390 × 844 |
|---|---|---|---|
| 登录及七个后台页面 | 通过 | 通过 | 通过 |
| 配置、测试、用户、密钥弹窗 | 通过 | 通过 | 通过 |
| 输入框和下拉框实际高度 | 44px | 44px | 44px |
| 筛选同行顶边、底边 | 一致 | 一致 | 一致 |
| 查询输入和按钮 | 同高、底边一致 | 同高、底边一致 | 同高、纵向堆叠 |
| 长标签、帮助文案、禁用状态 | 通过 | 通过 | 通过 |
| 搜索加载、结果、空、错误状态 | 通过 | 通过 | 通过 |
| 页面及弹窗横向溢出 | 无 | 无 | 无 |
| 页面脚本错误 | 无 | 无 | 无 |

主代理复核桌面、移动端搜索区和配置弹窗截图，并验证下拉框键盘选择、Tab 顺序、可见焦点、加载时禁用、摘要展开。前端专项子代理额外模拟禁用 subgrid：三个视口仍无横向溢出，控件高度一致；旧浏览器不保证长标签共享行轨。

截图与几何记录保存在 `.bensz-api/task-20261003-1105-frontend-alignment/shared/` 的 `before/`、`after/` 和 `comparison.png`；这些合成数据检查不作为外部搜索服务可用性证据。Safari/WebKit 未直接运行，当前环境未安装对应浏览器运行时。

## 静态与兼容性检查

- `sh scripts/uv.sh run --no-sync pytest tests/test_admin.py tests/test_proxy_http.py -q`：13 passed；两条既有 FastAPI ORJSONResponse 弃用提示。
- `sh scripts/uv.sh run --no-sync pytest tests/test_benchmark.py -q --basetemp .bensz-api/task-20261003-1105-frontend-alignment/shared/pytest-tmp`：60 passed。
- `sh scripts/uv.sh run --no-sync ruff check src/bensz_search tests`：通过。
- `node --check src/bensz_search/static/app.js` 和 `git diff --check`：通过。

## 本机部署

为隔离工作区同时进行的其他后端开发，从上述 revision 建立项目内源码归档，覆盖本次样式及版本文件后构建 `bensz-search:0.2.1`。构建目录位于任务工作区 `shared/deploy-source/`，无嵌套 Git 元数据。本次镜像代表这组已验收修改，不代表当前工作区其他并行任务已经部署。

保留既有 `search-data` 数据卷及私有部署配置，更新本机 8898 服务：容器 healthy、`/ready` 返回 200；实际 CSS SHA256 与修复源码相同，真实登录后的搜索表单在三个视口均为 44px，无横向溢出和脚本错误。真实学术搜索返回 HTTP 200、3 条结果。证据见同目录 `live-report.json` 与 `live-search-*.png`，截图已替换账号标识，不保存 Cookie 或凭据。本次不改变 upstream LiteLLM 1.103.2，不重做商业 provider 验收。

## 贡献记录

BAC 依赖已可用。开始校验时原账本 70 条事件有效，存在三条既有来源类型警告；本任务使用 CLI 追加需求后发现 `root_hash` 冲突：BAC 将 Git remote 纳入项目身份哈希，而本仓库初始化账本后新增了 remote。

备份原容器后，仅纠正本任务未签名尾事件的项目身份字段，保留原 70 条事件完全一致，在修复事件中记录旧哈希与原因；使用 BAC 库继续追加产出、测试和部署证据，沿用 genesis 的稳定项目身份。最终校验无错误，仍保留上述历史警告。修复脚本及原容器备份位于任务工作区 `shared/record_bac.py` 和 `shared/contribution-before-context-repair.bac`，未修改已安装依赖或历史署名。
