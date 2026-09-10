from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "kmoeshelf"
SERVER_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class Config:
    api_url: str
    token: str


def load_config() -> Config:
    api_url = os.environ.get(
        "KMOESHELF_API_URL", "http://localhost:8000/api/v1"
    ).rstrip("/")
    token = os.environ.get("KMOESHELF_API_TOKEN", "")
    if not token:
        raise RuntimeError("KMOESHELF_API_TOKEN is required")
    return Config(api_url=api_url, token=token)


class KmoeshelfClient:
    def __init__(
        self,
        config: Config,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=config.api_url,
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=60.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self._client.request(method, path, **kwargs)


def text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def error_result(message: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def call_api(
    client: KmoeshelfClient, method: str, path: str, **kwargs: Any
) -> dict[str, Any]:
    response = client.request(method, path, **kwargs)
    if response.status_code == 204:
        payload: Any = {"ok": True}
    else:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if response.status_code >= 400:
        return error_result(f"HTTP {response.status_code}: {rendered}")
    return text_result(rendered)


def list_subscriptions(
    client: KmoeshelfClient, arguments: dict[str, Any]
) -> dict[str, Any]:
    return call_api(client, "GET", "/subscriptions")


def get_subscription(
    client: KmoeshelfClient, arguments: dict[str, Any]
) -> dict[str, Any]:
    return call_api(client, "GET", f"/subscriptions/{arguments['subscription_id']}")


def create_subscription(
    client: KmoeshelfClient, arguments: dict[str, Any]
) -> dict[str, Any]:
    return call_api(client, "POST", "/subscriptions", json=arguments)


def update_subscription(
    client: KmoeshelfClient, arguments: dict[str, Any]
) -> dict[str, Any]:
    subscription_id = arguments["subscription_id"]
    body = {
        key: value
        for key in ("content_types", "download_format", "initialization_strategy")
        if (value := arguments.get(key)) is not None
    }
    return call_api(
        client, "PATCH", f"/subscriptions/{subscription_id}", json=body
    )


def delete_subscription(
    client: KmoeshelfClient, arguments: dict[str, Any]
) -> dict[str, Any]:
    params = {
        "cancel_pending": "true" if arguments.get("cancel_pending") else "false"
    }
    return call_api(
        client,
        "DELETE",
        f"/subscriptions/{arguments['subscription_id']}",
        params=params,
    )


def check_subscription(
    client: KmoeshelfClient, arguments: dict[str, Any]
) -> dict[str, Any]:
    return call_api(
        client, "POST", f"/subscriptions/{arguments['subscription_id']}/check"
    )


HANDLERS: dict[str, Callable[[KmoeshelfClient, dict[str, Any]], dict[str, Any]]] = {
    "list_subscriptions": list_subscriptions,
    "get_subscription": get_subscription,
    "create_subscription": create_subscription,
    "update_subscription": update_subscription,
    "delete_subscription": delete_subscription,
    "check_subscription": check_subscription,
}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_subscriptions",
        "description": (
            "列出 Kmoeshelf 中全部订阅及其状态，包括启用状态、追踪类型、格式、"
            "上次/下次检查时间、最近错误，以及各状态下载任务计数。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_subscription",
        "description": "按 id 查询单个订阅的当前状态。",
        "inputSchema": {
            "type": "object",
            "properties": {"subscription_id": {"type": "integer"}},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_subscription",
        "description": (
            "订阅一部漫画（remote_id 为 Kmoe 漫画 ID）。content_types 可选 "
            "volume(单行本)/extra(番外)/serial(连载话)；download_format 为 "
            "epub/mobi；initialization_strategy 为 backfill(补齐已有内容)/"
            "future_only(仅从当前基线追新)。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "remote_id": {"type": "string", "pattern": "^[A-Za-z0-9]+$"},
                "content_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["volume", "extra", "serial"]},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "download_format": {"type": "string", "enum": ["epub", "mobi"]},
                "initialization_strategy": {
                    "type": "string",
                    "enum": ["backfill", "future_only"],
                },
            },
            "required": [
                "remote_id",
                "content_types",
                "download_format",
                "initialization_strategy",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_subscription",
        "description": (
            "编辑订阅的内容类型、下载格式或初始化策略；未提供的字段保持不变。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "integer"},
                "content_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["volume", "extra", "serial"]},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "download_format": {"type": "string", "enum": ["epub", "mobi"]},
                "initialization_strategy": {
                    "type": "string",
                    "enum": ["backfill", "future_only"],
                },
            },
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_subscription",
        "description": (
            "删除订阅。cancel_pending 为 true 时同时取消等待中的下载任务，"
            "否则保留它们（已下载的文件永不删除）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "integer"},
                "cancel_pending": {"type": "boolean"},
            },
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_subscription",
        "description": "立即触发一次该订阅的追新检查。",
        "inputSchema": {
            "type": "object",
            "properties": {"subscription_id": {"type": "integer"}},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
]


def handle_message(
    message: dict[str, Any], client: KmoeshelfClient
) -> dict[str, Any] | None:
    """Return a JSON-RPC response envelope, or None for notifications."""
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS},
        }
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            result = error_result(f"Unknown tool: {name}")
        else:
            try:
                result = handler(client, arguments)
            except Exception as exc:  # noqa: BLE001 - surface any handler failure to the agent
                result = error_result(f"{type(exc).__name__}: {exc}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    try:
        config = load_config()
    except RuntimeError as exc:
        print(f"kmoeshelf MCP: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    client = KmoeshelfClient(config)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = handle_message(message, client)
            if response is None:
                continue
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    finally:
        client.close()


if __name__ == "__main__":
    main()
