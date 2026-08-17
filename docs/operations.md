# Kmoe 自动订阅服务运维手册

本文面向 NAS 与 Linux 主机上的单机 Docker Compose 部署。首版设计为局域网内单管理员使用；如需跨公网访问，必须在前方部署 HTTPS 反向代理并增加网络访问控制。

## 1. 部署前准备

- Docker Engine 24 或更新版本，以及 Docker Compose v2。
- 至少 1 GiB 可用内存；下载目录按漫画库规模预留空间。
- 主机上的 `data/` 与 `downloads/` 必须位于可靠持久磁盘，不能使用容器临时层。
- 容器内应用用户 UID 为 `10001`。NAS 若启用严格权限，需要让该 UID 对两个目录可读写。

首次部署：

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把生成值写入 `.env` 的 `KMOE_APP_SECRET_KEY`，然后执行：

```bash
mkdir -p data downloads
docker compose pull
docker compose up -d
docker compose ps
```

Compose 默认拉取公开镜像 `ghcr.io/84xiaodu/kmoeshelf:latest`，无需登录 GHCR。浏览器打开 `http://<主机地址>:8000`，先创建管理员，再到“设置”登录 Kmoe。不要把 `.env` 提交到 Git 或发送给他人。

## 2. 数据与密钥

| 主机路径 | 容器路径 | 内容 |
| --- | --- | --- |
| `./data/app.db` | `/data/app.db` | 管理员、会话、加密 Kmoe Cookie、订阅和任务 |
| `./data/backups/` | `/data/backups/` | 版本升级前自动生成的 SQLite 备份 |
| `${KMOE_STORAGE_HOST_ROOT:-./downloads}` | `/storage/` | EPUB、MOBI、下载中的 `.part` 文件与 Web 可选子目录 |

`KMOE_APP_SECRET_KEY` 用于派生会话哈希和 Kmoe Cookie 加密密钥。丢失或更换它会使现有管理会话失效，并使已保存的 Kmoe 会话无法解密；恢复部署时必须同时恢复原密钥。

`KMOE_STORAGE_HOST_ROOT` 只在宿主机部署时设置一次。例如 Linux/NAS 可填写 `/volume1/media/manga`，Docker Desktop for Windows 可填写 `D:/Media/Manga`。应用只看到容器内固定的 `/storage`，不能从 Web 访问该挂载点之外的宿主机路径。

在 Web“设置 → 下载根目录”中选择的是 `/storage` 下的相对目录。切换前会显示受管文件数量与容量；确认后，系统暂停领取新下载，等待运行中的下载结束，复制并校验已完成文件，原子切换数据库路径，再清理旧的受管文件。迁移失败时原目录保持有效；若失败发生在清理阶段，新目录保持有效，可在同一页面重试。不要在迁移过程中手工移动这些文件。

自动备份只在数据库迁移版本落后于应用版本时生成。备份先写入隐藏临时文件，经 `PRAGMA quick_check` 验证后原子改名；备份失败会阻止迁移和应用启动。系统不会自动删除旧备份，管理员应按存储策略定期归档或清理。

## 3. 日常操作

查看状态和日志：

