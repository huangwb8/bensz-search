# 添加搜索 API 与远端 bensz-search

本教程面向 bensz-search 管理员，按“获取供应商密钥 → 后台添加 → 单独测试 → 应用调用”的顺序操作。依据当前项目源码及 **LiteLLM 1.103.2** 编写，本地后台默认地址为 <http://127.0.0.1:8898/admin>；自定义部署请替换地址和端口。

## 先分清两种密钥

| 密钥 | 从哪里获取 | 填在哪里 | 用途 |
|---|---|---|---|
| 供应商 API Key | Exa、Brave 等供应商的开发者控制台 | bensz-search 后台 → **Search API** → 添加或编辑服务 → **API Key** | bensz-search 向供应商发起搜索 |
| bensz-search 访问密钥 | 用户区 → **我的密钥** → **创建我的密钥** | 应用请求的 `Authorization: Bearer …` | 应用或 AI Agent 调用 bensz-search |

供应商 Key 输入框只粘贴密钥本身，不加 `Bearer `、`x-api-key:` 等前缀，也不粘贴整段 curl。后台登录密码用于登录；应用接入使用“我的密钥”页面生成的 key。管理员区的“全体访问密钥”用于查看、撤销和删除所有用户的密钥；用户可在“我的密钥”中删除自己的有效、已撤销或已过期密钥。密钥可设置过期时间；原生 Search API 需要 `search` 权限，协议 HTTP 与 MCP 需要 `protocol` 权限，默认同时授予两者。

## 后台添加的通用步骤

1. 使用管理员账号登录。初始账号通常为 `admin`，初始密码见部署生成的 `docs/deploy/.secrets/local-admin.txt`；修改过密码后使用新密码。尚未部署时先阅读[部署说明](deploy/README.md)。
2. 打开左侧 **Search API**，点击 **添加 Search API**。
3. 在配置抽屉中填写下表字段，然后点击 **保存配置**；也可点击 **保存并测试**，保存后直接打开测试。
4. 在新服务所在行点击 **测试**，用 `Python official documentation` 这样的普通查询测试（最多 1000 字符）。测试会调用真实供应商，可能消耗额度。
5. 确认显示“连接成功”、结果数大于 0，并能看到标题和链接。再到 **搜索调试台**，在“搜索服务”中选中这条配置，执行一次搜索。
6. 单个服务通过后，将“搜索服务”切换为 **自动智能路由**。自动模式按任务、预算和可用性选择服务，并不保证每次都调用全部已添加服务。

| 表单字段 | 怎么填 |
|---|---|
| 服务名称 | 自己取的唯一名称，例如 `exa-main`；1–64 个字母、数字、短横线或下划线，不能使用保留名 `auto`。保存后名称不能修改 |
| 服务类型 | 选择对应供应商，例如 Exa；不能只填 Key 而不确认类型 |
| API 服务地址 | 商业服务通常**留空**即可使用原生默认地址；手动填写时使用下面的地址速查表 |
| API Key | 粘贴该供应商控制台生成的密钥；商业服务必填；bensz-search 使用远端访问密钥 |
| 搜索引擎（可选） | 仅 SearXNG 使用，其他服务留空 |
| 超时时间（ms） | 可先填 `15000`，即 15 秒；允许范围为 `100`–`60000` |
| 启用服务，参与搜索路由 | 勾选后可供搜索调试台、外部 API 和自动路由使用；也可先不勾选，保存后单独测试，再点击“启用” |

可以添加多条相同类型服务，例如 `exa-main`、`exa-backup`，但名称必须不同。编辑同类型服务时 API Key 留空会保留原密钥；更换服务类型时必须提供新供应商的密钥。保存、启停或删除立即影响新的搜索请求，无需重启。

SearXNG 可在服务的“更多”操作中同步实例引擎并查看验证依据。普通编辑和启停保留已有证据，更换实例后需要重新同步。配置导出不包含密钥或引擎证据；导入时同名服务不会覆盖，需密钥的服务默认停用，补齐凭据并测试后再启用。

