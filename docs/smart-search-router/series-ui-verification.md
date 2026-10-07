# 首页与后台系列视觉验收

## 当前版本补充

2026-10-07 随 1.0.5 发布的后台改进进一步统一了 44px 控件、原生模块、手机卡片、暗色主题、治理页面与抽屉交互；管理员区去重个人入口，详情见[商业后台说明](commercial-admin.md)和[验收记录](commercial-admin-verification.md)。下文保留此前各版本的实际历史截图与验证证据，32px 控件、七页导航等描述属于当时版本。

## 范围与来源

2026-10-05，按用户要求参考本地 bensz-router 优化 bensz-search 的首页入口与后台，并根据后续要求拆分管理员与用户工作区。目标项目基于 revision `f9ca7e4a25be55c2e54ae5c2934bdf62c444fc9c`，参考项目基于 revision `2ca4aeb8406358abeab4fd32c81f731c6c313ea2`。修改原生前端、用户入口别名和既有安全头适用范围，未修改 LiteLLM 1.103.2 的搜索调用链。

参考文件：bensz-router 的 `server/homepage/homepage.css`、`server/frontend/src/views/login.css`、`themePalette.css`、`workspace.css`、`layouts/WorkspaceShell.vue`、`components/WorkspaceNavigation.vue`。只读学习布局与视觉规则，未引入 Vue、外部资源或 UI 依赖。

## 已实现

- 采用 classic 白灰蓝色板：画布 `#f7f7f8`、主要文字 `#1d1d1f`、主操作 `#0066cc`、边框 `#e5e5e8`。
- 首页入口采用 68px 品牌顶栏、中文衬线展示标题、产品介绍、搜索流程示意、右侧登录面板和三项能力说明；手机自然纵向排布。
- 保留原有 `/` 跳转 `/admin` 的行为；首页介绍与登录同页，登录后按角色和入口进入对应工作区。流程示意不代表实时请求或服务状态。
- 后台采用浅色侧栏，管理员和用户上下排列、独立折叠，各区页面直接平铺；选中导航使用蓝色强调，公共面板、表格、按钮、焦点和提示统一样式。
- 品牌使用原创单色搜索变体，在启动、首页和后台共用同一标记。
- 控件维持 44px、紧凑按钮 32px，保留 subgrid 同行对齐、搜索摘要展开、API 和权限数据流。
- 软件版本现位于左上角产品名下方，采用无边框、无背景的灰色小字；管理员、用户工作区和手机顶部品牌区采用相同结构。原右上角版本徽章与“搜索服务控制台”副标题已移除，动态版本读取、缺失提示和无障碍标签保留。开发阶段曾使用 1.1.0／1.1.1，按发布要求统一交付为 1.0.3；历史界面验收与本次发布验收分别记录。

## 管理员与用户工作区

| 工作区 | 入口 | 概览与导航 |
|---|---|---|
| 管理员后台 | `/admin` | 全局运行概览、Search API、用户管理、搜索调试及管理员自己的密钥和账号 |
| 用户工作台 | `/app` | 独立个人概览、搜索、我的密钥、接入指南、账号设置 |

成员访问管理入口后自动进入 `/app`。管理员侧栏同时显示上方“管理员”和下方“用户”两个可折叠列表，分别直接平铺七个和五个页面；成员仅显示用户列表。删除横向切换控件及工作空间、搜索工具、账号等子分类。个人概览根据现有 API 统计启用来源和本人未撤销密钥，并提供搜索与密钥快捷入口，不展示全局请求计数、回退或运行模式，不构造不存在的个人用量。

两区默认展开，组按钮只切换列表可见性，提供独立 `aria-expanded` 与 `aria-controls`。页面与区域切换、前进后退保留折叠状态；重新登录恢复默认展开。真实链接标记区域和页面，只有当前区域的当前页高亮，支持修饰键在新标签打开；手机选择页面后关闭外层菜单，组折叠状态继续保持。

页面 hash 保存当前视图，支持刷新、前进后退与非法页面回退；未知 hash 使用自有属性白名单，成员不能借 hash 进入管理页面。角色判断与当前工作区判断分别维护，管理权限仍由服务端 `administrator` 校验，密钥查询／撤销仍按会话用户过滤。

两区调用原有 `/admin/api`，沿用 `/admin` Cookie 路径、CSRF 和同源检查；用户入口增加相同的 CSP、nosniff 与 no-store 响应头。未创建新的身份体系或数据副本。

## 浏览器验收

### 品牌区版本布局补充验收

2026-10-07 基于本项目 revision `404c569` 与 bensz-router revision `58c6c78` 的本地源码调整版本布局，修订版本为 1.0.5。参考 `WorkspaceShell.vue` 的产品名／版本两行结构及 `workspace.css` 的弱化版本样式，沿用本项目原生前端，没有新增依赖。

本机 Chrome 使用正式静态资源及无凭据合成 API 响应；修改前后在相同接入指南路由、数据和视口截图对比，补充 Search API 页面截图。管理员后台、管理员个人区、普通成员区在 1440 × 900、1024 × 768、390 × 844 与 320 × 740 共 12 组检查通过：版本可见并与产品名左对齐、账号区无重复版本、无页面横向溢出或脚本错误；长账号、页面／区域切换、手机菜单开合、缺失版本提示、键盘焦点与退出后的单行登录品牌均通过。主代理复核桌面、平板和手机截图。

`node --check`、`git diff --check` 与现有后台测试 `tests/test_admin.py`（26 项）通过。截图、脚本和几何报告位于 `.bensz-api/task-20261007-0846-brand-version/shared/`；本次仅验证本地界面，没有部署到远端服务器。

### 既有界面验收

