# 服务器 Compose 部署调整

## 需求与范围

调整已授权服务器 `/docker/bensz-search`，使用 `docker-compose.yml`、`expose`、`huangwb8/bensz-search:latest` 和固定容器名。将命名卷迁入项目目录，独立部署 SearXNG，并移除搜索服务对外部 SearXNG 的依赖。两个容器按用户补充要求统一使用已有外部网络 `npm_default`，不创建项目默认网络。

## 实施步骤

- 核查运行容器、挂载、网络和持久化 provider；检查 BAC 主账本。
- 先拉取镜像，将原 Compose、环境文件和数据备份保存在服务器项目内私有目录。
- 停止搜索服务后复制数据，验证文件一致性，修改已有数据库中的 SearXNG 服务地址并保留凭据和用户记录。
- 使用独立 SearXNG 配置和项目内 bind mounts 启动两项服务，校验 Compose、健康状态、真实检索及 API 调用。
- 同步服务器部署模板、说明、变更记录和贡献账本。

## 恢复方式

保留原命名卷和私有部署备份；启动失败时停止新服务并恢复旧 Compose 和环境文件，再用原镜像与原卷启动。禁止使用 `down -v`。
