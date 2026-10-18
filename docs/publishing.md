# 容器镜像构建与发布

## 发布范围

[GitHub Actions 工作流](../.github/workflows/publish-image.yml) 在推送版本 tag 时构建镜像，并上传到 GitHub Secrets 指定的容器镜像仓库。它不通过 SSH 连接服务器，也不更新运行中的服务。部署由你现有的工具完成。

镜像包含 `linux/amd64` 和 `linux/arm64` 两个平台。工作流使用 [Docker 官方构建发布 Action](https://github.com/docker/build-push-action)、[仓库登录 Action](https://github.com/docker/login-action)、[Buildx Action](https://github.com/docker/setup-buildx-action) 和 [QEMU Action](https://github.com/docker/setup-qemu-action)。

镜像仓库必须支持 Docker Registry API、HTTPS 和 OCI 多平台镜像。Docker Hub、GHCR 和支持这些能力的私有仓库均可使用。自签名证书或仅内网可达的仓库，需要另外配置自托管 Runner 的网络和证书。

## 配置 GitHub Secrets

将代码推送到你自己的 GitHub 仓库。在仓库的 **Settings → Secrets and variables → Actions → Repository secrets** 中添加：

| Secret | 用途 | Docker Hub 示例 | GHCR 示例 |
| --- | --- | --- | --- |
| `REGISTRY_HOST` | 仓库域名，可带端口，不带协议或路径 | `docker.io` | `ghcr.io` |
| `REGISTRY_IMAGE` | 小写的命名空间和镜像名，不带域名或 tag | `yourname/gatebridge-mcp` | `yourname/gatebridge-mcp` |
| `REGISTRY_USERNAME` | 登录账户 | Docker Hub 用户名 | GitHub 用户名 |
| `REGISTRY_PASSWORD` | 具备推送权限的访问令牌 | Docker Hub access token | 有 `write:packages` 权限的 PAT |

私有仓库示例：`REGISTRY_HOST=registry.example.com:5000`，`REGISTRY_IMAGE=robot/gatebridge-mcp`。

这些值只指定镜像发布目标。**不要把生产设备令牌或 MCP 访问令牌放入镜像构建参数。** 运行时令牌由你的部署工具注入；发布镜像不需要访问 ESP32 或原服务端。

上传前，创建镜像仓库或确认账号可以自动创建仓库。组织策略、SSO 授权、令牌有效期和镜像可见性由仓库平台控制。

## 触发版本发布

触发器采用 `*.*.*` tag 匹配，并在工作流内严格校验正式版本号。支持 `0.1.0` 和 `v0.1.0`；不接受 `release-0.1.0`、`v0.1.0-rc.1`、前导零或带额外字段的版本。

发布前，将 `pyproject.toml` 中的项目版本更新为目标版本，并运行 `uv lock`，将改动提交到默认分支。然后创建并推送签名 tag：

```sh
git tag -s v0.1.0 -m "GateBridge MCP 0.1.0"
git push origin v0.1.0
```

推送分支不会触发此工作流。推送正式 tag 后，会生成以下镜像引用：

```text
<REGISTRY_HOST>/<REGISTRY_IMAGE>:0.1.0
<REGISTRY_HOST>/<REGISTRY_IMAGE>:sha-<完整提交 SHA>
```

工作流不发布 `latest`，避免重跑旧版本时改变默认部署目标。部署工具应选定版本 tag 或镜像 digest；成功的 Actions 页面会显示 digest。

同名 tag 仍可能在重新运行时覆盖镜像。若需要禁止覆盖，在镜像仓库启用 tag 不可变策略。推荐部署使用 digest。

工作流运行入口为你仓库下的 **Actions → Publish container image**。上传代码后，实际页面地址为：

```text
https://github.com/<OWNER>/<REPO>/actions/workflows/publish-image.yml
```

当前项目尚未绑定远程仓库，因此这里使用占位地址；仓库内的工作流文件链接已经可用。

## 运行已发布镜像

将 `.env.example` 复制为 `.env`，填写实际的原服务端地址、设备令牌和独立的 MCP HTTP 令牌。Compose 会加载 `.env`，无需把令牌写入 `compose.yaml`。

Linux 示例：

```sh
cp .env.example .env
# 编辑 .env，替换占位内容。
export GATEBRIDGE_IMAGE=docker.io/yourname/gatebridge-mcp:0.1.0
docker compose up -d
```

默认仅将容器端口映射到宿主机 `127.0.0.1:8000`。反向代理可将 `/mcp` 转发到该地址，并保留 `Authorization` 请求头。将外部域名加入 `GATEBRIDGE_ALLOWED_HOSTS`。

容器内部监听 `0.0.0.0`，因此 `GATEBRIDGE_API_TOKEN` 必填。Compose 使用非 root 用户、只读根文件系统及临时 `/tmp`；不需要持久化数据卷。

如果原舵机服务在宿主机上，Docker Desktop 可使用 `host.docker.internal`。Linux 应使用部署网络中可达的地址，或由部署工具配置宿主机映射。不要将容器内的 `127.0.0.1` 当成原服务器。

只需要 stdio 时，可以覆盖镜像的默认参数：

```sh
docker run --rm -i --no-healthcheck --env-file .env \
  docker.io/yourname/gatebridge-mcp:0.1.0 --transport stdio
```

stdio 模式不提供 HTTP 健康探针，上述命令会关闭镜像中的 HTTP 健康检查。

## 本地构建

```sh
docker build -t gatebridge-mcp:local .
```

构建使用 `uv.lock` 锁定运行依赖。`.dockerignore` 只允许包源码、README 和依赖文件进入构建上下文，`.env`、Git 目录和 worktree 均不会发送给构建器。

## 参考资料

- [GitHub Actions 工作流语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)：tag 触发、Secrets 和工作流权限。
- [Docker 官方镜像发布示例](https://docs.docker.com/build/ci/github-actions/push-multi-registries/)：镜像登录、Buildx 和多平台发布。
- [uv Docker 集成](https://docs.astral.sh/uv/guides/integration/docker/)：锁定依赖和分阶段构建。