## 地址与类型速查

以下地址均为供应商的搜索接口地址，不是账号登录网页。手动填写时按表复制，不添加末尾斜杠或 `?query=…`。

| 后台服务类型 | 建议服务名称 | API 服务地址：留空或填写以下值 | 适用于首次导入的环境变量 |
|---|---|---|---|
| OpenAI Web Search | `openai-main` | `https://api.openai.com/v1` | `OPENAI_API_KEY`、`OPENAI_SEARCH_API_BASE`、`OPENAI_SEARCH_MODEL` |
| Exa | `exa-main` | `https://api.exa.ai` | `EXA_API_KEY` |
| Brave | `brave-main` | `https://api.search.brave.com/res/v1/web/search` | `BRAVE_API_KEY` |
| Tavily | `tavily-main` | `https://api.tavily.com` | `TAVILY_API_KEY` |
| Serper | `serper-main` | `https://google.serper.dev` | `SERPER_API_KEY` |
| Perplexity | `perplexity-main` | `https://api.perplexity.ai` | `PERPLEXITY_API_KEY` |
| bensz-search | `academic-remote` | **必填**远端根地址，例如 `https://search.example.org` | `BENSZ_SEARCH_UPSTREAM_URL`、`BENSZ_SEARCH_UPSTREAM_KEY` |
| SearXNG | `searxng-local` | **必填**实例地址，例如 `http://host.docker.internal:8080` | `SEARXNG_API_BASE`、`SEARXNG_ENGINES` |

**Brave 的地址格式需要特别注意**：当前 adapter 直接使用完整 endpoint，手动填写时必须保留 `/res/v1/web/search`。Exa、Tavily、Serper、Perplexity 的 adapter 会补上 `/search`，填写表中的根地址即可。

## bensz-search：接入其他实例

在服务类型中选择 **bensz-search**，填写远端根地址和远端用户区“我的密钥”页面生成的 Key，搜索引擎留空，建议超时 `15000` ms。远端继续执行自己的自动路由，也可接入其他实例。参与节点均需升级到支持联邦搜索的版本；默认最多 4 层，提供循环检测、全链调用额度、超时传递与来源去重。详见[实例组合与递归搜索](smart-search-router/federated-search.md)。

## OpenAI：使用 Responses 内置网页搜索

使用 OpenAI 开发者 API Key，在服务类型中选择 **OpenAI Web Search**。地址留空，默认模型 `gpt-4.1-mini`，建议超时 `30000`；可以设置搜索上下文大小与输出 token 上限。保存后测试，确认账号支持所选模型和 `web_search`。兼容网关地址填写包含 `/v1` 的 API base，必须支持 Responses 与该内置工具。

