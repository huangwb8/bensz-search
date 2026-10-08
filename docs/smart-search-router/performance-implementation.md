# 性能优化实现与验证

本次按 [2026-10-07 计划](../plans/2026-10-07-performance-optimization.md)直接实现 P0–P2，实现阶段保留软件版本 `1.0.8`，随后按人类指定统一发布为 `1.0.9`；上线证据见 [v1.0.9 发布验收](../deploy/releases/v1.0.9.md)。现有原生 `/search`、鉴权、CSRF、用量归属、deadline、fallback、用户隔离和管理功能继续由原有回归验证约束。

## 已实现的行为

### 后端与持久化

异步请求的 store 调用与搜索记账通过 `BlockingWork` 执行。管理操作最多 8 个线程、32 个已提交工作；Telemetry 最多 4 个线程、16 个已提交工作。上下文随调用进入线程，密钥与用户归属保持不变。取消等待不会停止 SQLite，已提交工作会等待完成或明确失败后释放容量；退出时先排空再关闭数据库。

Telemetry 仅在内存计数时持锁，数据库持久化在锁外执行。写入失败保留进程统计，增加 `persistence_errors` 并记录错误日志，不能把进程计数当作已持久化记录。取消中的 auto/planned 搜索也形成一次执行记录。

SQLite 使用一个受锁保护的写连接和四个有界只读连接。读连接启用 foreign keys、5 秒 busy timeout 和 query_only，借出期间使用独立读事务，发挥 WAL 读写并行能力。嵌套事务中的读取继续使用写连接。所有写事务先取得 SQLite writer lock，跨进程合并与比较仍受事务保护。登录及改密的 scrypt 在写锁外执行，随后重新检查密码与启用状态，阻止过期校验通过；365 天统计清理最多每小时触发一次。

可用服务来自随路由代次发布的配置快照。配置保存、删除、启停和导入后的刷新同步发布新快照，鉴权和 `/ready` 不再重复查询 provider 表。用户、密钥和会话有效性仍直接检查数据库。管理概览提供有界的应用锁等待、SQLite writer 等待、事务耗时、HTTP 总耗时和事件循环间隔观测。

### 页面读取

浏览器 `ResourceCache` 只保存当前页面进程内的数据，最多 64 个资源。缓存键包含身份代次、用户、角色、工作区和完整请求参数。服务列表新鲜期 30 秒，概览与个人用量 5 秒；相同资源共享在途请求。离开页面取消无人订阅的读取，晚到响应不能更新新页面；退出、身份变化和角色变化清除身份缓存。

页面结构立即显示，新鲜缓存同步应用，过期数据保留并刷新。搜索表单使用精简的 `/admin/api/workspace`，不等待概览统计；选项尚未加载时仍可输入，依赖配置的选择与提交暂不可用。个人概览的配置、密钥摘要与用量各自加载和处理错误。一块 5 秒超时会显示重试入口，其余分区继续使用。刷新搜索选项与会话列表不替换输入表单，保存草稿、未保存提醒、一次性密钥和重新登录行为。

公开站点信息在后台读取，模块启动和表单显示不等待该接口；返回后应用配置的名称与默认语言，更新导航和标题并保留输入。

写入成功后按资源失效缓存；导航取消不会取消搜索提交或配置操作。读取默认超时 5 秒，写入、测试和搜索保留较长上限，取消读取不弹出网络错误。

### 数据与静态资源

新界面通过 `compact=true` 请求概览，最近记录为 20 条摘要；不传该参数的旧管理客户端保留完整历史默认值。完整详情通过 `/admin/api/requests/{request_id}` 获取，仅管理员可用。`/smart-search/metrics` 和搜索 debug 仍保留原结构；进程内完整历史仍最多 200 条。

JS/CSS 使用整个模块图的内容哈希路径 `/admin/assets/{fingerprint}/{filename}`，包括相对 import 和 CSS。进程持有一致资源快照，生产启动时将完整公共 bundle 原子发布到数据卷 `assets/`；保留已发布 bundle，使部署后旧 HTML 的模块路径仍可读取。公共资源提供一年 immutable 缓存和 ETag，HTML、身份与私有 API 保持 no-store。GZip 对可压缩响应生效，缓存路径与压缩响应分别验证。

公共 bundle 保留供跨镜像升级使用，不能在发布过程中删除旧 bundle。长期维护时，可由运维按保留期限清理已停止使用的版本；此实现不自动删除旧资源。

