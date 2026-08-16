# Kmoe 自动订阅服务

面向 NAS/Linux 的 Kmoe 漫画订阅与自动下载 Web 服务。当前已完成应用基础、数据库迁移、管理员认证、健康检查和 Docker 入口。

## Docker 启动

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 将输出写入 .env 的 KMOE_APP_SECRET_KEY
docker compose up --build
```

服务默认监听 <http://localhost:8000>，API 文档位于 <http://localhost:8000/docs>。

## 本地开发

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
export KMOE_APP_SECRET_KEY=replace-with-at-least-32-random-characters
export KMOE_DATABASE_URL=sqlite+aiosqlite:///./data/app.db
export KMOE_DOWNLOAD_DIR=./downloads
.venv/bin/uvicorn kmoe_subscriptions.main:create_app --factory --reload
```

测试：

```bash
.venv/bin/python -m pytest -q -s
```

完整设计与实施步骤见：

- `docs/superpowers/specs/2026-08-16-kmoe-subscription-service-design.md`
- `docs/superpowers/plans/2026-08-16-kmoe-subscription-service-implementation.md`
