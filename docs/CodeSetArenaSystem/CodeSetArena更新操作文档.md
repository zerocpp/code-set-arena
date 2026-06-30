# CodeSetArena 学生端升级操作指南

本文档适用于已在 WSL Ubuntu 环境中安装 Docker Engine 和 Docker Compose 插件，并需要将 CodeSetArena **学生端**从旧版本升级到新版本的场景。以下示例以旧版本 `v7.1.3`、新版本 `v7.1.7`、CPU 架构 `linux-amd64` 为例。执行前应确认版本号、路径、CPU 架构、学生端目录和镜像文件名是否与实际发布包一致。

> 重要说明：本文档只面向 **学生端 WSL 升级**。

从 `v7.1.7` 学生端发布包开始，发布包不再携带 `.env` / `.env.example`。模型服务参数不再通过复制 `.env.example` 初始化，而是在学生端页面的设置入口中填写，或按项目提供的 CLI 方式填写。默认端口为 `8000`，如需修改访问端口，可设置 `CODESETARENA_STUDENT_PORT`，或编辑 `docker-compose.yml` 中端口映射左侧的宿主机端口。

------

## 一、升级前确认

进入 WSL Ubuntu 后，先确认 Docker 正常运行：

```bash
docker version
docker compose version
docker ps
```

确认旧版本目录是否存在：

```bash
ls ~/workspace/codesetarena/Student/
```

确认新版本安装包或已解压目录是否存在：

```bash
ls ~/workspace/Online/
```

本文示例路径如下：

```text
旧版本目录：
~/workspace/codesetarena/Student/codesetarena-student-local-v7.1.3-linux-amd64

新版本目录：
~/workspace/Online/codesetarena-student-local-v7.1.7-linux-amd64

新版本镜像文件：
codesetarena-student-v7.1.7.image.tar
```

升级前建议记录当前运行状态，便于出错时回退或排查：

```bash
docker ps
docker images | grep codesetarena
```

------

## 二、停止旧版本服务

进入旧版本目录：

```bash
cd ~/workspace/codesetarena/Student/codesetarena-student-local-v7.1.3-linux-amd64
```

先查看旧服务状态：

```bash
docker compose ps
```

停止并移除旧版本容器和 Compose 默认网络：

```bash
docker compose down
```

再次确认旧服务是否已经停止：

```bash
docker compose ps
docker ps
```

正常情况下，`docker compose ps` 不应再显示旧版本服务处于 `running` 或 `Up` 状态。

如果担心有残留容器，可以执行：

```bash
docker ps -a
```

注意：默认情况下，`docker compose down` 不会删除外部卷，也不会删除没有被明确清理的镜像。如果需要保留业务数据，不要随意添加 `-v` 参数。

------

## 三、卸载旧版本镜像

确认旧容器已经停止后，可以删除旧版本镜像：

```bash
docker rmi codesetarena-student:v7.1.3
```

如果提示镜像正在被容器使用，先查找相关容器：

```bash
docker ps -a --filter ancestor=codesetarena-student:v7.1.3
```

如确认这些容器已经不再需要，可删除对应容器后再删除镜像：

```bash
docker rm <容器ID或容器名称>
docker rmi codesetarena-student:v7.1.3
```

正式操作中不建议默认使用 `docker rmi -f` 强制删除镜像。应先确认旧容器已经停止并删除，再执行 `docker rmi`。

如果旧版本目录也不再需要，可以移动备份或删除。建议先备份，不建议直接删除：

```bash
mkdir -p ~/workspace/backup

mv ~/workspace/codesetarena/Student/codesetarena-student-local-v7.1.3-linux-amd64 \
   ~/workspace/backup/codesetarena-student-local-v7.1.3-linux-amd64.bak
```

确认升级成功后，再决定是否删除备份目录。

------

## 四、准备新版本目录

进入新版本存放目录：

```bash
mkdir -p ~/workspace/Online
cd ~/workspace/Online
```

如果新版本压缩包尚未解压，执行：

```bash
tar -xzf codesetarena-student-local-v7.1.7-linux-amd64.tar.gz
```

进入新版本目录：

```bash
cd ~/workspace/Online/codesetarena-student-local-v7.1.7-linux-amd64
```

检查目录内容：

```bash
ls -lh
```

`v7.1.7` 学生端发布包正常应能看到类似文件：

```text
PLATFORM.txt
codesetarena-student-v7.1.7.image.tar
docker-compose.yml
```

模型服务相关配置应在学生端启动后进入设置页填写，包括：

```text
Base URL
API Key
模型列表
```

------

## 五、加载新版本 Docker 镜像

在新版本目录中执行：

```bash
docker load -i codesetarena-student-v7.1.7.image.tar
```

加载完成后查看镜像：