### 容量与长列表

`BENSZ_SEARCH_MAX_CONCURRENT_SEARCHES` 默认 `16`，允许 `1–64`，单 worker 下作用于原生搜索、后台搜索、HTTP 协议与 MCP 工具执行。采用立即拒绝，超出容量返回可重试的 429；HTTP 返回 `Retry-After: 1`。管理读取和健康请求不占搜索名额。Uvicorn 的外围并发限制仍保留，不能替代应用容量控制。

`/admin/api/keys` 和 `/admin/api/users` 可选 `limit`、`offset`、`query`、`status`、`sort`；不传 `limit` 的原客户端仍取得完整列表。新界面每页 50 条，筛选输入防抖 150 ms，排序与筛选在服务端执行，并保留所有权隔离。增加密钥所属用户/创建时间、密钥名称与用户名称索引；返回记录数量与 DOM 工作量有界。

仍维持单 worker。多 worker 的配置传播、权限失效和一致性没有在本轮引入，不能据此直接增加 worker。

## 验证方式

正式回归在 `tests/test_performance.py`，包括真实 ASGI 请求下的 350 ms SQLite/应用锁竞争、并发用量对账、取消提交、密码状态重检、分页隔离、过载、概览详情兼容、GZip、静态模块图与跨发布旧资源读取。`tests/test_cache.mjs` 验证共享请求、订阅取消、失效、晚到响应隔离与缓存上限。

`tests/performance_browser.py` 使用 Chrome、350 ms 合成 API 延迟，测量 100 次新鲜缓存导航和 100 次首次表单显示，另检查快速导航、分区超时与 100/1,000/5,000 行列表。`tests/ui_smoke.py` 在桌面、平板、移动尺寸覆盖完整管理与用户工作区、草稿、焦点、弹窗、重新登录和系统设置。

`tests/performance_app.py` 是隔离容器专用的合成入口，固定 provider 延迟 100 ms，不进入产品启动链。`tests/performance_load.py` 在 1、8、16、32 并发下记录搜索/管理耗时、拒绝、RSS、线程、FD、任务和用量，支持 `--duration 1800` 的 30 分钟混合负载。只使用合成身份，不读取真实部署环境文件。

所有原始性能产物在本任务工作区，正式结果在下面更新。真实 provider、线上 24 小时观察不属于本地 mock 结果，不能据此声称已经验证。

## 验证结果

2026-10-08，本机 Python 3.11、真实 SQLite/ASGI、桌面 Chrome。容器使用 amd64 镜像在 ARM 主机仿真，限制 1 GiB、128 PID、单 worker，provider 固定等待 100 ms。下面的接口耗时不包含真实供应商网络。

| 验证 | 结果 | 条件与范围 |
|------|------|------------|
| 后端回归 | 302 passed，9 项既有 FastAPI 弃用提示 | 原生、自动、协议、MCP、后台、鉴权、CSRF、撤销、用户隔离与持久化 |
| 注入锁竞争 | 心跳 p99 7.32 ms、最大 12.69 ms；60 次管理读取的并发批次最大 5.22 ms | 350 ms SQLite/应用锁，8 个并发搜索；计数全部匹配 |
| 热导航 | 100 次 p95 6 ms、最大 9.1 ms，无新增读取 | 同一身份、资源缓存新鲜 |
| 首次表单 | 100 次 p95 26.8 ms、最大 31.6 ms；冷打开 61.24 ms | API 与公开站点信息延迟 350 ms |
| 快速导航与分区超时 | 20 轮成功；keys/users/overview 各取消 20 个过期读取，草稿保留 | 每次切换间隔 25 ms；个人统计超时 5 秒，其余分区可用 |
| 三尺寸 UI | 1440/1024/390 均通过，无页面错误、无横向溢出 | 草稿、焦点、重新登录、密钥操作、管理员/用户区与系统设置 |
| 长列表 | 5,000 行时 keys p95 2.19 ms、users 1.11 ms；仅渲染 50 行，无 long task | 各规模/接口 50 次 HTTP 请求，真实 SQLite；名称排序使用覆盖索引 |

性能实现阶段最终测试镜像 `sha256:1b1ea32cd67ae0e806dda38b9fdc3cef4badeabea450fcc9876b14c7df4aa727` 的 HTTP 容量阶梯如下。管理采样每轮访问 compact 概览、workspace 和 readiness，连接池保留最多 48 个 keep-alive 连接；默认搜索容量为 16。

