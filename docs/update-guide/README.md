# CodeSetArena 学生端更新操作指南

本文适用于已在 WSL Ubuntu 环境中安装 Docker Engine 和 Docker Compose 插件，并需要将 CodeSetArena 学生端从旧版本升级到新版本的场景。以下示例以旧版本 `v7.1.3`、新版本 `v7.1.7`、CPU 架构 `linux-amd64` 为例。执行前应确认版本号、路径、CPU 架构和角色目录是否与实际文件一致。

Docker Compose 官方文档说明，`docker compose down` 会停止并移除由 `up` 创建的容器；`docker compose up` 会创建、重建并启动服务容器；`docker compose ps` 用于查看 Compose 项目的容器状态和端口。升级时应先停旧服务，再加载新镜像，最后启动新版本。([Docker Documentation](https://docs.docker.com/reference/cli/docker/compose/down/?utm_source=chatgpt.com))

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

![image-20260630230359716](C:\Users\27241\AppData\Roaming\Typora\typora-user-images\image-20260630230359716.png)

再次确认旧服务是否已经停止：

```bash
docker compose ps
docker ps
```

正常情况下，`docker compose ps` 不应再显示旧版本服务处于 `running` 或 `Up` 状态。

![image-20260630230419457](C:\Users\27241\AppData\Roaming\Typora\typora-user-images\image-20260630230419457.png)

如果担心有残留容器，可以执行：

```bash
docker ps -a
```

注意：默认情况下，`docker compose down` 不会删除外部卷，也不会删除没有被明确清理的镜像；如果需要保留业务数据，不要随意添加 `-v` 参数。Docker 官方文档也说明，`down` 默认主要移除服务容器和网络，外部网络和卷不会被删除。([Docker Documentation](https://docs.docker.com/reference/cli/docker/compose/down/?utm_source=chatgpt.com))

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

Docker 官方文档说明，`docker image rm` / `docker rmi` 用于移除或取消标记本地镜像；如果镜像正在被运行中的容器使用，不能直接删除，除非使用强制参数。正式操作文档中不建议默认使用 `-f`，应先确认容器状态。([Docker Documentation](https://docs.docker.com/reference/cli/docker/image/rm/?utm_source=chatgpt.com))

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

正常应能看到类似文件：

```text
docker-compose.yml 或 compose.yaml
.env.example
codesetarena-student-v7.1.7.image.tar
```

------

## 五、初始化新版本环境文件

如果新版本目录中存在 `.env.example`，但还没有 `.env`，执行：

```bash
cp -n .env.example .env
```

然后检查 `.env` 内容：

```bash
cat .env
```

如需修改端口、路径、环境变量，应使用编辑器打开：

```bash
nano .env
```

`cp -n` 的作用是：如果 `.env` 已存在，则不覆盖旧文件。这样可以避免误覆盖已经配置好的端口、密钥或运行参数。Docker Compose 支持通过环境变量文件设置容器环境，官方文档也说明 Compose 可以结合 `.env` / `env_file` 管理环境变量配置。([Docker Documentation](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/?utm_source=chatgpt.com))

------

## 六、加载新版本 Docker 镜像

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

Docker 官方文档说明，`docker load` 可以从 tar 归档文件或标准输入加载镜像，并恢复镜像及其标签。([Docker Documentation](https://docs.docker.com/reference/cli/docker/image/load/?utm_source=chatgpt.com))

------

## 七、启动新版本服务

确认当前位于新版本目录：

```bash
pwd
```

应显示：

```text
/home/你的用户名/workspace/Online/codesetarena-student-local-v7.1.7-linux-amd64
```

启动新版本服务：

```bash
docker compose up -d
```

查看启动状态：

```bash
docker compose ps
docker ps
```

查看启动日志：

```bash
docker compose logs --tail=100
```

如果需要持续观察日志：

```bash
docker compose logs -f
```

`docker compose up -d` 表示在后台启动服务；Docker Compose 官方文档说明，`up` 会创建、重建并启动 Compose 文件中定义的服务容器。([Docker Documentation](https://docs.docker.com/reference/cli/docker/compose/up/?utm_source=chatgpt.com))

------

## 八、浏览器访问新版本

查看端口映射：

```bash
docker compose ps
```

或：

```bash
docker ps
```

找到类似：

```text
0.0.0.0:8080->80/tcp
```

则在 Windows 浏览器访问：

```text
http://127.0.0.1:8080
```

如果端口不是 `8080`，应以 `docker compose ps` 或 `docker ps` 显示的实际端口为准。

------

## 九、升级成功标志

升级完成后，应满足以下条件：

```text
1. 旧版本目录执行 docker compose ps，不再显示旧容器运行；
2. docker images 中可以看到 codesetarena-student:v7.1.7；
3. 新版本目录执行 docker compose ps，服务状态为 running / Up；
4. docker ps 可以看到新版本容器；
5. docker compose logs 没有明显 error、failed、panic；
6. Windows 浏览器可以访问 http://127.0.0.1:端口；
7. 页面显示为新版本学生端服务。
```

------

## 十、可直接执行的升级命令汇总

熟悉操作的人员可使用以下命令快速执行。执行前请确认路径、版本号、CPU 架构和角色目录正确。

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


# 4. 加载新版本镜像
docker load -i codesetarena-student-v7.1.7.image.tar

# 5. 启动新版本服务
docker compose up -d

# 6. 检查状态
docker compose ps
docker ps
docker compose logs --tail=100
```

------

## 十一、故障处理建议

**故障处理建议：旧容器未停止导致镜像无法删除**

### 1.原因解释

在升级 CodeSetArena 或删除旧版本镜像时，可能会遇到类似问题：

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

------

### 2. 原因解释

Docker 镜像可以理解为容器运行的“基础模板”。容器是基于镜像创建出来的运行实例。只要某个容器仍然存在，尤其是仍在运行，系统就可能认为这个镜像仍被占用。

因此，正确处理顺序应该是：

```text
先停止旧容器 → 再删除旧容器 → 最后删除旧镜像
```

不能直接跳到 `docker rmi` 删除镜像。

------

## 十二、推荐处理流程

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

## 十三、一组可直接执行的排查命令

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

如果是教师端，把镜像名改成：

```bash
codesetarena-teacher:v7.1.3
```

------

## 5. 更推荐的升级写法

如果你知道旧版本目录，建议不要手动一个个 `docker stop`，而是直接执行：

```bash
cd 旧版本目录
docker compose down
```

然后再删除旧镜像：

```bash
docker rmi 旧版本镜像名
```

例如：

```bash
cd ~/workspace/codesetarena/Student/codesetarena-student-local-v7.1.3-linux-amd64
docker compose down

docker rmi codesetarena-student:v7.1.3
```

这样比手动 `docker stop` 更稳，因为 `docker compose down` 会按照当前项目的 Compose 配置统一停止并移除相关容器和网络。([Docker Documentation](https://docs.docker.com/reference/cli/docker/compose/down/?utm_source=chatgpt.com))

------

## 6. 不建议一上来使用强制删除

不要优先使用：

```bash
docker rmi -f codesetarena-student:v7.1.3
```

原因是：强制删除容易造成容器和镜像状态不清晰，后续排查更麻烦。文档中建议写成：

```text
正式升级时，不建议默认使用 -f 强制删除镜像。应先确认旧容器已经停止并删除，再执行 docker rmi。
```

------

## 7. 判断是否处理成功

满足以下条件，说明旧版本已经清理干净：

```bash
docker ps -a | grep codesetarena
```

不再显示旧版本容器；

```bash
docker images | grep codesetarena
```

不再显示旧版本镜像；

```bash
docker compose ps
```

旧版本目录下没有正在运行的服务；

```bash
docker ps
```

只显示当前需要运行的新版本容器。



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

同时确认 `.env` 或 `docker-compose.yml` 中的端口映射是否与浏览器访问端口一致。