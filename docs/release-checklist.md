# 首版发布验收清单

更新日期：2026-08-17

自动化验收使用去敏 Fixture、本地伪 Kmoe 服务、临时 SQLite、真实文件系统操作和 Chromium。它验证应用契约与失败安全性，但不替代发布管理员使用自己账号执行一次小规模真实站点验收。

## 自动化基线

- [x] Python 完整测试：56 项通过。
- [x] TypeScript/Vite 生产构建通过。
- [x] Chromium 主流程：初始化、Kmoe 登录、搜索、详情和创建订阅通过。
- [x] Chromium 存储目录预检/确认迁移与订阅策略预览/应用流程通过。
- [x] 真实 Kmoe 搜索路由发现通过：已知漫画返回站点模糊匹配，随机字符串返回零条。
- [x] Docker 多阶段镜像构建通过。
- [x] 容器内迁移、`/health/ready` 和 React 首页通过。
- [x] 运行数据与私钥文件扫描通过。
- [x] MIT 项目许可、第三方声明及 Python 包内许可文件通过。

## 十个设计验收场景

| # | 场景 | 自动化证据 | 状态 |
| --- | --- | --- | --- |
| 1 | 新安装创建管理员、登录 Kmoe，重启后会话仍存在 | `test_auth.py`、`test_kmoe_credentials.py`、Playwright 主流程、容器烟雾测试 | 模拟通过；真实账号待发布者确认 |
| 2 | “仅追新”保存基线且不下载旧内容 | `test_subscriptions.py` | 通过 |
| 3 | “补齐已有内容”只为选定类型建任务 | `test_subscriptions.py`、`test_subscription_api.py` | 通过 |
| 4 | 新卷恰好创建一个任务，重复检查不产生副本 | `test_check_scheduler.py`、数据库唯一约束 | 通过 |
| 5 | 异常空响应不清空基线并报告站点错误 | `test_kmoe_parser.py`、`test_kmoe_api.py` | 通过 |
| 6 | 中断后支持 Range 则续传，不支持则安全重下 | `test_download_worker.py`、`test_storage.py` | 通过 |
| 7 | 最终文件落盘前不标记完成 | `test_download_worker.py`、原子无覆盖存储测试 | 通过 |
| 8 | 下载中重启后恢复，不重复生成最终文件 | `test_download_worker.py` | 通过 |
| 9 | Kmoe 会话失效后暂停远端工作，重新登录后可重试 | `test_kmoe_api.py`、下载错误映射与重试 API 测试 | 模拟通过；真实账号待发布者确认 |
| 10 | 密码、Cookie 与签名 URL 不进入数据库明文、API 或事件流 | `test_kmoe_credentials.py`、`test_subscription_api.py`、敏感文件扫描 | 通过 |

## 真实站点发布前检查

使用专门的低风险测试漫画与账号执行，禁止在日志或验收记录中粘贴 Cookie、密码和签名 URL。

- [ ] 登录真实 Kmoe 账号，确认镜像、邮箱和状态正确。
- [x] 搜索已知漫画与随机不存在字符串，确认结果分别为 Kmoe 模糊匹配与空结果。
- [ ] 打开一部漫画，核对三类内容数量与网页一致。
- [ ] 创建一条 `future_only` 订阅，确认没有历史下载任务。
- [ ] 创建或临时调整一条 `backfill` 订阅，只选择一个小文件并完成下载。
- [ ] 暂停/恢复订阅，执行单订阅检查和全局检查。
- [ ] 在下载中重启容器，确认任务恢复与最终文件完整。
- [ ] 重新登录 Kmoe 后重试一条认证失败任务。
- [ ] 在 Web 中切换到挂载根目录下的测试子目录，确认文件自动搬迁且任务路径更新。
- [ ] 检查 `docker compose logs app` 不包含密码、Cookie 或签名地址。
- [ ] 从离线备份在临时目录恢复一次，并核对订阅与完成文件。

## 一键本地检查

依赖已经安装后运行：

```bash
scripts/release-check.sh
```

若本机不运行 Docker，只跳过镜像构建：

```bash
KMOE_SKIP_DOCKER_BUILD=true scripts/release-check.sh
```
