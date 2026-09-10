# Kmoeshelf MCP 服务器

本项目附带一个标准的 [Model Context Protocol](https://modelcontextprotocol.io)（MCP）服务器，让 AI 智能体（Claude、Cursor 等）可以通过自然语言调用 Kmoeshelf 的外部订阅 API，完成订阅的增、删、改、查和立即检查。

服务器是 Kmoeshelf 服务的轻量客户端，通过 stdio 与 MCP 客户端通信，只依赖项目已安装的 `httpx`，不引入额外运行时依赖。

## 配置

服务器通过环境变量配置：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `KMOESHELF_API_URL` | 否 | Kmoeshelf 外部 API 根地址，默认 `http://localhost:8000/api/v1` |
| `KMOESHELF_API_TOKEN` | 是 | 与 Kmoeshelf 服务 `.env` 中 `KMOE_API_TOKEN` 相同的令牌 |

注意：MCP 服务器运行在「调用方」一侧，它是 Kmoeshelf 的客户端，所以这里用的是 `KMOESHELF_API_TOKEN`（指向远端服务的令牌），而不是服务端的 `KMOE_API_TOKEN` 配置名。

## 暴露的工具

| 工具 | 对应接口 | 说明 |
| --- | --- | --- |
| `list_subscriptions` | `GET /subscriptions` | 列出全部订阅及状态、下载任务计数 |
| `get_subscription` | `GET /subscriptions/{id}` | 查询单个订阅状态 |
| `create_subscription` | `POST /subscriptions` | 新增订阅 |
| `update_subscription` | `PATCH /subscriptions/{id}` | 编辑订阅策略 |
| `delete_subscription` | `DELETE /subscriptions/{id}` | 删除订阅（可选取消等待任务） |
| `check_subscription` | `POST /subscriptions/{id}/check` | 立即触发追新检查 |

## 运行方式

安装后可直接运行：

```bash
KMOESHELF_API_TOKEN=... KMOESHELF_API_URL=http://localhost:8000/api/v1 \
  python -m kmoe_subscriptions.mcp
```

`pyproject.toml` 中也注册了控制台入口 `kmoeshelf-mcp`。

## 接入 Claude Desktop

在 `claude_desktop_config.json` 中加入：

```json
{
  "mcpServers": {
    "kmoeshelf": {
      "command": "/home/zx/kmoeshelf/.venv/bin/python",
      "args": ["-m", "kmoe_subscriptions.mcp"],
      "env": {
        "KMOESHELF_API_URL": "http://localhost:8000/api/v1",
        "KMOESHELF_API_TOKEN": "your-token-here"
      }
    }
  }
}
```

重启 Claude Desktop 后即可用自然语言操作订阅，例如「帮我把漫画 50076 订阅为 EPUB，补齐已有内容」。

## 接入 Cursor

在 Cursor 的 MCP 配置中添加同名条目（`command` / `args` / `env` 同上）。Cursor 会通过 stdio 启动本服务器并暴露这 6 个工具。

## 关于 pi

pi 有意不内建 MCP（见 pi 文档），但支持两种用法：

1. **作为外部命令**：在 pi 会话中用 Bash 直接调用 `python -m kmoe_subscriptions.mcp` 或其他 MCP 客户端。
2. **包成 pi 扩展**：参照 pi 的扩展文档，用本模块的 `TOOLS` 和 `handle_message` 把 6 个工具注册为 pi 的自定义工具。

## 安全

- 令牌只通过环境变量传入，不写进任何文件；日志只输出到 stderr，不污染 stdio 的 JSON-RPC 流。
- 服务器只暴露订阅增删改查与立即检查，不暴露搜索、下载地址、Cookie 或签名 URL。
- 建议只允许受信任的调用方访问该 MCP 服务器与 Kmoeshelf 服务的 `/api/v1` 端口。
