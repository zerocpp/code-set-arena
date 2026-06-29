# CodeSetArena 学生端本地部署

完整操作见本目录中的 `CodeSetArena-学生端-安装使用手册-v7.1.3.pdf`。

本地交付包按 Docker Server 架构区分。Windows WSL 2 和普通 Intel/AMD Linux 通常使用 `linux-amd64` 包；Apple Silicon 或 ARM64 Linux 可使用 `linux-arm64` 包。可用以下命令确认：

```bash
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
```

如果本目录包含 `PLATFORM.txt`，请确认其中的 `target_platform` 和上面的输出一致。

如果本目录包含 `docker-offline/`，可先按其中的 README 使用离线 Docker 安装包。

```bash
docker load -i codesetarena-student-v7.1.3.image.tar
cp .env.example .env
docker compose up
```

打开：

```text
http://127.0.0.1:8000
```
