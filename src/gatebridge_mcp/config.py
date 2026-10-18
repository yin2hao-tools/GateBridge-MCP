import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    upstream_url: str
    device_id: str
    device_token: str = field(repr=False)
    timeout: float = 8
    status_max_age: float = 30
    api_token: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.getenv("GATEBRIDGE_UPSTREAM_URL", "ws://127.0.0.1:8777/ws").strip()
        parsed = urlsplit(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("GATEBRIDGE_UPSTREAM_URL 必须是完整的 ws:// 或 wss:// 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("上游地址不能包含用户名、密码、查询参数或片段；令牌通过认证消息传递")
        if parsed.port == 0:
            raise ValueError("上游端口不能为 0")
        device_id = os.getenv("GATEBRIDGE_DEVICE_ID", "mg946r-001").strip()
        token = os.getenv("GATEBRIDGE_DEVICE_TOKEN", "")
        if not device_id or not token:
            raise ValueError("必须设置 GATEBRIDGE_DEVICE_TOKEN，且设备 ID 不能为空")
        timeout = float(os.getenv("GATEBRIDGE_TIMEOUT", "8"))
        max_age = float(os.getenv("GATEBRIDGE_STATUS_MAX_AGE", "30"))
        if not all(math.isfinite(value) and 0 < value <= 3600 for value in (timeout, max_age)):
            raise ValueError("超时和状态有效期必须大于 0，且不超过 3600 秒")
        return cls(url, device_id, token, timeout, max_age, os.getenv("GATEBRIDGE_API_TOKEN", ""))
