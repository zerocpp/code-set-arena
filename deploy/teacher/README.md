# CodeSetArena 助教端本地部署

v7.1.7 起，交付包内不再携带 PDF/MD 说明文档或模型配置 `.env` 文件；本目录只保留本地启动所需文件。

本地交付包按 Docker Server 架构区分。Windows WSL 2 和普通 Intel/AMD Linux 通常使用 `linux-amd64` 包；Apple Silicon 或 ARM64 Linux 可使用 `linux-arm64` 包。可用以下命令确认：

```bash
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
```

如果本目录包含 `PLATFORM.txt`，请确认其中的 `target_platform` 和上面的输出一致。

如果本目录包含 `docker-offline/`，可先按其中的 README 使用离线 Docker 安装包。

```bash
docker load -i codesetarena-teacher-v7.1.7.image.tar
docker compose up
```

打开：

```text
http://127.0.0.1:8010
```

首次打开后，请在“设置”页手动填写并保存 Base URL、API Key、模型列表和合法学生端版本号白名单。
