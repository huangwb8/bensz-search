# 卡死与页面切换迟滞诊断

> 本文保留优化前的诊断与基线；当前实现与测量见[性能优化实现与验证](performance-implementation.md)。

2026-10-07。结论依据本项目当前源码、真实 Chrome 下的合成 API 实验，以及隔离 SQLite 的锁竞争实验。已经复现会阻塞服务端和拖慢页面切换的机制；尚未取得故障发生时的部署日志、浏览器 Performance/HAR 或容器资源曲线，因此不能断言每次线上卡死都由同一触发条件造成。

## 核心判断

优先处理两处问题：**异步请求路径上的同步数据库与锁等待**，以及**页面显示对完整数据请求的依赖**。两者会相互放大：后台一旦遇到慢写入或锁竞争，界面就持续等数据；用户再次切换页面，旧读取仍在执行，进一步增加负担。

当前证据支持先修正请求与数据加载方式。还没有证据需要更换前端框架或数据库，也没有证据证明 CPU、内存或外部搜索服务本身是本次部署故障的唯一原因。

## 审计范围与版本依据

- bensz-search 基线 HEAD：`be71ea3286bd56472a65f709a09d17be7fbe6d90`，配置版本 `1.0.8`。工作区已有并行发生的个人用量等未提交改动，本任务未修改这些源码。
- LiteLLM：依赖锁定的 `1.103.2` 发行包；没有对应 upstream Git commit，不以其他参考 checkout 替代运行依赖。
- dudu 对照 HEAD：`f828235e1efd3b3539e5ddde325cff0ce595bdd5`；只读其正式前端源码，没有运行或修改该项目。
- 探针覆盖原生静态页面、应用的 `managed_api_auth`、`Telemetry` 和 `AdminStore`。数据库、身份和 API 响应均为合成数据，没有使用部署凭据或调用真实 provider。
- [源码指纹](../../.bensz-api/task-20261007-2119-performance-diagnosis/shared/source-baseline.json)记录工作区 SHA256；[HEAD 核对](../../.bensz-api/task-20261007-2119-performance-diagnosis/shared/head-mechanisms.json)确认核心阻塞路径与页面加载机制也存在于已提交 HEAD。

## 服务端：慢操作会拖住其他请求

### 统计落盘仍在事件循环上执行

事件循环是这个服务调度异步请求的线程。等待外部 HTTP 的 `await` 可以让其他请求继续运行；同步 SQLite 操作和 `threading.RLock` 等待会占住这条线程。

