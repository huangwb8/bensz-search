# 实例组合与递归搜索

`bensz_search` 是原生搜索源类型。一个实例可以接入多个远端 bensz-search，远端也可以继续接入其他实例。各节点独立维护密钥、权限和路由策略，对上一层提供统一搜索服务。本功能随 **1.0.4** 发布。

## 后台接入

参与组合的实例均需升级到支持联邦搜索的版本。在远端创建独立的应用访问密钥，然后在本地管理员后台 **搜索引擎 → 添加 Search API** 中配置：

| 字段 | 填写方式 |
|---|---|
| 服务名称 | 如 `academic-remote`，用于本地选择该来源 |
| 服务类型 | **bensz-search**，内部标识 `bensz_search` |
| API 服务地址 | 如 `https://search.example.org`；可含部署前缀，不要附加 `/search`、`/bensz-search/v1` 或 MCP 地址 |
| API Key | 远端 bensz-search 的**访问密钥** |
| 搜索引擎 | 留空，下游执行自己的自动路由 |
| 超时时间 | 建议 `15000` ms，同时受整次请求剩余时间限制 |
| 下游费用估算 | 默认 `$0.02`/查询，按远端整条搜索子树设置保守预留 |

保存后点击 **测试**，再在搜索调试选择该来源。停用配置仍可单独测试，编辑时密钥留空保留原密钥。密钥加密保存，列表与搜索结果不返回明文。

调用方式保持一致：`POST /search` 指定 `search_tool_name: "academic-remote"`，或使用 `auto`；v1 planned 使用该名称作为 `tool_id`，MCP 共用相同执行逻辑。远端作为整体服务参与规划，不展开其内部引擎。能力分数是本地先验，远端质量与来源独立性没有实测。

## 配置文件

`config/litellm.yaml` 提供可选模板，配置 `BENSZ_SEARCH_UPSTREAM_URL` 和 `BENSZ_SEARCH_UPSTREAM_KEY` 后，首次初始化可导入。已有后台配置以数据库为准，不因环境变量变化自动覆盖。

```yaml
search_tools:
  - search_tool_name: academic-remote
    litellm_params:
      search_provider: bensz_search
      api_base: os.environ/BENSZ_SEARCH_UPSTREAM_URL
      api_key: os.environ/BENSZ_SEARCH_UPSTREAM_KEY
      timeout: 15
```

自定义 capabilities 文件应保留 `bensz_search` 类型模板。后台“下游费用估算”（管理员 API 的 `estimated_cost_usd`） 表示远端**整条子树**的保守估算，默认每次查询 `$0.02`；本地预留该额度，远端在额度内继续分配。费用不逐层重复相加，也不保证真实账单。估算过低会限制远端可选来源，估算过高会更快耗尽本地预算。

## 递归控制

| 控制 | 行为 |
|---|---|
| 循环 | 路径包含实例 ID；连接自身或 A→B→A 返回 `federation_loop` |
| 层数 | 默认最多 **4 个 bensz-search 实例**，包含入口；最后一层仍可调用普通供应商。`BENSZ_SEARCH_MAX_HOPS` 支持 1–8，各层取本地与传入上限的较小值 |
| 调用额度 | 默认整棵调用树最多 **10 次搜索调用**，包含委托边和叶子供应商，受 `BENSZ_SEARCH_MAX_CALLS` 进一步限制。并行、fallback、列表查询分配互不重叠的额度；未用额度不回收，可能少搜 |
| 超时 | 传递剩余毫秒数，各层按接收时刻重建 deadline。网络传输会使下游 deadline 略晚，父端整体超时与取消是最终边界 |
| 权限 | 每层使用独立的远端 Key，继续执行自身 Key/team 权限；不转发本地用户身份、Cookie、上层 Key 或日志 metadata |
| 旧版本 | 先检查远端 capabilities 的联邦支持与权限；不支持则停止该分支，不提交搜索。关闭 HTTP 重定向，避免转发凭据 |

实例 ID 默认由部署的 `BENSZ_SEARCH_SECRET` 派生，不暴露 secret；同一实例的 worker 使用相同 ID。不同实例使用独立 secret；复制配置时可显式设置不同的 `BENSZ_SEARCH_INSTANCE_ID`（1–64 个 ASCII 字母、数字、`_` 或 `-`）。ID 在 HTTP 响应头公开，仅识别搜索节点。无 secret 的开发环境使用进程 ID，多进程部署应显式设置稳定 ID。

内部 `X-Bensz-Search-Context` 头携带版本、实例路径、层数、剩余时间、调用额度与预算。重复头、非法 ID、重复路径、超限值会被拒绝，错误不回显输入。约束适用于遵循协议的实例，不能证明第三方实际遵守了其声明。

## 来源与融合

v1 的 `sources` 新增可选 `instance_path`、`upstream_tool_id`、`upstream_call_id`、`upstream_rank`，保留远端节点路径与叶子来源；当前层 `tool_id`、`call_id`、名次保持本地含义。来源链扁平化并限制长度。原生 `/search` 结果也包含 `source_families` 与 `upstream_sources`。

两个远端均返回 Brave 的同一文档时，只计一次 Brave 贡献；聚合分支的多个底层 family 分摊一票，避免随来源数量放大权重。远端来源信息仍是未经独立测量的声明。远端部分成功在上层保留 `partial_success` 状态。URL、摘要类型、日期与域名继续使用既有归一化和过滤。

## 验证

`tests/test_federated_search.py` 使用多实例 ASGI 执行实际 HTTP 协议并模拟底层供应商，覆盖来源与约束传递、循环、层数、并行额度、列表查询、deadline/取消、鉴权 fallback、旧版本、重定向、体积与非法输入。`tests/test_federated_admin.py` 使用真实后台和 LiteLLM Router 验证 CRUD、密钥保留、启停、测试、显式接口和 v1 planned。

本次未调用真实远端部署或商业供应商，未发布镜像或更新服务器。
