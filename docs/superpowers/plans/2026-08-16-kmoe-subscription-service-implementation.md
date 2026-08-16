# Kmoe 自动订阅服务实施计划

日期：2026-08-16  
依据：`docs/superpowers/specs/2026-08-16-kmoe-subscription-service-design.md`

## 实施原则

- 每个阶段交付一个可运行、可测试的纵向切片。
- 站点协议只存在于 `kmoe` 适配层；API、调度和下载器只使用标准化模型。
- SQLite 是任务状态的唯一事实来源；进程内队列只负责唤醒。
- 不在首版引入 Redis、Celery、WebSocket、组件库或额外微服务。
- 安全、数据完整性和 trust boundary 校验不因最小实现而省略。

## 阶段 1：应用基础与管理员认证

目标：Docker 或本地命令可启动应用；数据库自动迁移；管理员可完成首次初始化、登录、查询当前会话和退出。

文件：

- `pyproject.toml`
- `src/kmoe_subscriptions/config.py`
- `src/kmoe_subscriptions/db.py`
- `src/kmoe_subscriptions/models.py`
- `src/kmoe_subscriptions/security.py`
- `src/kmoe_subscriptions/main.py`
- `src/kmoe_subscriptions/api/auth.py`
- `alembic.ini` 与 `migrations/`
- `tests/test_auth.py`
- `.env.example`
- `Dockerfile`
- `compose.yaml`

任务：

1. 定义环境配置并在缺少安全密钥时拒绝启动。
2. 建立 SQLAlchemy 异步 SQLite 会话和 Alembic 初始迁移。
3. 建立唯一管理员模型，使用 Argon2id 保存密码哈希。
4. 实现一次性初始化、登录、当前用户与退出 API。
5. 使用 HttpOnly、SameSite Cookie；为状态变更请求加入同源/CSRF 校验。
6. 实现 `/health/live` 与 `/health/ready`。
7. 添加 API 测试，覆盖初始化竞争、错误密码、有效会话和退出。
8. 构建 Docker 镜像并验证持久卷重启。

验收命令：

```bash
python -m pytest tests/test_auth.py
docker compose config
docker compose up --build
```

## 阶段 2：Kmoe 登录、搜索与详情适配层

目标：管理员可在 API 中登录 Kmoe、搜索漫画并查看标准化详情。

文件：

- `src/kmoe_subscriptions/kmoe/client.py`
- `src/kmoe_subscriptions/kmoe/parser.py`
- `src/kmoe_subscriptions/kmoe/schemas.py`
- `src/kmoe_subscriptions/kmoe/errors.py`
- `src/kmoe_subscriptions/api/kmoe.py`
- `tests/fixtures/kmoe/`
- `tests/test_kmoe_parser.py`
- `tests/test_kmoe_api.py`

任务：

1. 实现带请求节流、重试和镜像故障转移的 HTTPX 客户端。
2. 使用去敏 HTML Fixture 实现登录、搜索和详情解析契约。
3. 将卷、番外和连载话标准化为稳定内容类型与远端 ID。
4. 使用应用密钥认证加密 Kmoe Cookie，密码不落盘。
5. 将认证失效、配额不足、镜像失败和站点结构变化映射为结构化错误。
6. 使用本地伪服务测试重试与镜像切换，不依赖真实站点执行 CI。

验收命令：

```bash
python -m pytest tests/test_kmoe_parser.py tests/test_kmoe_api.py
```

## 阶段 3：订阅、快照与追新调度

目标：可创建两种初始化策略的订阅，并由调度器幂等发现新增内容。

文件：

- `src/kmoe_subscriptions/models.py`
- `src/kmoe_subscriptions/services/subscriptions.py`
- `src/kmoe_subscriptions/services/scheduler.py`
- `src/kmoe_subscriptions/api/subscriptions.py`
- `migrations/versions/*_subscriptions.py`
- `tests/test_subscriptions.py`
- `tests/test_scheduler.py`

任务：

1. 增加 Comic、Subscription、RemoteItem 和 ActivityEvent。
2. 实现内容类型与格式校验。
3. 在单事务内完成 `backfill` 或 `future_only` 初始化。
4. 以远端 ID 和类型比较快照；解析失败时保留旧基线。
5. 使用数据库唯一约束保证任务创建幂等。
6. APScheduler 只创建检查批次，工作器执行实际检查。
7. 实现全部检查、单订阅检查、启停与编辑 API。

验收命令：

```bash
python -m pytest tests/test_subscriptions.py tests/test_scheduler.py
```

## 阶段 4：下载工作器与文件完整性

目标：新增内容可自动下载，支持进度、取消、重试和重启恢复。

文件：

- `src/kmoe_subscriptions/services/downloads.py`
- `src/kmoe_subscriptions/storage.py`
- `src/kmoe_subscriptions/api/downloads.py`
- `migrations/versions/*_downloads.py`
- `tests/test_downloads.py`
- `tests/test_storage.py`

任务：

1. 建立持久化 DownloadTask 状态机和原子领取。
2. 下载到 `.part`，校验后原子改名，最终落盘前不标记完成。
3. 检测 Range 支持；支持则续传，否则安全重下。
4. 对网络类错误执行带抖动指数退避；认证、配额和磁盘错误快速失败。
5. 实现取消、手动重试和启动恢复。
6. 实现安全目录与文件命名，保证路径留在下载根目录。
7. 提供 SSE 任务事件流，并限制数据库与前端更新频率。

验收命令：

```bash
python -m pytest tests/test_downloads.py tests/test_storage.py
```

## 阶段 5：React 管理界面

目标：用户不依赖命令行即可完成全部首版流程。

文件：

- `frontend/package.json`
- `frontend/src/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/pages/Setup.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Search.tsx`
- `frontend/src/pages/Subscriptions.tsx`
- `frontend/src/pages/Downloads.tsx`
- `frontend/src/pages/Settings.tsx`
- `frontend/tests/app.spec.ts`

任务：

1. 使用浏览器原生 Fetch、EventSource 和表单能力，不增加状态管理或组件库。
2. 实现初始化、管理员登录和 Kmoe 登录。
3. 实现搜索、详情和订阅表单。
4. 实现仪表盘、订阅列表、任务列表、取消和重试。
5. 实现设置页和结构化错误展示。
6. 添加键盘操作、标签、焦点状态和移动端基本布局。
7. 使用 Playwright 覆盖一条完整主流程。

验收命令：

```bash
npm --prefix frontend test
npm --prefix frontend run build
python -m pytest
```

## 阶段 6：部署、恢复与发布检查

目标：可在 NAS/Linux 上稳定部署、升级、备份和恢复。

文件：

- `Dockerfile`
- `compose.yaml`
- `README.md`
- `docs/operations.md`
- `.github/workflows/ci.yml`

任务：

1. 多阶段构建 React 资源和 Python 应用镜像。
2. 使用非 root 用户、健康检查和停止宽限期。
3. 验证数据库迁移前备份、失败回滚和卷权限。
4. 编写局域网部署、反向代理 HTTPS、备份和恢复说明。
5. CI 执行后端测试、前端构建、Docker 构建和敏感信息扫描。
6. 对照设计文档的 10 个验收场景执行发布检查。

验收命令：

```bash
python -m pytest
npm --prefix frontend run build
docker compose build
docker compose up -d
docker compose ps
```

## 提交边界

每个阶段至少一个独立提交。迁移、模型和对应测试保持在同一提交；不提交 `.env`、SQLite 数据库、下载文件、真实 Kmoe 页面或真实凭证。

