# 公网环境部署指南

本文档面向**无法访问公司内网**的机器（如客户环境）：拿到代码后，如何完成 Docker 构建并启动 Lance 可视化服务。

内网环境的部署见 README 第 7 节。

## 分发内容清单

客户需要拿到三样东西，缺一不可：

| 内容 | 获取方式 | 说明 |
|---|---|---|
| **代码仓库** | git clone 或压缩包 | 已含 `assets/models`、`assets/operators`、`assets/gestures`（共约 12MB） |
| **物体网格包** `objects_pack.zip` | 百度网盘 | 40 个物体的 `*_aligned.stl`，约 98MB，需解压到 `assets/objects/` |
| **Lance 数据集** `.lance` | 百度网盘 | 要可视化的数据文件 |

> 注：`assets/objects` 体积达 1.3GB 且为二进制，不入 git 库（已在 `.gitignore` 排除），通过网盘单独分发瘦身版。

---

## 1. 前置条件

- Docker Engine + Docker Compose 插件（`docker compose version` 能输出版本号）
- 能访问公网（Docker Hub 或其加速器、清华 pypi 镜像、download.pytorch.org、GitHub）
- Lance 数据集已下载到本机

## 2. 获取代码

```bash
git clone <仓库地址> lance_visualization
cd lance_visualization
```

> 若拿到的是压缩包，直接解压即可，无需 git 操作。
> assets 已改为普通目录（不再是子模块），**无需执行 `git submodule`**。

## 3. 放置物体网格

从百度网盘下载 `objects_pack.zip`，解压到仓库的 `assets/objects/` 目录：

```bash
unzip objects_pack.zip -d assets/
# 解压后应形成 assets/objects/<物体名>/<物体名>_aligned.stl 结构
ls assets/objects/bottle/bottle_aligned.stl   # 验证存在
```

缺这一步，3D 场景里只显示手部，不显示被操作的物体。

## 4. 配置 `deploy/.env`

```bash
cd deploy
cp .env.example .env
vim .env
```

必须设置的项：

```bash
# 关键：公网环境覆盖基础镜像源（默认是公司内网 Harbor，公网不可达）
BASE_IMAGE=python:3.10

# Lance 数据集所在目录（挂到容器 /data），改成实际路径
HOST_DATA_PATH=/path/to/lance_datasets

# NAS 挂载路径（挂到容器同名路径），改成实际路径；没有 NAS 就指向数据目录
HOST_NAS_PATH=/path/to/data

APP_PORT=8868
```

说明：

- `BASE_IMAGE=python:3.10` 从 Docker Hub 拉取基础镜像。Docker Hub 不可达时改用公共加速器，例如 `BASE_IMAGE=docker.1ms.run/library/python:3.10`（加速器可用性随时间变化，以 `docker pull` 实测为准）。
- `HOST_NAS_PATH` 会被挂载到容器内的**同名路径**，因此前端数据源输入框里直接填宿主机的真实路径即可。
- 数据库配置（`DATABASE_URL` 等）留空不影响可视化，仅关闭"最近数据源列表"功能。
- 不需要配置 `/etc/docker/daemon.json` 的 insecure-registries——那是内网 HTTP registry 专用的。

## 5. 构建并启动

```bash
docker compose up -d --build
```

首次构建约 5-10 分钟（取决于网络），之后秒级。

## 6. 验证

```bash
docker ps --filter name=human-viz    # 状态 Up，无反复重启
docker logs human-viz                # 应看到 "Application startup complete"
curl http://localhost:8868/          # 应返回 HTML
```

## 7. 使用

浏览器打开 `http://localhost:8868`：

1. 右上角数据源框填某个具体 `.lance` 数据集路径（容器内路径 = 宿主机路径），或点"浏览"逐级选择
2. 左侧轨迹列表点选轨迹
3. 拖帧轴 / 点播放：3D 手 mesh + 物体 + 视频 + 曲线联动

**注意**：播放时不要勾选左侧 "URDF Mesh"（该显示项未做传输优化，每帧全量网格数据会压垮浏览器标签页；暂停后可单独打开细看）。

---

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| build 拉基础镜像超时 | Docker Hub 不可达，把 `.env` 的 `BASE_IMAGE` 换成公共加速器 |
| 容器反复重启、`docker logs` 无输出 | 依赖段错误。确认仓库是包含 scipy 修复的版本（`deploy/requirements.txt` 应为 `scipy>=1.7.0,<1.15`）；不要自行放开该上限 |
| pip 安装阶段报 502 | 镜像站临时故障，重试；或把 Dockerfile 的 `UV_INDEX_URL` 换成其他 pypi 镜像 |
| 3D 场景没有物体，只有手 | 物体网格没放对。确认 `assets/objects/<名>/<名>_aligned.stl` 存在，且 `.env` 的 `HOST_ASSETS_PATH` 指向包含这些文件的 assets 目录 |
| 页面崩溃 / 卡死 | 取消勾选 "URDF Mesh" 后刷新；URL 参数会自动恢复数据源和轨迹 |
| 前端"浏览"看不到数据目录 | 数据路径必须在 `.env` 的 `HOST_DATA_PATH` 或 `HOST_NAS_PATH` 挂载范围内；改 `.env` 后 `docker compose up -d` 重建容器生效 |

## 完全离线场景

构建需要公网。若目标机器完全离线，需在一台有网机器上构建后导出镜像：

```bash
docker compose build
docker save human-viz:latest -o human-viz.tar
# 拷贝 human-viz.tar 与仓库代码到目标机器
docker load -i human-viz.tar
docker compose up -d   # 不带 --build，直接使用本地镜像
```
