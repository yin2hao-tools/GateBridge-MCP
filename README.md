# GateBridge MCP

## 用途

GateBridge MCP 将现有 ESP32/MG946R 闸门控制服务接入 MCP（Model Context Protocol，模型上下文协议）。它以 `controller` 身份连接原服务端，原服务端和 ESP32 固件保持原样。

```text
你的机器人 → MCP → GateBridge MCP → 原舵机 WebSocket 服务 → ESP32 → 闸门
原网页和原 Agent ─────────────────→ 原舵机 WebSocket 服务
```

工具包括 `gate_open`、`gate_close` 和 `gate_get_status`。服务还提供设备说明、状态和协议三个 Resources，以及一个操作提示模板。所有接口都有中文描述和明确的结果语义，详见 [接口说明](docs/api.md)。

**`queued` 只表示原服务端已转发命令，不能证明闸门已经到位。** 本服务不提供原协议缺少的限位、防夹检测和全局控制仲裁。

## 本地运行

需要 Python 3.12 或更新版本，以及现有舵机服务的地址、设备 ID 和令牌。默认设备 ID 为 `mg946r-001`。开门固定为 180°，关门固定为 0°，与原网页保持一致。

安装依赖：

```sh
uv sync --locked
```

PowerShell 下配置并运行：

```powershell
$env:GATEBRIDGE_UPSTREAM_URL = 'ws://127.0.0.1:8777/ws'
$env:GATEBRIDGE_DEVICE_ID = 'mg946r-001'
$env:GATEBRIDGE_DEVICE_TOKEN = '<现用设备令牌>'
uv run --locked gatebridge-mcp
```

Linux 下配置并运行：

```sh
export GATEBRIDGE_UPSTREAM_URL=ws://127.0.0.1:8777/ws
export GATEBRIDGE_DEVICE_ID=mg946r-001
export GATEBRIDGE_DEVICE_TOKEN='<现用设备令牌>'
uv run --locked gatebridge-mcp
```

默认使用 stdio，日志写入 stderr。上游暂时离线时，MCP 仍可启动并列出工具、读取资源。服务会自动重新连接；开关命令永不自动重放。

### 机器人通过 stdio 接入

将下面配置放入机器人的 MCP 配置文件，并替换路径与令牌。Windows 使用 `D:/code/temp/mcptest` 形式的绝对路径。

```json
{
  "mcpServers": {
    "gatebridge": {
      "command": "uv",
      "args": ["run", "--locked", "--directory", "/absolute/path/to/gatebridge-mcp", "gatebridge-mcp"],
      "env": {
        "GATEBRIDGE_UPSTREAM_URL": "ws://original-server:8777/ws",
        "GATEBRIDGE_DEVICE_ID": "mg946r-001",
        "GATEBRIDGE_DEVICE_TOKEN": "<现用设备令牌>"
      }
    }
  }
}
```

### 机器人通过 HTTP 接入

```sh
export GATEBRIDGE_API_TOKEN='<独立的机器人访问令牌>'
uv run --locked gatebridge-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

MCP 地址为 `http://127.0.0.1:8000/mcp`。请求需要携带 `Authorization: Bearer <机器人访问令牌>`。服务使用静态 Bearer 认证，不包含 OAuth 登录与令牌签发；机器人需支持自定义认证请求头。

远程访问时，使用 HTTPS 反向代理或受控加密网络。将实际请求的 Host 加入 `GATEBRIDGE_ALLOWED_HOSTS`；浏览器调用还需设置 `GATEBRIDGE_ALLOWED_ORIGINS`。Origin 白名单用于请求检查，不会自动启用跨域 CORS。普通服务端机器人无需 Origin。

