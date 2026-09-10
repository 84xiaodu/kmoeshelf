# Kmoeshelf

面向 NAS/Linux 的 Kmoe 漫画订阅与自动下载 Web 服务。管理员可在浏览器中登录 Kmoe、搜索漫画、订阅追新、查看实时下载状态，并维护检查与下载设置。

## 功能

- 单管理员初始化、登录、CSRF 防护与管理员改密。
- 加密保存一个 Kmoe 会话；Kmoe 密码不落盘。
- 漫画搜索、详情和单行本/番外/连载话分类。
- `仅追新` 与 `补齐已有内容` 两种订阅策略。
- 默认每 6 小时自动检查，也可全局或单订阅立即检查。
- 持久化下载队列、并发、断点续传、重试、取消和重启恢复。
- 宿主机只挂载一次存储根目录，Web 中可选择其下目录并自动搬迁已完成文件。
- 订阅可随时编辑内容类型、EPUB/MOBI 格式和仅追新/补齐策略，并先预览任务影响。
- SSE 实时下载状态，以及响应式 React 管理界面。
- 可选 Bangumi 推荐增强：开启后会把已订阅漫画标题发送到 Bangumi 公共 API，用匹配标签生成更精准的发现入口。
- SQLite 升级前完整性校验备份与 Docker Compose 部署。

## Docker 启动

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 将输出写入 .env 的 KMOE_APP_SECRET_KEY
docker compose pull
docker compose up -d
docker compose ps
```

Compose 默认从公开镜像 `ghcr.io/84xiaodu/kmoeshelf:latest` 拉取，无需登录 GHCR。服务默认监听 <http://localhost:8000>。首次打开会要求创建管理员，之后在“设置”中登录 Kmoe。

数据保存在 `./data`。漫画文件默认保存在 `./downloads`，也可在 `.env` 用 `KMOE_STORAGE_HOST_ROOT` 指向 NAS 或其他宿主机目录；容器统一挂载为 `/storage`，之后可在 Web“设置”中自由选择其下的相对目录。务必保留 `.env` 中的原密钥；更换密钥会使现有会话和加密 Kmoe Cookie 失效。若希望推荐更精准，可将 `.env` 中 `KMOE_BANGUMI_RECOMMENDATIONS=true`，系统会用已订阅标题查询 Bangumi 公共 API 并把返回标签再映射到 Kmoe 搜索。详细升级、HTTPS、备份和恢复步骤见 [运维手册](docs/operations.md)。

## 外部 API

可选地，在 `.env` 中设置 `KMOE_API_TOKEN`（至少 16 个随机字符）即可开启供脚本、Bot 或其他服务调用的外部接口。所有接口以 `Authorization: Bearer <token>` 认证；未设置令牌时接口返回 403。

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 将输出写入 .env 的 KMOE_API_TOKEN
```

接口（前缀 `/api/v1`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/subscriptions` | 查询全部订阅状况（含各状态下载任务计数） |
| GET | `/api/v1/subscriptions/{id}` | 查询单个订阅状况 |
| POST | `/api/v1/subscriptions` | 新增订阅 |
| PATCH | `/api/v1/subscriptions/{id}` | 编辑订阅（内容类型/格式/初始化策略），返回任务影响预览结果 |
| POST | `/api/v1/subscriptions/{id}/check` | 立即触发一次该订阅的追新检查 |
| DELETE | `/api/v1/subscriptions/{id}?cancel_pending=true` | 删除订阅，并明确是否取消等待中的任务 |

示例（`TOKEN` 为 `.env` 中的值）：

```bash
# 查询全部订阅
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/subscriptions

# 新增订阅（remote_id 为漫画详情页 ID；content_types 可选 volume/extra/serial）
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"remote_id":"50076","content_types":["volume"],"download_format":"epub","initialization_strategy":"backfill"}' \
  http://localhost:8000/api/v1/subscriptions

# 删除订阅并取消等待中的下载任务
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/subscriptions/1?cancel_pending=true'

# 编辑订阅（改为追踪番外与连载话、MOBI 格式）
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content_types":["extra","serial"],"download_format":"mobi","initialization_strategy":"backfill"}' \
  http://localhost:8000/api/v1/subscriptions/1

# 立即检查一次该订阅
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/subscriptions/1/check
```

新增订阅会像 Web 端一样先连接 Kmoe 拉取详情；因此需要先在 Web 端登录过 Kmoe。外部接口只提供订阅增删改查与立即检查，不暴露搜索、下载地址或任何带签名/敏感字段。

若希望让 AI 智能体（Claude、Cursor 等）通过自然语言调用以上接口，项目还附带一个零依赖的 MCP 服务器，见 [MCP 服务器](docs/mcp.md)。

## 本地开发

后端：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
export KMOE_APP_SECRET_KEY=replace-with-at-least-32-random-characters
export KMOE_DATABASE_URL=sqlite+aiosqlite:///./data/app.db
export KMOE_DOWNLOAD_DIR=./downloads
.venv/bin/uvicorn kmoe_subscriptions.main:create_app --factory --reload
```

前端开发服务器会把 `/api` 与 `/health` 代理到 `127.0.0.1:8000`：

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

打开 Vite 显示的地址。生产构建由 Docker 多阶段构建复制到 Python 包，并由 FastAPI 同源提供。

需要验证 Dockerfile 或开发本地镜像时，显式构建而不改变生产 Compose：

```bash
docker build -t kmoeshelf:local .
```

部署时可通过 `KMOE_IMAGE` 固定到不可变的提交标签，例如 `ghcr.io/84xiaodu/kmoeshelf:sha-1a2b3c4`；恢复跟随最新版时删除该变量并重新拉取。

## 测试

```bash
.venv/bin/python -m pytest -q -s
npm --prefix frontend run build
npm --prefix frontend test
KMOE_APP_SECRET_KEY=local-compose-validation-key-000000000000 docker compose config
```

首次运行浏览器测试还需要：

```bash
npx --prefix frontend playwright install --with-deps chromium
```

完整设计、实施步骤和发布验收见：

- [设计规格](docs/superpowers/specs/2026-08-16-kmoe-subscription-service-design.md)
- [实施计划](docs/superpowers/plans/2026-08-16-kmoe-subscription-service-implementation.md)
- [发布验收清单](docs/release-checklist.md)

## 许可证

本项目由 84xiaodu 以 [MIT License](LICENSE) 发布。参考项目及可能采用的第三方材料按各自许可证授权，完整归属与许可文本见 [第三方声明](THIRD_PARTY_NOTICES.md)。

本项目许可证不涵盖 Kmoe 服务、相关商标、漫画内容或用户下载的文件；这些材料仍受各自权利人的条款及适用法律约束。
