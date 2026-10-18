import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .bridge import BridgeError, GateBridge
from .config import Settings
from .models import CommandQueued, GateStatus

INSTRUCTIONS = (
    "GateBridge MCP 控制已配置的一台 ESP32/MG946R 闸门。"
    "仅在用户明确要求开门或关门时调用写入工具。0° 关门，180° 开门。"
    "先阅读 gatebridge://device 和 gatebridge://protocol，使用 gate_get_status 查看可用状态。"
    "queued 只表示原服务端已转发，不得向用户声称闸门已到位。"
    "DELIVERY_UNKNOWN 表示结果不确定，不得自动重试。"
    "初次连接的状态可能是过期缓存，角度报告也不证明机械到位。"
)

PROTOCOL = """# 闸门控制约定

本服务以 role=controller 连接现有舵机 WebSocket 服务。
原服务端和 ESP32 固件保持原样。每个实例固定控制一个设备。

## 操作与回执

- gate_open：发送 cmd=angle、value=180。
- gate_close：发送 cmd=angle、value=0。
- gate_get_status：只读取适配器已收到的状态，不移动舵机，也不主动探测板子。
- 只有原服务端返回 success=true、queued=true、cmd=angle，工具才返回 queued。
- queued 仅证明原服务端的转发调用成功。physical_state_confirmed 始终为 false。

## 状态边界

首次认证后的快照可能是原服务端的历史缓存，stale 始终为 true。
后续广播的有效期由服务配置决定。report_received_at 是接收时间，不是设备采样时间。
reported_position 仅根据有效角度报告推断，不能证明门体、限位或防夹传感器状态。
断线时 device_online 为 null。设备离线回执会使写入工具失败。
不支持主动 status 命令；读取 Resources 不会触发开关动作。

## 并发与失败

本实例串行发送写入命令。原网页、原 Agent 和其他实例仍可能同时控制设备。
协议没有全局互斥和可靠的机械执行回执。
连接自动重建，开关命令永不自动重放。
DELIVERY_UNKNOWN 需要人工或外部传感器核实，不得自动重试，也不得自动执行反向操作。
令牌只从环境读取，不在工具、资源或提示模板中返回。
"""