实际链路为：[`SmartRouter.search`](../../src/bensz_search/router.py#L83) → [`Telemetry._append`](../../src/bensz_search/telemetry.py#L139) → [`initialize_admin` 绑定的 sink](../../src/bensz_search/admin.py#L917) → [`AdminStore.record_usage`](../../src/bensz_search/admin_store.py#L456)。显式搜索的统计也通过 `record_execution` 进入同一 sink。

`record_usage` 在事务中取得写锁、读取并合并每日 JSON、更新用量和清理历史，提交也由当前调用线程执行。`Telemetry` 还在持有自身锁时调用 sink，数据库慢操作同时拉长了统计快照的等待时间。搜索结束时发生这类等待，其他页面 API 和健康请求也无法及时调度。

### 鉴权和部分管理操作会同步等待共享数据库锁

[`managed_api_auth`](../../src/bensz_search/admin.py#L340) 是异步函数，但直接调用 `authenticate_key` 和 `active_names`。后台搜索、provider 测试和引擎同步也存在直接 store 调用；[`readiness`](../../src/bensz_search/server.py#L235) 读取启用服务时同样访问 store。

[`AdminStore`](../../src/bensz_search/admin_store.py#L33) 只有一个 SQLite 连接和一个覆盖读写的 `RLock`。即使开启 WAL，应用层这把锁仍让读写相互等待。[`login`](../../src/bensz_search/admin_store.py#L208) 的 scrypt 校验也在锁内进行；登录函数已经移到工作线程执行，但其他请求依然会等待它持有的 store 锁。

需要区分现有代码：多数管理 GET 使用同步 `def`，FastAPI 会把这些 endpoint 及同步依赖放入线程池。这里没有认定“所有管理接口都在事件循环上执行”；问题在直接从异步路径进入同步 store，以及跨路径共享的长临界区。

### 锁竞争实验

使用独立 SQLite 文件，让另一个连接持有写事务 350 ms，或让工作线程持有 store 锁 350 ms；同时每 5 ms 调度一次异步心跳。下面是本机单次测量，数值用于证明机制，不代表线上吞吐或延迟分位。

| 实验 | 操作耗时 | 心跳最大间隔 | 判断 |
|---|---:|---:|---|
| 当前统计路径遇到 SQLite 写锁 | 358.01 ms | 360.58 ms | 数据库等待阻塞事件循环 |
| 当前鉴权路径遇到 store 锁 | 328.13 ms | 330.78 ms | 应用层锁等待阻塞事件循环 |
| 同一统计落盘移到工作线程的对照 | 356.00 ms | 5.90 ms | 数据库仍然慢，但调度线程能继续工作 |

鉴权实验先做无竞争调用预热；锁保持时间包括探针开始前的 25 ms 心跳预热，因此鉴权实际等待小于 350 ms。无竞争路径还包含首次对象初始化、磁盘和调度影响，不据此推导稳态性能。

**工作线程对照只验证方向，不是完整修复。** 若整段 `Telemetry.record` 被移出事件循环，却继续在其锁内等待数据库，快照读取仍可能受阻。实施必须同时缩短锁范围，将持久化移出 telemetry 临界区。

证据：[探针](../../.bensz-api/task-20261007-2119-performance-diagnosis/systematic-debugging/input/probe_backend.py)、[结果](../../.bensz-api/task-20261007-2119-performance-diagnosis/systematic-debugging/output/backend-probe.json)。

## 前端：切换速度取决于数据请求完成时间

### 缺少按资源复用的数据缓存

[`navigate`](../../src/bensz_search/static/app.js#L133) 每次把内容区替换为骨架，再等待 `loadPage` 完成，最后整页渲染。[`loadPage`](../../src/bensz_search/static/app.js#L186) 有两个关键行为：

- 每次进入概览或搜索页，都重新获取 `/overview`。搜索表单所需的是可用服务列表，但也等待包含统计、健康和最近事件的概览响应。
- 用户概览通过 `Promise.all` 等待概览、密钥和个人用量全部返回；其中一个慢或失败，整个内容区都受到影响。列表页面也在每次进入时重读接口。

`state.overview` 虽然保存最近结果，却没有被用来让概览和搜索页先显示可用内容。`revision/loadRevision` 能防止旧响应覆盖新页面，但不会取消旧请求。所有请求统一使用 [`75 秒超时`](../../src/bensz_search/static/app.js#L45)，轻量页面读取遇到故障时会表现为很长的等待。

### Chrome 延迟实验

运行当前静态资源，使用真实 Chrome 和合成 API：`/overview` 固定延迟 350 ms，列表接口固定延迟 120 ms。通过浏览器内 `performance.now` 与 DOM 变更观察，测量点击到骨架退出的时间，避免把测试工具轮询时间算进结果。

| 操作 | 内容显示耗时 | 新 API 请求 |
|---|---:|---:|
| 进入 Search API | 129.3 ms | 1 |
| 返回概览 | 358.7 ms | 1 |
| 进入搜索调试 | 357.4 ms | 1 |
| 再次进入 Search API | 129.7 ms | 1 |
| 再次返回概览 | 359.5 ms | 1 |
| 已有概览数据时进入调用指南 | 2.6 ms | 0 |

在这个小数据场景，主要等待来自 API 依赖，渲染开销没有解释几百毫秒的差异。快速尝试切换 8 次、间隔 25 ms，服务端观察到 6 个 API 请求，浏览器观察到 0 个 API 请求被取消；不把尝试点击次数等同于服务端请求次数。

证据：[探针](../../.bensz-api/task-20261007-2119-performance-diagnosis/systematic-debugging/input/probe_browser.py)、[结果](../../.bensz-api/task-20261007-2119-performance-diagnosis/systematic-debugging/output/browser-probe.json)。

## dudu 中值得复用的机制

| 机制 | dudu 源码证据 | 对本项目的启发 |
|---|---|---|
| 页面间复用数据 | `apps/web/src/services/queryClient.ts` 设置 `staleTime: 30_000`，页面使用独立 query key | 已加载页面在短时间内返回时可直接显示数据 |
| 按业务资源加载 | `SubscriptionsPage.tsx` 分别查询 subscriptions 和 groups；`DashboardPage.tsx` 使用独立 dashboard query | 让表单、列表、统计分别处理加载和错误 |
| 页面代码按需加载 | `apps/web/src/app/routes.tsx` 使用 `lazy` 与 `Suspense` | 大型前端可减少初始代码负担；本项目目前五个 JS 模块合计约 112 KB，优先级较低 |

这些是源码层面的机制对照，未进行两项目在同硬件、同网络、同数据量下的性能排名。也没有假定 dudu 的所有请求都支持取消，或其布局组件完全不会重新挂载。

## 次要放大因素与待验证项

**概览返回的历史超出首屏使用量。** `Telemetry.snapshot` 返回最多 200 条完整事件，概览只显示最近 20 条。同一合成事件重复填满历史后，JSON 从 94,976 字节缩减至 20 条时的 10,736 字节，减少约 89%。这是合成 payload 的结果；真实大小取决于计划和 attempts。请求详情功能仍需要详细数据，不能直接删掉后端历史。

**静态资源被统一禁止缓存。** [`SearchInputMiddleware`](../../src/bensz_search/integration.py) 对以 `/admin` 开头的响应附加 `Cache-Control: no-store`，包含 `/admin/static/*`。这会影响整站重新打开或刷新；站内菜单切换通常不会重取模块，因此它不能独立解释每次切页迟滞。

**大列表可能产生浏览器长任务。** 密钥和用户接口返回全量列表；客户端筛选、排序及表格 HTML 重建也处理全量数据。当前小 fixture 没有验证这条路径在实际规模下的影响，应在数据规模达到数百至数千行时做定向测量。

**部署容量尚未证实为根因。** 当前 Dockerfile 启动一个 Uvicorn worker，`--limit-concurrency 64`；生产 Compose 限制内存 1 GiB。64 是 Uvicorn 的连接/任务门槛，不能当作已验证的搜索容量。本机可见旧 `0.2.1` 搜索容器在观察时使用约 364 MiB、重启次数 0、`OOMKilled=false`，不代表用户故障部署。Docker 标记 `unhealthy` 也不会仅因该状态被 `restart: unless-stopped` 自动重启。

**简单增加 worker 有额外约束。** `AdminRuntime.refresh` 只替换当前进程路由；健康、熔断和部分统计也在进程内。多 worker 会增加内存，并可能让配置热更新只对部分请求生效，必须先解决一致性再评估。

## 结论与后续

已经定位并复现两项可直接优化的机制：服务端同步等待会阻塞其他异步请求；页面反复等待完整数据，导致返回已访问页面仍然受网络影响。建议按[优化计划](../plans/2026-10-07-performance-optimization.md)先修正异步边界和数据加载，再根据真实负载决定容量和列表优化。

线上最终归因还需要卡住时的容器状态、事件循环延迟、请求总耗时、SQLite 等待与浏览器请求瀑布。现有搜索 `latency_ms` 在统计落盘前计算，无法完整反映这段响应尾部等待；需要独立测量 HTTP 总耗时。
