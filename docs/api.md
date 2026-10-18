# MCP 接口说明

## 发现与约定

服务名称为 `GateBridge MCP`。客户端通过标准 MCP 初始化，随后可调用 `tools/list`、`resources/list` 和 `prompts/list`。stdio 与 Streamable HTTP 提供相同接口。

每个服务实例固定绑定 `GATEBRIDGE_DEVICE_ID`。工具不接受设备 ID、任意角度、任意上游地址或令牌参数。需要控制另一台设备时，单独部署一个实例。

`tools/list` 包含中文用途、调用条件、实际副作用、失败语义和输出 JSON Schema。开关工具的 annotations 为：

```json
{
  "readOnlyHint": false,
  "destructiveHint": true,
  "idempotentHint": false,
  "openWorldHint": true
}
```

这些 annotations 提醒客户端真实设备会移动，并避免自动重试。annotations 只是客户端提示；授权仍由机器人业务系统和 HTTP 令牌控制。

## Tools

### gate_open

打开配置的闸门，对应原网页的 180° 开门。仅在用户明确请求时调用。不能用此工具查询状态或探测连接。

输入参数为空对象：

```json
{"name":"gate_open","arguments":{}}
```

上游收到的消息：

```json
{"device_id":"mg946r-001","cmd":"angle","value":180}
```

成功结果同时提供 `structuredContent` 和 JSON 文本 `content`。`structuredContent` 示例：

```json
{
  "device_id": "mg946r-001",
  "operation": "open",
  "requested_angle": 180,
  "delivery_state": "queued",
  "physical_state_confirmed": false,
  "message": "原服务端已转发命令；闸门是否到位尚未确认。"
}
```

收到成功结果后，可以告诉用户“开门命令已转发，尚未确认闸门到位”。不能告诉用户“闸门已经打开”。

### gate_close

关闭配置的闸门，对应原网页的 0° 关门。调用前由用户或业务系统确认通道可以关闭。本服务无法确认防夹、人员通过或限位状态。

输入为 `{"name":"gate_close","arguments":{}}`。成功结果与 `gate_open` 相同，区别是 `operation` 为 `close`，`requested_angle` 为 `0`。

### gate_get_status

读取本实例最近收到的报告。输入为 `{"name":"gate_get_status","arguments":{}}`。不发送板端命令，不触发闸门动作，上游离线时也可以调用。

示例结果：

```json
{
  "device_id": "mg946r-001",
  "bridge_connected": true,
  "device_online": null,
  "reported_angle": 180,
  "reported_position": "unknown",
  "report_source": "initial_snapshot",
  "report_received_at": "2026-10-18T08:00:00+00:00",
  "report_age_seconds": 0.253,
  "stale": true,
  "physical_state_confirmed": false,
  "last_error": null
}
```

这个示例表示适配器已认证，但只拿到了可能过期的初始快照。即使快照中角度为 180，也不能判断闸门当前打开。

| 字段 | 含义 |
| --- | --- |
| `device_id` | 实例绑定的设备 ID |
| `bridge_connected` | 适配器是否已完成原服务端的 controller 认证；与设备在线是两回事 |
| `device_online` | 最近有效广播或成功转发回执报告的在线情况；断线、过期和未知均为 `null` |
| `reported_angle` | 最近报告中的角度。缺失、非有限数或超出 0～180 时为 `null`。过期角度仍可保留供排查 |
| `reported_position` | 有效广播角度为 180 时是 `open`，为 0 时是 `closed`，其他有效角度为 `intermediate`；缓存、过期或无角度时为 `unknown` |
| `report_source` | `none`、`initial_snapshot` 或 `broadcast` |
| `report_received_at` | 本服务收到报告的 UTC 时间，ISO 8601 格式；不是设备采样时间 |
| `report_age_seconds` | 使用单调时钟计算的接收后经过秒数，未知时为 `null` |
| `stale` | 初始快照、无报告、上游断线或超过配置有效期时为 `true` |
| `physical_state_confirmed` | 始终为 `false`，原协议没有可靠的机械到位确认 |
| `last_error` | 脱敏连接错误代码，正常连接时为 `null` |

心跳若没有 `angle` 字段，角度返回未知，不沿用旧角度假装最新报告。成功的命令回执可以更新 `device_online`，但不会把目标角度写成设备实际角度。

### 失败结果

开关工具失败时返回 MCP 工具错误，`isError` 为 `true`。文本包含下列错误代码，SDK 可能添加工具名称前缀：

```json
{
  "isError": true,
  "content": [
    {
      "type": "text",
      "text": "Error executing tool gate_open: DELIVERY_UNKNOWN: 未收到可靠转发回执，命令可能已发送，请勿自动重试"
    }
  ]
}
```