`GET /healthz` 无需认证，仅返回进程存活状态。它不证明板子在线，也不证明闸门状态。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GATEBRIDGE_UPSTREAM_URL` | `ws://127.0.0.1:8777/ws` | 原舵机服务地址，支持 `ws` 和 `wss`，禁止内嵌凭据和查询参数 |
| `GATEBRIDGE_DEVICE_ID` | `mg946r-001` | 与原服务端一致的固定设备 ID |
| `GATEBRIDGE_DEVICE_TOKEN` | 无，必填 | 原服务端现用令牌，不是机器人访问令牌 |
| `GATEBRIDGE_TIMEOUT` | `8` | 连接、认证和单次命令回执的超时秒数 |
| `GATEBRIDGE_STATUS_MAX_AGE` | `30` | 状态报告的有效秒数；初始快照始终按不可信缓存处理 |
| `GATEBRIDGE_TRANSPORT` | `stdio` | `stdio` 或 `streamable-http` |
| `GATEBRIDGE_HOST` | `127.0.0.1` | HTTP 监听地址，命令行参数可覆盖 |
| `GATEBRIDGE_PORT` | `8000` | HTTP 端口，命令行参数可覆盖 |
| `GATEBRIDGE_API_TOKEN` | 空 | MCP HTTP 的静态 Bearer 令牌；监听非本机地址时必填 |
| `GATEBRIDGE_ALLOWED_HOSTS` | 额外列表为空 | 逗号分隔的 HTTP Host，例如 `mcp.example.com` 或 `mcp.example.com:*`；自动允许本机地址 |
| `GATEBRIDGE_ALLOWED_ORIGINS` | 额外列表为空 | 逗号分隔的浏览器 Origin，例如 `https://robot.example.com`；自动允许本机 HTTP Origin |

`.env.example` 仅作为配置参考。普通 Python 启动不会自动加载 `.env`，可使用 `uv run --env-file .env`。令牌只从环境读取，不会出现在 Resources 或日志中。

## 原服务端兼容条件

适配器要求原服务端支持 `/ws` 上的 `controller` 角色。认证成功后，原服务端需依次发送 `auth_ack` 和设备状态快照。控制消息为 `{"device_id":"mg946r-001","cmd":"angle","value":180}`。

原服务端在转发成功后需返回 `{"type":"status","device_id":"mg946r-001","online":true,"success":true,"cmd":"angle","queued":true}`。完整说明见 [接口文档](docs/api.md)。这是已检查项目中的独立舵机协议，不是小智语音 WebSocket 或通用设备 MCP 协议。

如果原服务端在 Docker 容器中，需确认适配器所在网络可以访问舵机端口。容器内的 `127.0.0.1` 指向容器本身。原项目的示例 Compose 没有映射 `8777`。

## 验证记录

开发期间完成以下检查，未新增测试代码：

- Ruff 静态检查和格式检查、Python 字节码编译、wheel 与源码包构建。
- 使用 MCP Inspector 检查 stdio 工具发现、资源发现和提示模板读取。
- 通过 Streamable HTTP 完成初始化，读取状态，检查缺少令牌返回 401、非法 Host 返回 421。
- 在回环地址运行原项目的舵机服务，用临时 WebSocket 客户端代替板子，核对开门下发 180、关门下发 0，以及离线时返回工具错误。
- 设备断开后重新连接适配器，确认原服务端残留的在线缓存被标记为未知和过期。

没有连接生产地址或真实 ESP32。机械到位、防夹、生产网络和实际固件兼容性需要现场确认。

## 容器与自动发布

提供 [Dockerfile](Dockerfile)、[Compose 示例](compose.yaml) 和 [GitHub Actions 工作流](.github/workflows/publish-image.yml)。推送 `X.Y.Z` 或 `vX.Y.Z` 格式的 tag 后，自动构建两个 Linux 平台的镜像，并上传到 Secrets 指定的 Docker Hub、GHCR 或兼容仓库。工作流只构建和上传，部署由外部工具完成。

发布方式参照 Myvideos-TS-Backend，镜像名固定为 `gatebridge-mcp`，同时发布版本标签和 `latest`。配置 `REGISTRY_HOST`、`REGISTRY_NAMESPACE`、`REGISTRY_USERNAME` 和 `REGISTRY_PASSWORD` 四个 Repository Secrets。

原来的 `REGISTRY_IMAGE` 改为 `REGISTRY_NAMESPACE`，只填写目标平台的用户名或组织名。详细步骤、工作流链接和镜像运行方法见 [构建发布说明](docs/publishing.md)。

工作流通过 JSON Schema 检查，Compose 通过配置检查。此前 CI 已完成两个平台的镜像构建，但推送因仓库写入权限不足失败；本次尚未验证实际上传。

## 参考资料

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)：Tools、Resources、Prompts、结构化结果和生命周期。
- [MCP 传输规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)：stdio 与 Streamable HTTP。
- 原项目的 `core/servo_control.py`、`ui/app.js` 和 `ui/index.html`：controller 认证、回执和角度映射。