class ProtectedHTTP:
    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if scope["path"] == "/healthz" and scope["method"] == "GET":
                await JSONResponse({"status": "ok"})(scope, receive, send)
                return
            headers = dict(scope["headers"])
            if self.expected and not secrets.compare_digest(
                headers.get(b"authorization", b""), self.expected
            ):
                await JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_server(settings: Settings, host: str, port: int) -> tuple[FastMCP, GateBridge]:
    bridge = GateBridge(settings)

    allowed_hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    allowed_hosts.extend(
        value.strip() for value in os.getenv("GATEBRIDGE_ALLOWED_HOSTS", "").split(",") if value.strip()
    )
    allowed_origins = ["http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*"]
    allowed_origins.extend(
        value.strip() for value in os.getenv("GATEBRIDGE_ALLOWED_ORIGINS", "").split(",") if value.strip()
    )
    mcp = FastMCP(
        "GateBridge MCP",
        instructions=INSTRUCTIONS,
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )
    write_annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )

    async def operate(operation: Literal["open", "close"]) -> CommandQueued:
        try:
            return await bridge.command(operation)
        except BridgeError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(title="打开闸门", annotations=write_annotations)
    async def gate_open() -> CommandQueued:
        """向已配置的 ESP32 闸门下发 180° 开门命令。无参数，仅在用户明确要求开门时调用。

        会移动真实舵机，可能影响人员或物品。与原网页和原 Agent 共享控制权。
        返回 queued 只确认原服务端已转发，physical_state_confirmed 始终为 false。
        不能声称门已打开。DEVICE_OFFLINE 表示原服务端报告设备离线。
        DELIVERY_UNKNOWN 表示命令可能已发送，禁止自动重试或自动关门补偿。
        """
        return await operate("open")

    @mcp.tool(title="关闭闸门", annotations=write_annotations)
    async def gate_close() -> CommandQueued:
        """向已配置的 ESP32 闸门下发 0° 关门命令。无参数，仅在用户明确要求关门时调用。

        会移动真实舵机，调用前应由用户或业务系统确认通道可以关闭。
        本服务无法确认防夹、限位或人员通过状态。与原网页和原 Agent 共享控制权。
        queued 只确认原服务端已转发，不能声称门已关闭。
        DELIVERY_UNKNOWN 表示结果不确定，禁止自动重试或自动开门补偿。
        """
        return await operate("close")

    @mcp.tool(
        title="读取闸门最近状态",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    def gate_get_status() -> GateStatus:
        """读取本适配器最近接收到的连接、在线和角度报告。无参数，不发送舵机命令。

        上游离线时仍可调用。bridge_connected 只表示适配器已通过 controller 认证。
        device_online=null 表示未知；初始快照可能来自原服务端过期缓存。
        stale=true 时 reported_position 为 unknown。reported_angle 仅是原服务端报告值。
        report_received_at 是本服务接收时间，不能视为设备采样时间。
        physical_state_confirmed 始终为 false；本工具不能确认机械到位或防夹状态。
        """
        return bridge.status()

    @mcp.resource(
        "gatebridge://device",
        name="gate_device",
        title="闸门设备与控制范围",
        mime_type="application/json",
        description="固定设备 ID、开关角度、允许工具和控制能力边界。只读，不含认证令牌，不移动闸门。",
    )
    def device_resource() -> str:
        return json.dumps(
            {
                "name": "GateBridge MCP",
                "device_id": settings.device_id,
                "actuator": "MG946R",
                "open_angle": 180,
                "close_angle": 0,
                "tools": ["gate_open", "gate_close", "gate_get_status"],
                "status_max_age_seconds": settings.status_max_age,
                "physical_confirmation_available": False,
                "exclusive_control": False,
                "command_replay": False,
            },
            ensure_ascii=False,
        )

    @mcp.resource(
        "gatebridge://status",
        name="gate_status",
        title="闸门最近状态",
        mime_type="application/json",
        description="与 gate_get_status 相同的只读快照，包含状态来源、有效期及未知值；读取不会发送控制命令。",
    )
    def status_resource() -> str:
        return bridge.status().model_dump_json()

    @mcp.resource(
        "gatebridge://protocol",
        name="gate_protocol",
        title="闸门控制协议与结果解释",
        mime_type="text/markdown",
        description="说明角度映射、queued 回执、历史缓存、并发限制及不确定结果的处理；操作前应阅读。",
    )
    def protocol_resource() -> str:
        return PROTOCOL

    @mcp.prompt(
        name="gate_operation",
        title="闸门操作指导",
        description="根据用户意图生成操作指导；获取提示本身不会开关闸门。",
    )
    def gate_operation(
        intent: Annotated[
            Literal["open", "close", "status"],
            Field(description="用户意图：open 为开门，close 为关门，status 为只读状态。"),
        ],
    ) -> str:
        """intent 为 open（开门）、close（关门）或 status（只读状态）。"""
        return (
            f"用户请求的闸门操作为 {intent}。先阅读 gatebridge://device 和 gatebridge://protocol，"
            "再调用 gate_get_status。只有用户明确要求动作时，才调用对应的 gate_open 或 gate_close。"
            "说明 queued 仅代表已转发，状态未知时直说未知；DELIVERY_UNKNOWN 时停止，不自动重试。"
        )

    return mcp, bridge


async def serve_stdio(mcp: FastMCP, bridge: GateBridge) -> None:
    bridge.start()
    try:
        await mcp.run_stdio_async()
    finally:
        await bridge.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="将现有 ESP32 闸门 WebSocket 接入 MCP")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.getenv("GATEBRIDGE_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("GATEBRIDGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=os.getenv("GATEBRIDGE_PORT", "8000"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env()
        if not 1 <= args.port <= 65535:
            raise ValueError("HTTP 端口必须在 1 到 65535 之间")
        if (
            args.transport == "streamable-http"
            and args.host not in {"127.0.0.1", "::1", "localhost"}
            and not settings.api_token
        ):
            raise ValueError("监听外部 HTTP 地址时必须设置 GATEBRIDGE_API_TOKEN")
    except ValueError as exc:
        parser.error(str(exc))
    mcp, bridge = create_server(settings, args.host, args.port)
    if args.transport == "stdio":
        asyncio.run(serve_stdio(mcp, bridge))
    else:
        app = mcp.streamable_http_app()

        @asynccontextmanager
        async def http_lifespan(app) -> AsyncIterator[None]:
            bridge.start()
            try:
                async with mcp.session_manager.run():
                    yield None
            finally:
                await bridge.close()

        app.router.lifespan_context = http_lifespan
        uvicorn.run(ProtectedHTTP(app, settings.api_token), host=args.host, port=args.port)
