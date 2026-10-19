from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class GateStatus:
    device_id: str
    bridge_connected: bool
    device_online: bool | None
    reported_angle: float | None
    reported_position: Literal["open", "closed", "intermediate", "unknown"]
    report_source: Literal["none", "initial_snapshot", "broadcast"]
    report_received_at: str | None
    report_age_seconds: float | None
    stale: bool
    last_error: str | None
    physical_state_confirmed: Literal[False] = False


@dataclass(frozen=True)
class CommandQueued:
    device_id: str
    operation: Literal["open", "close"]
    requested_angle: Literal[0, 180]
    delivery_state: Literal["queued"] = "queued"
    physical_state_confirmed: Literal[False] = False
