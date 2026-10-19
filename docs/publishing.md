# 插件打包与发布

## 本地打包

在项目根目录运行：

```sh
python scripts/package_plugin.py
```

输出文件为 `dist/astrbot_plugin_gatebridge.zip`。可以在 AstrBot 插件菜单中本地上传安装。

打包脚本只收录插件入口、元数据、配置 Schema、依赖、使用说明和 `gatebridge` 包。它不会收录 `.git`、虚拟环境、缓存、旧 `.env` 或本机配置。

ZIP 内部只有一个 `astrbot_plugin_gatebridge` 目录，目录下包含 `main.py` 和 `metadata.yaml`，符合 AstrBot 插件安装结构。

## GitHub Release

[发布工作流](../.github/workflows/release-plugin.yml) 在推送 `*.*.*` 格式的 tag 时执行字节码编译、打包，并将 ZIP 上传到同名 GitHub Release。不再构建 Docker 镜像，也不再读取 `REGISTRY_*` Secrets。

工作流使用 GitHub 自动提供的 `GITHUB_TOKEN`，权限为 `contents: write`，无需配置额外发布令牌。组织策略若禁止工作流写入，需要由仓库管理员调整授权。

发布前，将 `metadata.yaml` 的 `version` 和 `pyproject.toml` 的版本更新为目标版本，运行 `uv lock` 并提交。随后创建并推送签名 tag：

```sh
git tag -s v0.1.0 -m "GateBridge AstrBot 插件 v0.1.0"
git push origin main
git push origin v0.1.0
```

发布后，用户可以从 [GitHub Releases](https://github.com/yin2hao-tools/GateBridge-MCP/releases) 下载 ZIP。工作流为 [Release AstrBot plugin](https://github.com/yin2hao-tools/GateBridge-MCP/actions/workflows/release-plugin.yml)。

重新运行同一 tag 时，会替换该 Release 下的同名 ZIP。重新运行旧的 `v0.0.2` 标签仍会执行旧镜像工作流；新的插件发布流程需要包含本次改动的新 tag。

## 从 MCP 版本迁移

在 AstrBot 中停用旧 GateBridge MCP 入口，再安装本插件。原 MCP 连接地址、HTTP Bearer 令牌和容器镜像地址无需搬入插件。

原后端 WebSocket 地址、设备 ID 和设备令牌需要填入插件菜单。管理员和成员名单也在插件菜单设置，名单默认为空；默认允许 AstrBot 全局管理员。

旧容器的停止、旧 Secrets 的删除以及机器人现有 MCP 配置调整，由部署维护者完成。本项目转换不会操作这些外部服务，也不会修改原服务端或 ESP32。

## 参考资料

- [AstrBot 插件安装和配置](https://docs.astrbot.app/use/plugin.html)。
- [AstrBot 插件目录及元数据](https://docs.astrbot.app/dev/star/plugin-new.html)。
- [GitHub CLI 发布 Release](https://cli.github.com/manual/gh_release_create)。
- [GitHub CLI 上传附件](https://cli.github.com/manual/gh_release_upload)。