OpenAI 会收取搜索和模型费用；返回引用与来源链接，AI 生成摘要有明确标记。来源缺少发布日期时无法满足严格时效过滤。已有数据库通过后台新增，环境变量只首次导入。详见 [OpenAI 接入说明](smart-search-router/openai-web-search.md)与[已读取的官方协议](https://developers.openai.com/api/docs/guides/tools-web-search)。

## Exa：获取 Key 并添加

1. 打开 [Exa Dashboard](https://dashboard.exa.ai/)，注册或登录。
2. 在控制台的 API Keys 区域创建密钥并复制。检查账号剩余额度；需要时在供应商控制台配置计费。
3. 在 bensz-search 添加：服务名称 `exa-main`，服务类型 **Exa**，API 服务地址留空，API Key 粘贴刚复制的值，搜索引擎留空，超时 `15000`。
4. 保存后点击该行“测试”，确认返回搜索结果。

项目底层类型标识为 `exa_ai`；调用 bensz-search 时使用你保存的服务名称 `exa-main`。无需安装 Exa SDK。

官方说明：[Exa Quickstart](https://exa.ai/docs/get-started/quickstart)。

## Brave：使用 Brave Search API 的 Key

1. 打开 [Brave Search API Dashboard](https://api-dashboard.search.brave.com/)，注册或登录。
2. 在控制台选择包含 **Web Search** 的 API 方案，按其要求开通订阅或计费；在 API Keys 页面创建并复制密钥。
3. 在 bensz-search 添加：服务名称 `brave-main`，服务类型 **Brave**，API 服务地址留空，API Key 粘贴 Brave Search API 的密钥，搜索引擎留空，超时 `15000`。
4. 如需手动填地址，使用 `https://api.search.brave.com/res/v1/web/search`，保存后测试。

需要在 Search API 控制台申请密钥；安装 Brave 浏览器不会自动提供搜索 API Key。请求所需的 `X-Subscription-Token` 由项目自动设置。

官方说明：[Brave Web Search 入门](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started)。

## Tavily：从控制台复制 API Key

1. 打开 [Tavily 控制台](https://app.tavily.com/)，注册或登录。
2. 从控制台的 API Keys 区域复制已有密钥，或创建新密钥。确认可用 API Credits。
3. 在 bensz-search 添加：服务名称 `tavily-main`，服务类型 **Tavily**，API 服务地址留空，API Key 粘贴 Tavily 密钥，搜索引擎留空，超时 `15000`。
4. 保存后测试。无需在 bensz-search 配置 Tavily SDK 或填写登录密码。

官方说明：[Tavily Quickstart](https://docs.tavily.com/documentation/quickstart)。

## Serper：使用 serper.dev 的 Key

1. 打开 [Serper 官网](https://serper.dev/)，通过注册或登录入口进入控制台。
2. 找到 API Key 区域，复制密钥，并确认账号的查询额度或计费状态。
3. 在 bensz-search 添加：服务名称 `serper-main`，服务类型 **Serper**，API 服务地址留空或填 `https://google.serper.dev`，API Key 粘贴 Serper 密钥，搜索引擎留空，超时 `15000`。
4. 保存后测试。

Serper 使用自己的 API Key。不要填 SerpAPI、Google Cloud 或 Google Programmable Search 的密钥；它们属于其他服务。虽然接口域名包含 `google`，这里不需要填写 Google 搜索引擎 ID（`cx`）。

如果测试显示“服务额度不足”，请到 Serper 控制台检查该 Key 所属账号的余额并充值，或换用有额度的 Key。Serper 的 `Not enough credits` 会返回 HTTP 400；从 1.0.4 起，项目将它识别为 `quota`，自动搜索可回退到其他已授权来源，并对该来源冷却 5 分钟。后台连接测试可直接重试，不受自动路由冷却影响。旧版本可能只显示 `bad_request`，这类报错需要区分额度耗尽与真正的参数错误。

## Perplexity：接入 Search API

1. 打开 [Perplexity API 控制台](https://console.perplexity.ai/)，注册或登录。
2. 按控制台要求创建或选择 API 项目，配置 API 计费或额度，然后在 API Key 管理页面生成密钥。网页产品的订阅与 API 可用额度应分别在控制台确认。
3. 在 bensz-search 添加：服务名称 `perplexity-main`，服务类型 **Perplexity**，API 服务地址留空或填 `https://api.perplexity.ai`，API Key 粘贴生成的值，搜索引擎留空，超时 `15000`。
4. 保存后测试。

本项目调用的是 **`POST https://api.perplexity.ai/search`**，返回网页搜索结果。本表单无需填写 `sonar` 等聊天模型名；也不要填写 `/chat/completions` 地址。第三方服务若只提供 Perplexity 聊天接口，其 Key 和地址不能据此视为兼容 Search API。

官方说明：[Perplexity API 入门](https://docs.perplexity.ai/docs/getting-started/overview)。

## SearXNG：添加自己的实例

SearXNG 通常无需 API Key，但必须有服务器可访问的实例，并启用 JSON 搜索输出。

1. 确认自己的 SearXNG 配置包含以下格式；修改后按该实例的部署方式重启：

   ```yaml
   search:
     formats:
       - html
       - json
   ```

2. 在 bensz-search 添加：服务名称 `searxng-local`，服务类型 **SearXNG**，填写实例地址，API Key 通常留空，超时 `15000`。
3. 如 bensz-search 在 Docker 中、SearXNG 在宿主机 `8080` 端口，填写 `http://host.docker.internal:8080`。容器里的 `127.0.0.1` 指向容器自身；如果实例位于其他主机或同一 Docker 网络，应填写容器实际可访问的地址。
4. “搜索引擎”填写实例上已启用的引擎，多个以逗号分隔。点击 **填入常用引擎** 可填入 `google, bing, duckduckgo, brave, baidu, wikipedia, github, stackoverflow, pubmed, arxiv, google news`；也可按实例实际可用情况增删。留空时使用实例默认引擎。自动路由对网页、学术、代码和新闻查询使用对应的已配置子集；原生显式搜索使用保存的完整列表。
5. 本项目独立部署 SearXNG 时，可参考 [实例设置模板](deploy/searxng-settings.yml.example) 启用对应引擎和 JSON 输出。引擎是否能返回结果还取决于网络、CAPTCHA 和限流，需用真实查询确认。已有后台配置需编辑后保存，更新环境变量不会覆盖数据库。
6. 保存后测试，按所选引擎使用合适查询，如 GitHub 用 `python`，PubMed 用 `colorectal cancer`。有 HTTP 200 但无结果仍判为失败，需检查上游引擎的限流、CAPTCHA 或故障。

若实例前面有 Bearer 鉴权网关，可在 API Key 填写对应 token；当前 adapter 会设置 `Authorization: Bearer …`。表单不支持配置 Basic Auth、Cookie 或任意自定义鉴权头。

官方说明：[SearXNG 搜索配置](https://docs.searxng.org/admin/settings/settings_search.html)。

## 添加后，让应用使用这些服务

在用户区 **我的密钥** 页面点击 **创建我的密钥**，为应用取一个名称并保存完整 key；完整值只展示一次。将它注入应用环境变量 `BENSZ_SEARCH_API_KEY` 后，在终端运行：

```bash
curl --noproxy '*' http://127.0.0.1:8898/search \
  -H "Authorization: Bearer ${BENSZ_SEARCH_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "Python official documentation",
    "search_tool_name": "exa-main",
    "max_results": 3
  }'
```

`search_tool_name` 是**你在后台保存的服务名称**，必须与拼写、大小写一致，且服务已启用。例如配置名为 `exa-main`，就填写 `exa-main`。若你使用本教程的其他名称，替换为 `brave-main`、`tavily-main`、`serper-main` 或 `perplexity-main`。响应应包含非空的 `results` 数组。

单个配置确认可用后，将 `search_tool_name` 改成 `auto` 即可使用智能路由；可增加 `"debug": true` 查看自动路由计划和尝试记录。应用请求不需要携带供应商 Key 或供应商地址；这两项在后台管理。

## 仅首次启动时：用环境变量导入

已运行的服务建议直接使用后台添加。对于**尚未初始化数据库的新部署**，也可先运行：

```bash
python docs/deploy/deploy_local.py --init-only
```

在本地编辑生成的私有 `docs/deploy/.env`，填写所需项；不使用的商业服务保持空值：

```dotenv
EXA_API_KEY=<你的 Exa Key>
BRAVE_API_KEY=<你的 Brave Search Key>
TAVILY_API_KEY=<你的 Tavily Key>
SERPER_API_KEY=<你的 Serper Key>
PERPLEXITY_API_KEY=<你的 Perplexity Key>
```

以上为占位符，填写时替换整个 `<…>`。保留初始化脚本生成的管理员密码、master key 和加密密钥。没有 SearXNG 时将 `SEARXNG_API_BASE` 清空，然后执行 `python docs/deploy/deploy_local.py`。

首次导入的默认服务名称由 [`config/litellm.yaml`](../config/litellm.yaml) 定义，分别为 `exa`、`brave`、`tavily`、`serper`、`perplexity`、`searxng`。这与上面的手动添加示例 `exa-main` 等不同；调用时以后台实际名称为准。

**数据库初始化后，以后台配置为准。** 修改 `.env` 并重启不会覆盖已保存的服务；更新或轮换供应商 Key 应在后台编辑对应条目。项目的 Perplexity 导入变量是 `PERPLEXITY_API_KEY`，初始化时会将其值显式传给 adapter，无需另设 LiteLLM 内部使用的 `PERPLEXITYAI_API_KEY`。

## 常见失败怎么处理

| 现象或失败类别 | 检查与处理 |
|---|---|
| 没有“Search API”菜单，或提示需要管理员权限 | 使用管理员账号登录；成员只能搜索和管理自己的访问密钥 |
| 保存提示需要 API Key | 新建商业服务必须填写对应供应商的 Key；地址输入框只填地址 |
| 保存提示名称重复或名称无效 | 换一个唯一名称，只用字母、数字、`-`、`_`，不能使用 `auto` |
| `auth` | 上游返回 401/403；检查 Key 是否完整、已撤销、属于所选供应商，以及账号是否具备搜索接口权限 |
| `quota` | 上游返回 402；到供应商控制台检查余额或计费状态 |
| `rate_limit` | 上游返回 429；检查调用频率和供应商额度，降低并发或等待限流恢复 |
| `timeout` | 检查服务器或 Docker 容器的外网连接；可适当增加服务超时。后台搜索还有请求总时限，仅增大服务超时可能无效 |
| `bad_request` | 检查服务类型、接口路径和请求参数；Brave 地址需包含完整路径，Perplexity 应使用 Search API |
| `unavailable` / `invalid_response` | 检查供应商状态、DNS、TLS、网络代理，以及自定义地址是否返回兼容的搜索 JSON |
| `empty` | 已收到响应但无搜索结果；换普通查询。SearXNG 检查 JSON 输出和引擎可用性 |
| 单独测试成功，搜索调试台找不到配置 | 检查该服务是否启用；未启用配置也允许单独测试 |
| 调用 `/search` 返回 401 | 使用 bensz-search “我的密钥”页面生成且有效的 key；检查过期、撤销或账号停用；供应商 Key 不能用于此处 |
| `auto` 没有选择刚添加的服务 | 先按服务名称单独调用；自动模式会依据任务、预算及熔断状态选择。查看自动请求的 debug 信息 |
| `/ready` 成功，但查询失败 | 就绪检查只确认存在启用配置；外部检索是否可用以“测试”和实际搜索为准 |

错误类别按上游实际响应映射；例如额度问题也可能由供应商返回 429，不能仅凭类别认定账单状态。排查时提供服务名称、类型、错误类别和时间即可，勿分享完整 Key 或私有 `.env`。

## 依据与验证范围

字段与行为依据项目 [`admin.py`](../src/bensz_search/admin.py)、[`app.js`](../src/bensz_search/static/app.js)、[`litellm.yaml`](../config/litellm.yaml)，以及锁定的 LiteLLM **1.103.2 发行包**中 `llms/<provider>/search/transformation.py`；upstream revision 以发行版本标识，详见[调用链审计](smart-search-router/architecture-audit.md)。

2026-10-03 查阅了 Exa、Brave、Tavily、Perplexity 官方入门页；本次网络环境访问 Serper 官网失败，保留官网入口供用户操作。供应商控制台页面和额度政策可能调整，以登录后显示为准。本教程核对了配置字段与 adapter 地址规则；没有使用真实商业密钥发起搜索，不将文档核对视为商业服务线上验收。既有真实检索记录见[验收说明](smart-search-router/production-verification.md)。
