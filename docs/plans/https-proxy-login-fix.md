# HTTPS 反向代理登录修复

## 根因

公网 HTTPS 登录带有同站 Origin，仍返回 Cross-site requests are not allowed。应用在 Docker 内使用 HTTP；Uvicorn 默认只信任回环地址的代理头，当前 Nginx Proxy Manager 地址不在信任列表，导致应用用 HTTP 比较浏览器 HTTPS Origin。当前 HTTPS 部署也未启用 Secure Cookie。

## 实施

- 复现公网同源登录 403，确认代理容器地址和 HTTPS 转发头。
- 添加真实登录接口的代理头测试，覆盖可信代理、非可信代理与跨站拒绝。
- 在服务器私有环境配置 FORWARDED_ALLOW_IPS 为实际代理地址，并启用 BENSZ_SEARCH_COOKIE_SECURE；重建搜索容器，不更改账号或数据库。
- 验证实际 HTTPS 登录、会话、带 CSRF 的退出以及跨站拒绝，记录脱敏证据。
- 同步配置示例、服务器说明、变更记录和 BAC。

## 恢复与维护

修改前备份私有环境配置，恢复后重建搜索容器。代理容器 IP 变化时重新获取其 npm_default 地址并更新信任列表；不使用全局通配信任。
