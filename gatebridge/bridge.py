import asyncio
import json
import logging
import math
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal

from websockets.asyncio.client import ClientConnection, connect

from .config import Settings
from .models import CommandQueued, GateStatus

logger = logging.getLogger(__name__)
transport_logger = logging.getLogger(f"{__name__}.transport")
# WebSocket DEBUG 会记录认证帧，使用独立的 INFO 日志避免暴露令牌。
transport_logger.setLevel(logging.INFO)


class BridgeError(Exception):
    pass


class GateBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._socket: ClientConnection | None = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self._pending: asyncio.Future | None = None
        self._report: dict = {}
        self._report_time: float | None = None
        self._report_at: str | None = None
        self._source: Literal["none", "initial_snapshot", "broadcast"] = "none"
        self._online: bool | None = None
        self._online_time: float | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="gatebridge-upstream")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @staticmethod
    def _decode(raw: str | bytes) -> dict:
        try:
            value = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise BridgeError("UPSTREAM_PROTOCOL_ERROR") from exc
        if not isinstance(value, dict):
            raise BridgeError("UPSTREAM_PROTOCOL_ERROR")
        return value

    async def _run(self) -> None:
        delay = 1
        while True:
            try:
                async with connect(
                    self.settings.upstream_url,
                    open_timeout=self.settings.timeout,
                    close_timeout=2,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=65536,
                    logger=transport_logger,
                ) as socket:
                    await socket.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "role": "controller",
                                "device_id": self.settings.device_id,
                                "token": self.settings.device_token,
                            }
                        )
                    )
                    async with asyncio.timeout(self.settings.timeout):
                        auth = self._decode(await socket.recv())
                        while auth.get("type") != "auth_ack":
                            auth = self._decode(await socket.recv())
                        if auth.get("success") is not True:
                            raise BridgeError("UPSTREAM_AUTH_FAILED")
                        if (
                            auth.get("device_id") != self.settings.device_id
                            or auth.get("role") != "controller"
                        ):
                            raise BridgeError("UPSTREAM_PROTOCOL_ERROR")
                        snapshot = self._decode(await socket.recv())
                        if snapshot.get("device_id") != self.settings.device_id:
                            raise BridgeError("UPSTREAM_PROTOCOL_ERROR")
                        if snapshot.get("type") not in {"online", "heartbeat", "status"}:
                            raise BridgeError("UPSTREAM_PROTOCOL_ERROR")
                    self._report = {}
                    self._online = None
                    # shortcut: 上游无快照标识，按认证后首条状态识别；严格区分需要上游增加来源标识。
                    self._observe(snapshot, initial=True)
                    self._socket = socket
                    self._last_error = None
                    self._ready.set()
                    delay = 1
                    logger.info("上游 controller 认证成功")
                    async for raw in socket:
                        self._receive(self._decode(raw))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc) if isinstance(exc, BridgeError) else "UPSTREAM_UNAVAILABLE"
                logger.warning("上游连接中断：%s；%s 秒后重连", self._last_error, delay)
            finally:
                self._ready.clear()
                self._socket = None
                if self._pending and not self._pending.done():
                    self._pending.set_exception(
                        BridgeError("DELIVERY_UNKNOWN: 连接中断，命令可能已转发，请勿自动重试")
                    )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)

    def _observe(self, payload: dict, *, initial: bool = False) -> None:
        if payload.get("device_id") != self.settings.device_id:
            return
        self._report = payload
        self._report_time = time.monotonic()
        self._report_at = datetime.now(UTC).isoformat()
        self._source = "initial_snapshot" if initial else "broadcast"
        online = payload.get("online")
        if isinstance(online, bool):
            self._online = None if initial and online else online
            self._online_time = time.monotonic()

    def _receive(self, payload: dict) -> None:
        if payload.get("device_id") not in {None, self.settings.device_id}:
            return
        pending = self._pending
        if payload.get("type") == "error":
            if pending and not pending.done():
                pending.set_exception(BridgeError("COMMAND_REJECTED: 原服务端拒绝命令"))
            return
        if payload.get("queued") is True and payload.get("cmd") == "angle":
            if pending and not pending.done() and payload.get("success") is True:
                self._online = True
                self._online_time = time.monotonic()
                pending.set_result(None)
            return
        if payload.get("type") in {"online", "heartbeat", "status"}:
            self._observe(payload)
            if payload.get("online") is False and pending and not pending.done():
                pending.set_exception(BridgeError("DEVICE_OFFLINE: 原服务端报告设备离线"))

    def status(self) -> GateStatus:
        age = None if self._report_time is None else max(0, time.monotonic() - self._report_time)
        stale = (
            not self._ready.is_set()
            or age is None
            or age > self.settings.status_max_age
            or self._source != "broadcast"
        )
        angle = self._report.get("angle")
        if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle):
            angle = None
        if angle is not None and not 0 <= angle <= 180:
            angle = None
        position = "unknown"
        if not stale and angle is not None:
            position = "closed" if angle == 0 else "open" if angle == 180 else "intermediate"
        online = self._online
        if (
            not self._ready.is_set()
            or self._online_time is None
            or time.monotonic() - self._online_time > self.settings.status_max_age
        ):
            online = None
        return GateStatus(
            device_id=self.settings.device_id,
            bridge_connected=self._ready.is_set(),
            device_online=online,
            reported_angle=angle,
            reported_position=position,
            report_source=self._source,
            report_received_at=self._report_at,
            report_age_seconds=None if age is None else round(age, 3),
            stale=stale,
            last_error=self._last_error,
        )

    async def command(self, operation: Literal["open", "close"]) -> CommandQueued:
        async with self._command_lock:
            try:
                async with asyncio.timeout(self.settings.timeout):
                    await self._ready.wait()
            except TimeoutError as exc:
                code = self._last_error or "UPSTREAM_UNAVAILABLE"
                raise BridgeError(f"{code}: 上游尚未完成认证，未发送命令") from exc
            socket = self._socket
            if socket is None:
                raise BridgeError("UPSTREAM_UNAVAILABLE: 上游连接已断开，未发送命令")
            angle = 180 if operation == "open" else 0
            pending = asyncio.get_running_loop().create_future()
            self._pending = pending
            try:
                async with asyncio.timeout(self.settings.timeout):
                    await socket.send(
                        json.dumps(
                            {
                                "device_id": self.settings.device_id,
                                "cmd": "angle",
                                "value": angle,
                            }
                        )
                    )
                    await pending
            except BridgeError:
                raise
            except (Exception, asyncio.CancelledError) as exc:
                # Closing prevents a late receipt from being assigned to the next command.
                self._ready.clear()
                await socket.close()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise BridgeError(
                    "DELIVERY_UNKNOWN: 未收到可靠转发回执，命令可能已发送，请勿自动重试"
                ) from exc
            finally:
                self._pending = None
                if not pending.done():
                    pending.cancel()
                elif not pending.cancelled():
                    pending.exception()
            return CommandQueued(
                device_id=self.settings.device_id, operation=operation, requested_angle=angle
            )