| 搜索并发 | 管理请求样本 | 管理 p95 | 搜索 200 / 429 |
|----------|--------------|----------|----------------|
| 1 | 1,128 | 4.94 ms | 50 / 0 |
| 8 | 972 | 8.82 ms | 400 / 0 |
| 16 | 828 | 11.92 ms | 800 / 0 |
| 32 | 345 | 26.82 ms | 459 / 1,141 |

成功搜索共 1,709 次，全局、个人、密钥计数均为 1,709；拒绝请求不记入完成搜索。429 是容量保护的预期行为。8 并发管理读取超过计划要求的 500 样本，达到 p95 ≤ 200 ms 门槛。

缓存 Node 测试和 Ruff 检查通过。概览兼容、GZip/ETag、完整模块图和跨发布旧模块读取均有后端回归覆盖。最新容器的 HTML no-store、静态 immutable、ETag 304 与 readiness 200 也通过实际 HTTP 验证。

### 持续运行与退出

30 分钟测试使用本轮较早构建的镜像 `sha256:d51f8293c91129b5303698f8facb8767377b12b6b54a5305202ce8148cc040cd`；后续站点元数据加载和兼容默认值等收尾由上面的最新镜像及浏览器回归验收。这两轮镜像结果分别记录，未将较早镜像的持续测试标作最新镜像测试。

8 个并发搜索持续 1,800 秒，共 102,154 次响应，全部 HTTP 200；连同此前阶梯，103,846 次成功搜索与全局、个人、密钥计数完全匹配。每 10 秒采样管理概览，共 180 次，p95 19.38 ms、最大 109.58 ms。

180 次资源采样中 RSS 为 422.3–429.9 MiB；最后 10 分钟为 429.89–429.92 MiB，变化 32 KiB。线程保持 30；最后 10 分钟 FD 为 36–37，任务数随进行中的请求在 19–39 之间变化。停止发请求后 active 搜索降至 0、任务数降至 7、FD 降至 29。健康检查通过，两个专用测试容器均无 OOM、无重启，优雅退出码为 0，验收后已删除。

各资源采样窗口的心跳 p99 最大 11.48 ms，但窗口中的最大单次间隔为 322.41 ms。容器采样反映仿真、主机调度与应用的共同影响，不能据此承诺运行期间没有长停顿；专项锁竞争实验的心跳门槛已通过。持续负载未单独采集每次搜索的客户端延迟分布，阶梯的搜索耗时与该持续测试不能混作一个分布。

### 复现入口

以下命令在项目根目录依次执行；`uv` 入口不能并发运行。输出目录沿用本次任务，重复运行时可另选项目内的任务目录。

```sh
sh scripts/uv.sh run pytest -q --basetemp .bensz-api/task-20261008-0649-performance/shared/pytest-final
node --test tests/test_cache.mjs
sh scripts/uv.sh run python tests/performance_browser.py --output .bensz-api/task-20261008-0649-performance/shared/browser-performance.json
sh scripts/uv.sh run python tests/ui_smoke.py --output .bensz-api/task-20261008-0649-performance/shared/ui
sh scripts/uv.sh run python tests/performance_lists.py --output .bensz-api/task-20261008-0649-performance/shared/list-performance.json
```

容器基准需要将 `tests/performance_app.py`、`tests/performance_load.py` 只读挂载到 `/app/`，将任务产物目录挂载到 `/app/performance-results`，以 `uvicorn performance_app:app --host 0.0.0.0 --port 8000 --no-access-log --limit-concurrency 64 --timeout-graceful-shutdown 30` 启动隔离容器。不要使用真实部署数据库或凭据。启动后运行：

```sh
docker exec <隔离测试容器> python /app/performance_load.py --url http://127.0.0.1:8000 --requests 50 --duration 1800 --output /app/performance-results/sustained.json
python3 docs/deploy/check_health.py <隔离测试容器>
```

### 适用边界

真实 provider 与线上 24 小时观察尚未执行。本机仿真容器的延迟和内存不能直接换算成目标服务器容量。锁竞争实验达到计划心跳门槛，但早期容器阶梯曾观测到 273 ms 间隔，持续负载出现过 322 ms；不能据本地实验承诺任意负载下没有 200 ms 停顿。v1.0.9 上线的数据库快照、健康与短程真实检索见发布验收；目标机器性能阶梯、24 小时观察及监控定时器接入仍未验证。