```bash
docker images | grep codesetarena
```

正常应看到类似：

```text
codesetarena-student   v7.1.7
```

如果没有看到 `v7.1.7` 镜像，应检查当前目录是否正确，以及镜像文件名是否与实际发布包一致。

------

## 六、启动新版本服务

确认当前仍位于新版本目录：

```bash
pwd
```

启动新版本学生端服务：

```bash
docker compose up -d
```

查看启动状态和日志：

```bash
docker compose ps
docker compose logs --tail=100
```

------

## 七、浏览器访问

默认端口未修改时，在 Windows 浏览器访问：

```text
http://127.0.0.1:8000
```

如果不确定当前端口，执行：

```bash
docker compose ps
```

或：

```bash
docker ps
```

以 `PORTS` 列显示的左侧宿主机端口为准。

------

## 八、升级成功标志

升级完成后，应满足以下条件：

```text
1. 旧版本目录执行 docker compose ps，不再显示旧容器运行；
2. docker images 中可以看到 codesetarena-student:v7.1.7；
3. 新版本目录执行 docker compose ps，服务状态为 running / Up；
4. docker ps 可以看到新版本容器；
5. PORTS 显示类似 0.0.0.0:8000->8000/tcp，或显示自定义宿主机端口；
6. docker compose logs 没有明显 error、failed、panic；
7. Windows 浏览器可以访问 http://127.0.0.1:8000，或访问自定义宿主机端口；
8. 学生端页面可以打开；
9. 在设置页填写 Base URL / API Key / 模型列表后，模型运行测试可正常执行。
```

------

## 九、总结执行更新操作汇总

熟悉操作的人员可使用以下命令快速执行。执行前请确认路径、版本号、CPU 架构和用户目录正确。

```bash
# 1. 停止旧版本服务
cd ~/workspace/codesetarena/Student/codesetarena-student-local-v7.1.3-linux-amd64

docker compose ps
docker compose down
docker compose ps

# 2. 删除旧版本镜像
docker rmi codesetarena-student:v7.1.3

# 3. 准备新版本目录
mkdir -p ~/workspace/Online
cd ~/workspace/Online

# 如未解压，先执行：
# tar -xzf codesetarena-student-local-v7.1.7-linux-amd64.tar.gz

cd ~/workspace/Online/codesetarena-student-local-v7.1.7-linux-amd64

# 4. 检查 v7.1.7 发布包内容
ls -lh
# 正常应包含：
# PLATFORM.txt
# codesetarena-student-v7.1.7.image.tar
# docker-compose.yml

# 5. 如需修改宿主机访问端口，可设置环境变量；不需要修改则跳过
# export CODESETARENA_STUDENT_PORT=8010

# 6. 加载新版本镜像
docker load -i codesetarena-student-v7.1.7.image.tar

# 7. 启动新版本服务
docker compose up -d

# 8. 检查状态
docker compose ps
docker ps
docker compose logs --tail=100
```

默认访问地址：

```text
http://127.0.0.1:8000
```



## 十、故障处理建议

**故障处理建议：旧容器未停止导致镜像无法删除**

在升级 CodeSetArena 或删除旧版本镜像时，可能会遇到类似问题：

```bash
docker rmi codesetarena-student:v7.1.3
```

执行后提示镜像无法删除，常见原因是仍有容器依赖该镜像。

需要明确区分：

```text
docker stop          停止的是容器，不是镜像；
docker rm            删除的是容器；
docker rmi           删除的是镜像；
docker compose down  停止并移除当前 Compose 项目创建的容器和网络。
```

Docker 镜像可以理解为容器运行的基础模板。容器是基于镜像创建出来的运行实例。只要某个容器仍然存在，尤其是仍在运行，系统就可能认为这个镜像仍被占用。

正确处理顺序是：

```text
先停止旧容器 → 再删除旧容器 → 最后删除旧镜像
```

如果知道旧版本目录，优先执行：

```bash
cd ~/workspace/codesetarena/Student/codesetarena-student-local-v7.1.3-linux-amd64
docker compose down
```

然后删除旧镜像：

```bash
docker rmi codesetarena-student:v7.1.3
```

如果已经找不到旧版本目录，可以按镜像查容器：

```bash
docker ps -a --filter ancestor=codesetarena-student:v7.1.3
```

如果查到了容器，先停止再删除：

```bash
docker stop <容器ID或容器名称>
docker rm <容器ID或容器名称>
docker rmi codesetarena-student:v7.1.3
```

不建议一上来使用：

```bash
docker rmi -f codesetarena-student:v7.1.3
```

强制删除容易造成容器和镜像状态不清晰，后续排查更麻烦。

**Tips：在升级 CodeSetArena 或删除旧版本镜像时**，可能会遇到类似问题：

