# GHCR 镜像发布与 Compose 拉取实施计划

日期：2026-08-17  
依据：`docs/superpowers/specs/2026-08-17-ghcr-image-publishing-design.md`

## 目标

通过 GitHub Actions 将 Linux AMD64 应用镜像发布到公开的 `ghcr.io/84xiaodu/kmoeshelf`，并让生产 Compose 默认拉取 `latest`，同时允许通过 `KMOE_IMAGE` 固定提交 SHA 标签。

## 任务 1：增加 GHCR 发布工作流

文件：

- `.github/workflows/publish-image.yml`

步骤：

1. 对 `main` 推送和 Pull Request 运行工作流。
2. 设置 `contents: read` 与 `packages: write` 最小权限。
3. 使用官方 Docker Actions 配置 Buildx、GHCR 登录和镜像元数据。
4. Pull Request 只构建；`main` 推送发布 `latest` 与 `sha-<短提交号>`。
5. 为镜像写入源仓库、描述和 MIT 许可证 OCI 标签，使 GHCR Package 与仓库建立关联。
6. 启用 GitHub Actions 构建缓存。

验证：

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/publish-image.yml'))"
git diff --check
```

## 任务 2：切换 Compose 到远端镜像

文件：

- `compose.yaml`

步骤：

1. 删除应用服务的默认 `build: .`。
2. 增加 `image: ${KMOE_IMAGE:-ghcr.io/84xiaodu/kmoeshelf:latest}`。
3. 增加 `pull_policy: always`。
4. 保持端口、环境变量、持久卷、健康检查和停止宽限期不变。

验证：

```bash
KMOE_APP_SECRET_KEY=local-compose-validation-key-000000000000 docker compose config
```

确认解析结果只有预期 `image`，没有 `build`。

## 任务 3：更新部署与开发文档

文件：

- `README.md`
- `docs/operations.md`

步骤：

1. 将普通部署命令改为先 `docker compose pull`，再 `docker compose up -d`。
2. 说明公开 GHCR 镜像无需登录即可拉取。
3. 说明使用 `KMOE_IMAGE=ghcr.io/84xiaodu/kmoeshelf:sha-<提交号>` 固定或回滚版本。
4. 保留显式 `docker build -t kmoeshelf:local .` 的本地开发方式。
5. 将升级流程从本地 `--build` 改为拉取远端镜像。

验证：

```bash
rg -n "up -d --build|ghcr.io/84xiaodu/kmoeshelf|KMOE_IMAGE" README.md docs/operations.md
```

## 任务 4：执行本地发布前验证

步骤：

1. 运行项目规定的完整 Python 测试。
2. 验证 Compose 配置。
3. 本地构建与 GitHub Actions 相同的 Dockerfile，确认镜像可构建。
4. 运行敏感文件扫描与 `git diff --check`。

命令：

```bash
.venv/bin/python -m pytest -q -s
KMOE_APP_SECRET_KEY=local-compose-validation-key-000000000000 docker compose config
docker build -t kmoeshelf:ghcr-candidate .
scripts/check-sensitive-files.sh
git diff --check
```

## 任务 5：提交、推送并验证自动发布

步骤：

1. 将工作流、Compose 和文档作为一个发布配置提交。
2. 推送 `main`，触发 GitHub Actions。
3. 等待发布工作流成功，并记录镜像摘要与 SHA 标签。
4. 将 GHCR Package 可见性设为公开；不得在日志或文档中记录令牌。
5. 从未登录 GHCR 的临时 Docker 配置执行匿名拉取。
6. 执行项目的 `docker compose pull` 并确认其拉取同一摘要。

验证：

```bash
docker --config <empty-temp-dir> pull ghcr.io/84xiaodu/kmoeshelf:latest
KMOE_APP_SECRET_KEY=local-compose-validation-key-000000000000 docker compose pull
docker image inspect ghcr.io/84xiaodu/kmoeshelf:latest
```

若 GitHub 身份、Package 权限或网络阻止发布，保留已验证的本地改动并报告准确的远端阻塞，不尝试输出或绕过凭据。

## 任务 6：更新当前交接记录

文件：

- `docs/handoffs/CURRENT.md`

步骤：

1. 记录 GHCR 工作流、Compose 拉取行为、公开可见性和验证证据。
2. 只记录非敏感工作流编号、提交号、标签和镜像摘要。
3. 若远端发布仍受阻，明确记录待完成操作与阻塞原因。

