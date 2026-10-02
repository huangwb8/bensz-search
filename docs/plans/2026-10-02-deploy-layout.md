# Docker 部署文件归档计划

## 需求与范围

将 Docker 部署配置、构建文件、初始化脚本和部署说明统一托管在 `docs/deploy/`；按用户补充要求，将私有 `.env` 与 `.secrets/` 同步迁入该目录，保留已有凭据、Docker 项目名与数据卷。

## 实施步骤

- 迁移 Dockerfile、构建忽略规则、三份 Compose 配置、环境变量示例、部署脚本和说明。
- 修正 Compose 构建上下文、Dockerfile 和环境文件路径；修正脚本项目根目录及私有配置目录定位。
- 同步 README、设计/验收文档链接、项目目录约定与 CHANGELOG。
- 校验生产、fixture 和 live Compose 配置，验证脚本路径与初始化行为并构建镜像。
- 追加 BAC 贡献记录，交付前验证账本。

## 验证重点

Dockerfile 专属忽略规则继续排除凭据、开发缓存与文档；默认数据卷仍为 `bensz-search_search-data`。Compose 命令从项目根目录运行，使用显式 `-f docs/deploy/compose.yaml`。