使用本机 Chrome、正式静态资源与无凭据合成 API 响应。修改前后采用相同数据和视口，分别保存 36 和 57 张截图。附加导航检查保存 8 张截图。

| 项目 | 1440 × 900 | 1024 × 768 | 390 × 844 |
|---|---|---|---|
| 首页登录及七个后台页面 | 通过 | 通过 | 通过 |
| 配置、服务测试、用户及密钥弹窗 | 通过 | 通过 | 通过 |
| 同行控件与查询按钮对齐 | 通过 | 通过 | 通过 |
| 长标签、禁用态、搜索加载／结果／空／错误 | 通过 | 通过 | 通过 |
| 页面与弹窗横向溢出 | 无 | 无 | 无 |
| JavaScript 页面错误 | 无 | 无 | 无 |

补充 1440px 管理员、390px 成员和 320px 管理员检查：长账号、无配置服务、登录失败后重试、跳至主内容、Tab 焦点、键盘导航、手机菜单展开与收起、成员管理入口隐藏、退出登录均通过。前端权限检查只验证呈现，服务端权限仍由既有兼容性测试验证。

工作区拆分另保存同条件修改前 57 张、修改后 84 张截图，覆盖三个视口 × 管理员后台／成员工作台／管理员个人工作台九组组合。逐页检查两区导航及内容，验证前进后退、刷新、成员管理页面回退、继承属性 hash、密钥读取失败后版本保留及重试、空状态、管理员切区和登录退出；无页面溢出及脚本错误。拆分阶段通用管理界面 57 张截图再次通过。主代理复核两区桌面概览与用户区手机截图。

导航简化后，管理员和成员 × 三个视口六组检查保存 18 张截图：验证上下位置、区内平铺、独立折叠、Space 键操作、折叠不切页面、跨区及历史回放保持折叠状态、唯一选中页面、刷新和普通成员入口。九组工作区检查的 84 张截图再次通过。320px、长账号、登录错误、Tab 焦点与手机选择页面后收起外层菜单再次通过；无页面溢出和脚本错误。主代理实际复核桌面展开／收起及手机菜单截图。

安全专项定向审查未发现新增越权、会话或注入问题。新增测试检查两入口及尾斜杠变体、登录会话保持和安全头；现有成员跨账号密钥、管理员接口与密码轮换测试继续通过。验证中修正了安全头严格字符串断言，按指令集合判断既有上游和项目中间件重复添加的 no-store／nosniff；未改变权限逻辑。

主代理实际复核首页桌面／手机、概览桌面、手机搜索、表单弹窗及窄屏截图，确认文字层级、对齐、菜单和组件可读性。九组主要文字、辅助文字、导航、按钮、状态色及个人欢迎区文字的对比度均达到普通文字 4.5:1。

证据位于 `.bensz-api/task-20261005-0414-series-ui/shared/`：

- `before/`、`after/`：截图及几何报告。
- `navigation/`：登录错误、长账号、成员与菜单截图及检查报告。
- `comparison.png`：首页和后台概览的前后对比。
- `contrast.json`：主要色对的对比度结果。
- `role-before/`、`role-after/`：工作区拆分前后截图及路由／API 调用记录。
- `workspaces.png`：最终管理员后台与用户工作台并排预览。
- `folding/`：折叠导航截图和验证报告；`navigation.png`：展开与收起状态并排预览。

## 可复现验证

```sh
sh scripts/uv.sh run --no-sync --with 'playwright>=1.55' python .bensz-api/task-20261005-0414-series-ui/shared/check_ui.py before
sh scripts/uv.sh run --no-sync --with 'playwright>=1.55' python .bensz-api/task-20261005-0414-series-ui/shared/check_ui.py after
sh scripts/uv.sh run --no-sync --with 'playwright>=1.55' python .bensz-api/task-20261005-0414-series-ui/shared/check_navigation.py
sh scripts/uv.sh run --no-sync --with 'playwright>=1.55' python .bensz-api/task-20261005-0414-series-ui/shared/check_roles.py role-before
sh scripts/uv.sh run --no-sync --with 'playwright>=1.55' python .bensz-api/task-20261005-0414-series-ui/shared/check_roles.py role-after
sh scripts/uv.sh run --no-sync --with 'playwright>=1.55' python .bensz-api/task-20261005-0414-series-ui/shared/check_folding.py
sh scripts/uv.sh run --no-sync pytest tests/test_admin.py tests/test_proxy_http.py -q --basetemp .bensz-api/task-20261005-0414-series-ui/shared/pytest-tmp
sh scripts/uv.sh run --no-sync ruff check src/bensz_search tests
node --check src/bensz_search/static/app.js
git diff --check
```

初轮 API 兼容性测试 22 passed；新增入口验证后的最终结果 26 passed，3 条既有 FastAPI ORJSONResponse 弃用提示。Ruff、JavaScript 语法和 diff 检查通过。浏览器工具通过项目内 uv 临时依赖环境运行，不加入生产依赖。

## 验证边界与贡献记录

本次交付为源码优化，未更新运行容器或远程站点。浏览器响应均为合成数据，未进行真实 provider 调用；Safari、Firefox 未直接运行。中文衬线字体采用系统字体回退，不同操作系统字形可能略有不同。

BAC 依赖可用，开始与交付阶段检查主账本，保留旧历史及稳定项目身份，追加本任务需求、方案、前端产出和验证结果。账本无校验错误，保留三条既有来源类型警告。前端专项子代理完成前端实现与工作区拆分，安全专项子代理定向只读复核，主代理修改入口、安全头范围、测试并复验及维护正式计划、变更记录与验收说明；未将 AI 判断记为人工确认。
