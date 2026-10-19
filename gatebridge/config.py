import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    upstream_url: str
    device_id: str
    device_token: str = field(repr=False)
    timeout: float = 8
    status_max_age: float = 30

    @classmethod
    def from_config(cls, config: Mapping) -> "Settings":
        if not isinstance(config, Mapping):
            raise ValueError("闸门连接配置必须是对象")
        url = config.get("upstream_url", "ws://127.0.0.1:8777/ws")
        device_id = config.get("device_id", "mg946r-001")
        token = config.get("device_token", "")
        if not all(isinstance(value, str) for value in (url, device_id, token)):
            raise ValueError("连接地址、设备 ID 和令牌必须是字符串")
        url, device_id = url.strip(), device_id.strip()
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("连接地址格式无效") from exc
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or port == 0:
            raise ValueError("连接地址必须是有效的 ws:// 或 wss:// 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("连接地址不能包含凭据、查询参数或片段")
        if not device_id or not token.strip():
            raise ValueError("请填写设备 ID 和原后端令牌")
        timeout = config.get("timeout", 8)
        max_age = config.get("status_max_age", 30)
        if not all(
            type(value) in (int, float) and math.isfinite(value) and 0 < value <= 3600
            for value in (timeout, max_age)
        ):
            raise ValueError("超时和状态有效期必须是大于 0、不超过 3600 的秒数")
        return cls(url, device_id, token, float(timeout), float(max_age))