```bash
docker compose ps
docker compose logs --tail=200 app
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

`live` 只表示进程可响应；`ready` 还会验证数据库可访问且下载目录可写。Kmoe 暂时不可用不会让容器失去就绪状态。

优雅重启：

```bash
docker compose restart kmoeshelf
```

停止宽限期为 30 秒。工作器停止领取新任务；遗留运行任务会在下次启动时恢复为等待状态，并从可信 `.part` 文件续传。

## 4. 升级

升级前仍建议做一次完整离线备份，即使应用也会在检测到迁移时备份数据库：

```bash
docker compose stop kmoeshelf
tar -czf "kmoe-backup-$(date +%Y%m%d-%H%M%S).tar.gz" data downloads .env
docker compose pull
docker compose up -d
docker compose logs --tail=200 app
```

升级后检查 `/health/ready`、管理界面、订阅数量与最近任务。若新版本包含迁移，`data/backups/` 中应出现 `app-before-<UTC时间>.db`。

默认的 `latest` 会跟随 `main` 最新发布。需要固定版本或回滚时，在 `.env` 设置已验证的提交标签：

```dotenv
KMOE_IMAGE=ghcr.io/84xiaodu/kmoeshelf:sha-1a2b3c4
```

然后执行 `docker compose pull && docker compose up -d`。恢复跟随最新版时删除 `KMOE_IMAGE`，再次拉取并启动。提交 SHA 标签不可变，适合把应用镜像与数据库备份对应起来。

不要在容器运行期间直接复制 `app.db` 作为唯一备份；SQLite WAL 状态可能让单文件副本不一致。应停止容器，或使用应用自动生成的 SQLite 备份。

## 5. 恢复

1. 停止服务：`docker compose stop kmoeshelf`。
2. 先把当前 `data/` 和 `downloads/` 改名或另行归档，不要直接覆盖唯一副本。
3. 恢复 `app.db`、下载目录与创建该数据库时使用的 `.env`。
4. 确认目录可由 UID `10001` 写入。
5. 执行 `docker compose up -d` 并检查日志与 `/health/ready`。

只回滚数据库而不回滚下载目录可能使已完成任务指向不存在的文件；只回滚下载目录而不回滚数据库则可能留下数据库不知道的文件。灾难恢复应把两者视为同一备份集。

## 6. HTTPS 反向代理

局域网中也建议启用 HTTPS，特别是共享 Wi-Fi 或跨 VLAN 使用时。启用反向代理后在 `.env` 设置：

```dotenv
KMOE_COOKIE_SECURE=true
```

Caddy 示例：

```caddyfile
kmoe.home.example {
    reverse_proxy 127.0.0.1:8000
}
```

Nginx 必须关闭 SSE 缓冲并保留长连接：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 1h;
}
```

不要直接把 8000 端口映射到公网。建议同时使用防火墙、VPN 或反向代理访问控制。

## 7. 常见故障

### 容器反复退出

先看 `docker compose logs kmoeshelf`。常见原因包括密钥缺失/过短、`data/` 无写权限、迁移前备份失败或下载目录不可写。

### Kmoe 显示会话过期

在“设置”中重新输入 Kmoe 邮箱与密码。服务不会保存 Kmoe 密码，因此不会自动重新登录。重新登录后可在下载任务页重试认证失败任务。

### 下载失败或一直等待

- `quota_exhausted`：账号配额不足，不会自动重试。
- `auth_expired`：重新登录 Kmoe 后手动重试。
- `disk_full`：释放空间，并检查宿主机存储挂载所在文件系统。
- `storage_not_writable`：检查 `KMOE_STORAGE_HOST_ROOT` 的 UID `10001` 写权限，或在 Web 中选择可写子目录。
- `file_conflict`：最终路径存在不一致文件；先人工核对，不要直接删除数据库记录。
- `download_forbidden` / `auth_expired`：在“设置”重新登录 Kmoe 后重试。
- `download_url_expired`：临时地址已过期，点击重试会重新获取地址。
- `connect_timeout` / `download_server_error` / `network_error` / `mirror_unavailable`：系统按有界指数退避自动重试，也可稍后手动重试。

### 升级后无法启动

不要反复删除数据库。保留日志、当前 `app.db` 和最近的 `data/backups/app-before-*.db`。若确认要回滚，停止容器后同时回滚应用镜像与数据库备份。


### GHCR 镜像拉取失败

公开镜像不需要 `docker login`。先确认镜像名为 `ghcr.io/84xiaodu/kmoeshelf`，再运行 `docker compose pull` 查看具体错误。若固定了 `KMOE_IMAGE`，确认对应 `sha-<提交号>` 标签已经由发布工作流生成；删除该变量可恢复使用 `latest`。

## 8. 安全检查

- 定期更新基础镜像与 Python/Node 依赖。
- `.env` 权限建议设为仅部署用户可读。
- 日志、问题报告和截图中不得包含 Cookie、CSRF 令牌、密码或真实签名下载地址。
- 管理员密码至少 12 个字符；修改密码后，除当前浏览器外的其他管理会话会失效。
- 下载目录只应由应用与媒体库读取端访问，避免其他进程在下载期间修改 `.part` 文件。
