# Kmoe 搜索路由修复实施计划

日期：2026-08-17  
依据：`docs/superpowers/specs/2026-08-17-kmoe-search-routing-fix-design.md`

## 目标

让 `/api/kmoe/search` 动态跟随 Kmoe 当前可信搜索表单，返回站点自身的模糊匹配结果，不再把忽略关键词的全量书库页作为搜索结果。

## 任务 1：建立搜索表单解析契约

文件：

- `src/kmoe_subscriptions/kmoe/parser.py`
- `tests/fixtures/kmoe/search_form_current.html`
- `tests/test_kmoe_parser.py`

步骤：

1. 增加不可变的搜索目标值对象，字段限于可信主机、`/list.php` 路径和 `s` 参数。
2. 使用 `HTMLParser` 读取 form 与 input，不使用宽松正则执行 URL 发现。
3. 将相对 action 按当前来源规范化；验证 HTTPS、无凭据、无查询/片段、白名单主机、GET 方法和严格路径。
4. 接受重复但相同的可信表单，拒绝缺失或互相冲突的目标。
5. 添加当前表单、HTTP、外部主机、错误路径、POST、缺少字段和冲突目标测试。

验收：

```bash
.venv/bin/python -m pytest tests/test_kmoe_parser.py -q -s
```

## 任务 2：安全切换搜索镜像与 Cookie 域

文件：

- `src/kmoe_subscriptions/kmoe/client.py`
- `tests/test_kmoe_client.py`

步骤：

1. 增加只允许切换到客户端初始化镜像集合内主机的方法。
2. 切换时复制当前最小 Cookie 名值集合并重新限定到目标主机。
3. 拒绝集合之外的目标，且不改变活动镜像或 Cookie jar。
4. 测试可信切换会向新主机发送 Cookie，不可信切换被拒绝。

验收：

```bash
.venv/bin/python -m pytest tests/test_kmoe_client.py -q -s
```

## 任务 3：改造搜索编排和空结果规则

文件：

- `src/kmoe_subscriptions/kmoe/catalog.py`
- `src/kmoe_subscriptions/kmoe/parser.py`
- `tests/fixtures/kmoe/search_empty_zero_pages.html`
- `tests/test_kmoe_parser.py`
- `tests/test_kmoe_api.py`

步骤：

1. 从活动镜像首页发现当前搜索目标。
2. 安全切换到目标镜像后，请求 `/list.php`，参数为 `s` 与页码 `page`。
3. 结果请求设置 `allow_failover=False`，禁止把目标专属路径跨镜像重放。
4. 删除运行时对旧 `/l/{keyword}...` 路径的依赖。
5. 仅将第一页、零条结果、远端总页数零的组合规范化为第 `1/1` 页。
6. 更新 API 模拟服务，断言发现请求、搜索目标主机、Cookie、关键词和页码。
7. 测试随机不存在关键词为空，异常零页仍报 `site_changed`。

验收：

```bash
.venv/bin/python -m pytest tests/test_kmoe_parser.py tests/test_kmoe_client.py tests/test_kmoe_api.py -q -s
```

## 任务 4：全量、真实站点与部署验证

步骤：

1. 运行完整 Python 测试、前端生产构建和 Chromium 流程。
2. 使用已保存会话只读搜索一个已知漫画名与一个随机不存在字符串，只输出数量和 ID 摘要。
3. 确认两次结果不再相同，随机字符串返回零条。
4. 重建 Compose 服务并确认健康检查通过。
5. 通过运行中的 Web API 或浏览器复查搜索与分页。
6. 更新 `docs/handoffs/CURRENT.md` 和发布验收记录。

验收：

```bash
.venv/bin/python -m pytest -q -s
npm --prefix frontend run build
npm --prefix frontend test
docker compose up -d --build
docker compose ps
```

## 提交边界

计划文档独立提交；适配器、Fixtures、测试和交付文档作为一个修复提交。不得提交真实页面、Cookie、凭据、签名 URL 或数据库文件。