```bash
docker rmi codesetarena-student:v7.1.3
```

执行后提示镜像无法删除，常见原因是：**仍有容器依赖该镜像**。

需要明确区分：

```text
docker stop  停止的是容器，不是镜像；
docker rm    删除的是容器；
docker rmi   删除的是镜像；
docker compose down  停止并移除当前 compose 项目创建的容器和网络。
```

Docker 官方文档说明，`docker image rm` / `docker rmi` 用于删除或取消标记本地镜像，但不能直接删除正在被运行容器使用的镜像，除非使用强制参数；而 `docker compose down` 会停止并移除由 `up` 创建的服务容器和网络。([Docker Documentation](https://docs.docker.com/reference/cli/docker/image/rm/?utm_source=chatgpt.com))

Docker 镜像可以理解为容器运行的“基础模板”。容器是基于镜像创建出来的运行实例。只要某个容器仍然存在，尤其是仍在运行，系统就可能认为这个镜像仍被占用。

因此，正确处理顺序应该是：

```text
先停止旧容器 → 再删除旧容器 → 最后删除旧镜像
```

不能直接跳到 `docker rmi` 删除镜像。

------

## 十一、推荐处理流程

### 第一步：查看当前正在运行的容器

```bash
docker ps
```

如果要查看所有容器，包括已经停止的容器，执行：

```bash
docker ps -a
```

重点查看是否存在旧版本容器，例如：

```text
codesetarena-student
codesetarena-teacher
v7.1.3
v7.1.4
v7.1.5
```

------

### 第二步：进入旧版本目录，优先使用 docker compose down

如果旧版本是通过 `docker compose up -d` 启动的，最推荐进入旧版本目录执行：

```bash
cd ~/workspace/codesetarena/Student/codesetarena-student-local-v7.1.3-linux-amd64
docker compose down
```

教师端示例：

```bash
cd ~/workspace/codesetarena/Teacher/codesetarena-teacher-local-v7.1.3-linux-amd64
docker compose down
```

执行后检查：

```bash
docker compose ps
docker ps
```

`docker compose down` 默认会停止并移除当前 Compose 文件中定义的服务容器，以及该项目创建的默认网络；外部网络和外部卷不会被删除。([Docker Documentation](https://docs.docker.com/reference/cli/docker/compose/down/?utm_source=chatgpt.com))

------

### 第三步：如果不知道旧版本目录，按镜像查容器

如果已经找不到旧版本目录，可以直接查哪些容器依赖这个镜像：

```bash
docker ps -a --filter ancestor=codesetarena-student:v7.1.3
```

或者教师端：

```bash
docker ps -a --filter ancestor=codesetarena-teacher:v7.1.3
```

如果查到了容器，先停止：

```bash
docker stop <容器ID或容器名称>
```

再删除容器：

```bash
docker rm <容器ID或容器名称>
```

Docker 官方文档说明，`docker container rm` / `docker rm` 用于删除容器；如果容器还在运行，应先停止，再删除。([Docker Documentation](https://docs.docker.com/reference/cli/docker/container/rm/?utm_source=chatgpt.com))

------

### 第四步：删除旧镜像

确认旧容器已经停止并删除后，再删除旧镜像：

```bash
docker rmi codesetarena-student:v7.1.3
```

或教师端：

```bash
docker rmi codesetarena-teacher:v7.1.3
```

删除后检查：

```bash
docker images | grep codesetarena
```

如果旧版本镜像不再显示，说明删除成功。

------

## 十二、一组可直接执行的排查命令

以旧版本：学生端 `v7.1.3` 为例：

```bash
# 1. 查看所有 CodeSetArena 容器
docker ps -a | grep codesetarena

# 2. 查看是否有容器依赖旧镜像
docker ps -a --filter ancestor=codesetarena-student:v7.1.3

# 3. 停止旧容器
docker stop <容器ID或容器名称>

# 4. 删除旧容器
docker rm <容器ID或容器名称>

# 5. 删除旧镜像
docker rmi codesetarena-student:v7.1.3

# 6. 检查镜像是否删除成功
docker images | grep codesetarena
```



如果 `docker rmi codesetarena-student:v7.1.3` 失败，通常说明仍有容器占用旧镜像。先执行：

```bash
docker ps -a --filter ancestor=codesetarena-student:v7.1.3
```

确认容器不再需要后删除：

```bash
docker rm <容器ID或容器名称>
docker rmi codesetarena-student:v7.1.3
```

如果 `docker compose up -d` 后容器不断重启，执行：

```bash
docker compose ps
docker compose logs --tail=200
```

如果浏览器无法访问，依次检查：

```bash
docker compose ps
docker ps
docker compose logs --tail=100
```

`docker-compose.yml` 中的端口映射是否与浏览器访问端口一致。