| 代码 | 含义 | 调用方处理 |
| --- | --- | --- |
| `UPSTREAM_UNAVAILABLE` | 等待上游认证超时或发送前连接已断开，未发送本次命令 | 检查地址、网络和服务状态；恢复后由用户重新发起 |
| `UPSTREAM_AUTH_FAILED` | 原服务端拒绝设备 ID 或令牌 | 检查环境配置；不要尝试另一种设备角色 |
| `UPSTREAM_PROTOCOL_ERROR` | 原服务端响应格式与约定不符 | 核实连接的是独立舵机服务及兼容版本 |
| `DEVICE_OFFLINE` | 原服务端报告设备离线 | 检查 ESP32 电源和连接 |
| `COMMAND_REJECTED` | 原服务端返回 `type=error` | 检查原服务端日志和兼容性 |
| `DELIVERY_UNKNOWN` | 发送期间断线、超时或未收到明确回执，可能已经产生动作 | 停止自动处理，核实设备；不得自动重试或反向补偿 |

服务只重连连接，不会自动重发失败、超时或已排队的开关命令。取消调用也不能保证阻止已发出的硬件动作。

## Resources

`resources/list` 会列出以下三个固定 URI，均为只读资源。当前没有 Resource Templates，也不承诺资源变更订阅。需要更新状态时，重新读取资源或调用状态工具。

| URI | 名称 | MIME 类型 | 内容 |
| --- | --- | --- | --- |
| `gatebridge://device` | `gate_device` | `application/json` | 设备 ID、舵机类型、角度映射、允许工具、状态有效期和能力限制 |
| `gatebridge://status` | `gate_status` | `application/json` | 与 `gate_get_status` 完全相同的状态快照 |
| `gatebridge://protocol` | `gate_protocol` | `text/markdown` | 控制约定、回执解释、缓存限制、并发限制和失败处理 |

读取资源的 MCP 请求：

```json
{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"gatebridge://device"}}
```

`gatebridge://device` 内容示例：

```json
{
  "name": "GateBridge MCP",
  "device_id": "mg946r-001",
  "actuator": "MG946R",
  "open_angle": 180,
  "close_angle": 0,
  "tools": ["gate_open", "gate_close", "gate_get_status"],
  "status_max_age_seconds": 30,
  "physical_confirmation_available": false,
  "exclusive_control": false,
  "command_replay": false
}
```

Resources 不包含上游令牌、机器人令牌或完整环境变量。

## Prompts

`gate_operation` 用于生成面向 Agent 的操作指导。它接受一个必填字符串参数 `intent`，值为 `open`、`close` 或 `status`。

```json
{"jsonrpc":"2.0","id":3,"method":"prompts/get","params":{"name":"gate_operation","arguments":{"intent":"status"}}}
```

提示内容要求先阅读设备和协议资源，读取状态，并准确说明转发回执的含义。获取 Prompt 本身不会调用工具，也不会移动闸门。

## HTTP 与认证

Streamable HTTP 路径为 `/mcp`，使用标准 MCP JSON-RPC 生命周期。配置 `GATEBRIDGE_API_TOKEN` 后，所有 MCP 请求均需携带静态 Bearer 令牌：

```http
Authorization: Bearer <机器人访问令牌>
```

缺失或错误令牌返回 HTTP 401。监听非本机地址时必须配置令牌。该令牌与原服务端的 `GATEBRIDGE_DEVICE_TOKEN` 相互独立。

本服务不实现 OAuth 授权服务器。只支持交互式 OAuth、无法设置认证请求头的客户端，需要由你现有的 MCP 网关接入。

HTTP Host 和浏览器 Origin 按白名单检查。远程部署必须配置实际域名。`GET /healthz` 是唯一不要求认证的存活探针，只返回 `{"status":"ok"}`。

## 上游连接与并发

适配器发送的首条消息固定包含 `"role":"controller"`。它不会用 `device` 身份连接，因此不会主动替换原板子的连接记录。

同一实例串行处理开关命令，并等待对应的转发回执。回执超时后会关闭该连接，避免迟到的回执被下一次调用使用。原协议没有请求 ID，本服务无法为原网页、原 Agent 和其他实例建立全局互斥。

首次认证需要 `auth_ack` 和状态快照。后续 `online`、`heartbeat`、`status` 广播更新状态。初始快照可能来自原服务端缓存，因此始终标记为过期；后续广播的接收时间也不能证明设备采样时间。

原协议没有快照来源标识。本服务按认证后的首条状态识别初始快照；极端并发断线时，缓存与广播可能交错，因此无法严格识别每条消息的来源。在线和角度字段仅代表原服务端报告，不能替代独立传感器。

底层服务若改变角色认证、消息顺序或回执结构，需要重新检查兼容性。本服务不会通过修改原服务端或固件来弥补这些差异。
