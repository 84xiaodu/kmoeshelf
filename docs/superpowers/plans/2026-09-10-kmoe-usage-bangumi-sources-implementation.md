# Kmoe 用量与 Bangumi 订阅源实施计划

日期：2026-09-10
依据：`docs/superpowers/specs/2026-09-10-kmoe-usage-bangumi-sources-design.md`

## 任务 1：Kmoe 用量

- 严格解析 `/my.php` 免费/VIP 额度，不为缺失字段构造默认额度。
- 为 `KmoeCredential` 增加额度快照字段和 Alembic 迁移。
- 登录时更新快照，新增手动刷新 API。
- 在概览与设置页显示剩余额度、已用额度和重置日。
- 覆盖解析、持久化、API、迁移和 UI。

## 任务 2：Bangumi 订阅源

- 增加通用来源与来源条目模型及迁移。
- 扩展 Bangumi 客户端读取指定用户和收藏状态的书籍收藏。
- 新增来源 CRUD、手动同步、条目查询 API 和按周期自动同步的后台定时器。
- 新增独立“订阅源”导航页，支持添加用户名、选择状态、手动同步、编辑同步周期和删除。
- 可选 Access Token 仅从环境变量读取。
- 覆盖客户端、API、迁移和浏览器流程。

## 验收

```bash
.venv/bin/python -m pytest -q -s
npm --prefix frontend run build
npm --prefix frontend test
KMOE_APP_SECRET_KEY=local-compose-validation-key-000000000000 docker compose config
```
