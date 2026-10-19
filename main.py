import asyncio
from collections.abc import Mapping

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .gatebridge.bridge import BridgeError, GateBridge
from .gatebridge.config import Settings
from .gatebridge.models import GateStatus

HELP = (
    "GateBridge 闸门控制\n"
    "/闸门 开门：发送 180° 开门指令\n"
    "/闸门 关门：发送 0° 关门指令\n"
    "/闸门 状态：读取最近的设备报告\n"
    "/闸门 帮助：查看本说明\n"
    "也可使用 /gate open、/gate close、/gate status。\n"
    "仅限允许的管理员和指定成员。命令已转发不代表闸门已经到位。"
)

ERROR_MESSAGES = {
    "UPSTREAM_UNAVAILABLE": "尚未连接原闸门服务，本次指令未发送，请检查连接地址和网络。",
    "UPSTREAM_AUTH_FAILED": "原闸门服务认证失败，本次指令未发送，请管理员检查设备 ID 和令牌。",
    "UPSTREAM_PROTOCOL_ERROR": "原闸门服务响应不兼容，请管理员检查是否连接了正确的舵机接口。",
    "DEVICE_OFFLINE": "原闸门服务报告 ESP32 离线，请检查设备电源和连接。",
    "COMMAND_REJECTED": "原闸门服务拒绝了指令，请管理员检查后端日志。",
    "DELIVERY_UNKNOWN": "未能确认指令结果，闸门可能已经动作。请现场核实，勿自动重试或反向补偿。",
    "PLUGIN_STOPPED": "闸门插件正在停止或重载，请稍后再试。",
}


class GateBridgePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._bridge: GateBridge | None = None
        self._settings: Settings | None = None
        self._bridge_lock = asyncio.Lock()
        self._stopped = False

    async def initialize(self) -> None:
        try:
            await self._get_bridge()
        except ValueError:
            logger.info("GateBridge 已加载，请在插件配置页填写有效的闸门连接信息。")

    async def terminate(self) -> None:
        async with self._bridge_lock:
            self._stopped = True
            await self._close_bridge()

    async def _close_bridge(self) -> None:
        if self._bridge is not None:
            await self._bridge.close()
        self._bridge = None
        self._settings = None

    async def _get_bridge(self) -> GateBridge:
        async with self._bridge_lock:
            if self._stopped:
                raise BridgeError("PLUGIN_STOPPED")
            try:
                settings = Settings.from_config(self.config.get("connection", {}))
            except ValueError:
                await self._close_bridge()
                raise
            if self._bridge is None or settings != self._settings:
                await self._close_bridge()
                self._bridge = GateBridge(settings)
                self._settings = settings
                self._bridge.start()
            return self._bridge

    @staticmethod
    def _identity(event: AstrMessageEvent) -> str:
        platform_id, sender_id = event.get_platform_id(), event.get_sender_id()
        if not isinstance(platform_id, str) or not isinstance(sender_id, str):
            return ""
        if not platform_id.strip() or not sender_id.strip():
            return ""
        return f"{platform_id}:{sender_id}"

    def _authorized(self, event: AstrMessageEvent, identity: str) -> bool:
        permissions = self.config.get("permissions", {})
        if not identity or not isinstance(permissions, Mapping):
            return False
        if permissions.get("allow_astrbot_admins", True) is True and event.is_admin():
            return True
        for key in ("admin_ids", "member_ids"):
            entries = permissions.get(key, [])
            if isinstance(entries, list) and any(
                isinstance(entry, str) and entry.strip() == identity for entry in entries
            ):
                return True
        return False

    @staticmethod
    def _format_status(status: GateStatus) -> str:
        online = "未知" if status.device_online is None else "在线" if status.device_online else "离线"
        angle = "未知" if status.reported_angle is None else f"{status.reported_angle:g}°"
        position = {
            "open": "报告为开门",
            "closed": "报告为关门",
            "intermediate": "中间角度",
            "unknown": "未知",
        }
        source = {"none": "尚无报告", "initial_snapshot": "初始缓存，可能已过期", "broadcast": "后端广播"}
        lines = [
            f"设备：{status.device_id}",
            f"后端连接：{'已认证' if status.bridge_connected else '未连接或认证中'}",
            f"设备在线情况：{online}",
            f"报告角度：{angle}",
            f"报告位置：{position[status.reported_position]}",
            f"报告来源：{source[status.report_source]}",
            f"报告有效性：{'未知或已过期' if status.stale else '最近收到，不能证明机械到位'}",
        ]
        if status.report_age_seconds is not None:
            lines.append(f"距接收报告：{status.report_age_seconds:g} 秒")
        if status.last_error:
            lines.append(f"连接错误：{status.last_error}")
        lines.append("以上是原服务端报告，闸门实际到位状态尚未确认。")
        return "\n".join(lines)

    async def _handle(self, event: AstrMessageEvent, action: str) -> str:
        identity = self._identity(event)
        if not self._authorized(event, identity):
            return (
                "你没有闸门控制权限，请联系管理员在插件配置页添加授权。\n"
                f"你的授权标识：{identity or '无法获取，请检查消息平台'}"
            )
        action = action.strip().lower()
        if action in {"帮助", "help"}:
            return f"{HELP}\n你的授权标识：{identity}"
        if action not in {"开门", "open", "关门", "close", "状态", "status"}:
            return "未知闸门指令，请发送 /闸门 帮助。"
        try:
            bridge = await self._get_bridge()
            if action in {"状态", "status"}:
                return self._format_status(bridge.status())
            operation = "open" if action in {"开门", "open"} else "close"
            result = await bridge.command(operation)
            label = "开门" if result.operation == "open" else "关门"
            return f"{label}指令（{result.requested_angle}°）已由原服务端转发，闸门是否到位尚未确认。"
        except ValueError:
            return "闸门连接配置不完整或无效，请管理员在插件配置页检查地址、设备 ID、令牌和超时设置。"
        except BridgeError as exc:
            code = str(exc).split(":", 1)[0]
            return ERROR_MESSAGES.get(code, "闸门指令未能完成，请管理员检查插件日志。")

    @filter.command("闸门", alias={"gate"})
    async def gate(self, event: AstrMessageEvent, action: str = "帮助"):
        """闸门 开门/关门/状态/帮助；仅允许配置的管理员及指定成员，转发回执不代表闸门到位。"""
        event.stop_event()
        reply = await self._handle(event, action)
        yield event.plain_result(reply).stop_event()
