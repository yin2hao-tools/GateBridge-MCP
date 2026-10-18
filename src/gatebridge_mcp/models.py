from typing import Literal

from pydantic import BaseModel, Field


class GateStatus(BaseModel):
    device_id: str = Field(description="本适配器固定控制的设备 ID")
    bridge_connected: bool = Field(description="适配器是否已经通过原舵机服务的 controller 认证")
    device_online: bool | None = Field(description="最近有效广播或命令回执报告的在线状态；过期或未知为 null")
    reported_angle: float | None = Field(description="上游最近报告的角度；不等于传感器确认的实际角度")
    reported_position: Literal["open", "closed", "intermediate", "unknown"] = Field(
        description="根据有效角度报告推断的位置：180 为 open，0 为 closed；缓存或过期时为 unknown"
    )
    report_source: Literal["none", "initial_snapshot", "broadcast"] = Field(
        description="initial_snapshot 可能来自原服务端的过期缓存；broadcast 也不证明机械到位"
    )
    report_received_at: str | None = Field(description="适配器收到角度或状态报告的 UTC 时间，ISO 8601 格式")
    report_age_seconds: float | None = Field(description="距离收到该报告的秒数；不是设备采样时间")
    stale: bool = Field(description="没有报告、初始缓存、上游断线或报告超过有效期时为 true")
    physical_state_confirmed: Literal[False] = Field(
        default=False, description="始终为 false，现有协议不保证机械到位"
    )
    last_error: str | None = Field(description="脱敏的上游连接错误代码；连接正常时为 null")


class CommandQueued(BaseModel):
    device_id: str = Field(description="接收命令的设备 ID")
    operation: Literal["open", "close"] = Field(description="本次请求的操作")
    requested_angle: Literal[0, 180] = Field(description="发送给原舵机服务的目标角度")
    delivery_state: Literal["queued"] = Field(default="queued", description="仅确认原服务端已转发命令")
    physical_state_confirmed: Literal[False] = Field(
        default=False, description="始终为 false，不代表闸门已经到位"
    )
    message: str = Field(
        default="原服务端已转发命令；闸门是否到位尚未确认。", description="给用户的准确结果说明"
    )
