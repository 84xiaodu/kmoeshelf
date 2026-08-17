# GHCR 镜像发布与 Compose 拉取设计

日期：2026-08-17  
状态：已确认设计，等待书面规格复核

## 1. 目标

将 KmoeShelf 应用镜像自动发布到公开的 GitHub Container Registry，并让生产用 Docker Compose 默认从远端镜像仓库拉取，而不是在部署主机上构建。

镜像仓库固定为 `ghcr.io/84xiaodu/kmoeshelf`。首次发布完成后，任何无需登录 GHCR 的 Docker 客户端都应能拉取该镜像。

## 2. 发布触发与标签

新增独立的 GitHub Actions 镜像发布工作流：

- `main` 分支发生推送时构建并发布 `latest`。
- 每次发布同时生成不可变的 `sha-<短提交号>` 标签，用于定位和回滚具体构建。
- Git 标签推送时保留后续生成版本标签的扩展能力；首个实现只承诺 `latest` 与提交 SHA 标签。
- Pull Request 只验证构建，不向 GHCR 推送镜像。

工作流使用 GitHub 提供的 `GITHUB_TOKEN` 登录 GHCR，并仅授予发布所需的 `contents: read` 与 `packages: write` 权限。构建上下文不包含 `.env`、数据库、下载文件或其他运行时敏感数据。

## 3. Compose 部署行为

`compose.yaml` 中的应用服务不再包含默认 `build: .`，而改为：

```yaml
image: ${KMOE_IMAGE:-ghcr.io/84xiaodu/kmoeshelf:latest}
pull_policy: always
```

因此普通部署执行 `docker compose up -d` 时会检查并拉取远端 `latest`。需要固定版本或回滚时，部署者可通过 `KMOE_IMAGE` 指定 `sha-<短提交号>` 标签，无需修改 Compose 文件。

本地开发仍可使用显式 `docker build` 命令构建镜像；生产 Compose 不承担本地构建职责。

## 4. 首次发布与公开访问

首次镜像发布采用自动工作流完成。镜像包创建后，将其可见性设置为公开。公开状态通过未携带 GHCR 登录凭据的拉取请求验证，不能只依据 GitHub 页面设置或已登录客户端的成功结果判断。

如果当前 GitHub 身份无权创建 Package、修改可见性或触发工作流，实施过程应停止在明确的权限错误处，不记录或输出访问令牌。凭据只通过 GitHub CLI、Docker credential helper 或 GitHub Actions Secret 存储处理。

## 5. 文档与运维

README 和运维文档更新为远端镜像部署流程：

1. 配置现有应用环境变量与持久卷路径。
2. 执行 `docker compose pull`。
3. 执行 `docker compose up -d`。
4. 使用健康检查和日志确认启动成功。

文档同时说明 `KMOE_IMAGE` 固定 SHA 标签与回滚方式，并保留开发者本地构建命令。

## 6. 验证

实施完成需要满足以下检查：

- `.venv/bin/python -m pytest -q -s` 通过。
- `docker compose config` 输出有效配置，应用服务解析为预期 GHCR 镜像且没有默认 `build`。
- GitHub Actions 发布工作流成功构建并推送 `latest` 和对应 SHA 标签。
- GHCR Package 可见性为公开。
- 匿名客户端可执行 `docker pull ghcr.io/84xiaodu/kmoeshelf:latest`。
- 当前项目可执行 `docker compose pull`，且解析到的镜像摘要与 GHCR 中已发布镜像一致。

验证不删除或重建现有 `data`、下载目录和运行中容器；若需要实际重启服务，应保留原有持久卷挂载并先检查当前运行状态。

## 7. 范围外事项

- 不发布多架构镜像；首版沿用 GitHub Actions Linux AMD64 构建环境。
- 不引入 Docker Hub 或第二个镜像仓库。
- 不添加镜像签名、SBOM、漏洞阻断或自动版本发布系统。
- 不改变应用代码、数据库迁移、Kmoe 协议或持久卷布局。

