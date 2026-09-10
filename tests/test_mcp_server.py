from __future__ import annotations

import httpx

from kmoe_subscriptions.mcp.server import (
    Config,
    KmoeshelfClient,
    handle_message,
)


def mock_client(handler) -> KmoeshelfClient:
    return KmoeshelfClient(
        Config(api_url="http://test/api/v1", token="secret-token"),
        transport=httpx.MockTransport(handler),
    )


def call(client: KmoeshelfClient, name: str, arguments: dict, request_id: int = 1):
    return handle_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        client,
    )


def test_initialize_tools_list_ping_and_notifications() -> None:
    client = mock_client(lambda request: httpx.Response(500, request=request))
    try:
        init = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            client,
        )
        assert init["result"]["protocolVersion"] == "2024-11-05"
        assert init["result"]["capabilities"]["tools"] == {"listChanged": False}
        assert init["result"]["serverInfo"]["name"] == "kmoeshelf"

        listed = handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            client,
        )
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert names == {
            "list_subscriptions",
            "get_subscription",
            "create_subscription",
            "update_subscription",
            "delete_subscription",
            "check_subscription",
        }

        ping = handle_message(
            {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}}, client
        )
        assert ping["result"] == {}

        unknown = handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "nope", "params": {}}, client
        )
        assert unknown["error"]["code"] == -32601

        notification = handle_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, client
        )
        assert notification is None
    finally:
        client.close()


def test_tools_forward_to_external_api() -> None:
    calls: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (request.method, request.url.path, request.headers.get("authorization"))
        )
        if request.method == "GET" and request.url.path == "/api/v1/subscriptions":
            return httpx.Response(200, request=request, json=[])
        if request.method == "POST" and request.url.path == "/api/v1/subscriptions":
            return httpx.Response(
                201,
                request=request,
                json={"id": 1, "remote_id": "50076", "title": "Comic"},
            )
        if (
            request.method == "PATCH"
            and request.url.path == "/api/v1/subscriptions/1"
        ):
            return httpx.Response(
                200,
                request=request,
                json={"id": 1, "download_format": "mobi"},
            )
        if (
            request.method == "DELETE"
            and request.url.path == "/api/v1/subscriptions/1"
        ):
            return httpx.Response(204, request=request)
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/subscriptions/1/check"
        ):
            return httpx.Response(
                202,
                request=request,
                json={"batch_id": 7, "queued_count": 1, "created": True},
            )
        return httpx.Response(404, request=request, json={"detail": "not found"})

    client = mock_client(handler)
    try:
        listed = call(client, "list_subscriptions", {})
        assert listed["result"]["content"][0]["text"] == "[]"

        created = call(
            client,
            "create_subscription",
            {
                "remote_id": "50076",
                "content_types": ["volume"],
                "download_format": "epub",
                "initialization_strategy": "backfill",
            },
        )
        assert '"remote_id": "50076"' in created["result"]["content"][0]["text"]

        edited = call(
            client,
            "update_subscription",
            {"subscription_id": 1, "download_format": "mobi"},
        )
        assert '"download_format": "mobi"' in edited["result"]["content"][0]["text"]

        checked = call(client, "check_subscription", {"subscription_id": 1})
        assert '"batch_id": 7' in checked["result"]["content"][0]["text"]

        deleted = call(
            client,
            "delete_subscription",
            {"subscription_id": 1, "cancel_pending": True},
        )
        assert deleted["result"]["content"][0]["text"] == '{\n  "ok": true\n}'

        missing = call(client, "get_subscription", {"subscription_id": 999})
        assert missing["result"]["isError"] is True
        assert "HTTP 404" in missing["result"]["content"][0]["text"]

        unknown_tool = call(client, "bogus", {})
        assert unknown_tool["result"]["isError"] is True
    finally:
        client.close()

    assert ("GET", "/api/v1/subscriptions", "Bearer secret-token") in calls
    assert ("POST", "/api/v1/subscriptions", "Bearer secret-token") in calls
    assert ("PATCH", "/api/v1/subscriptions/1", "Bearer secret-token") in calls
    assert ("DELETE", "/api/v1/subscriptions/1", "Bearer secret-token") in calls
    assert ("POST", "/api/v1/subscriptions/1/check", "Bearer secret-token") in calls


def test_delete_sends_cancel_pending_false_by_default() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = request.url.params["cancel_pending"]
        return httpx.Response(204, request=request)

    client = mock_client(handler)
    try:
        call(client, "delete_subscription", {"subscription_id": 3})
    finally:
        client.close()
    assert seen["params"] == "false"
