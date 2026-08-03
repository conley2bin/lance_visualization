# Lance 数据可视化与位姿导出指南

本文档讲解 Lance 动捕数据的可视化与位姿导出：数据长什么样、怎么部署可视化系统、怎么用、怎么批量导出物体位姿给客户分析。

---

## 1. 这个系统是做什么的

采集员在动捕棚里用手操作物体（抓瓶子、拧瓶盖等），系统把手部动作（MANO 手模型）、被操作物体的运动轨迹、多相机视频统一存成 Lance 数据集。本项目把这些数据集在浏览器里**逐帧回放**：3D 场景看手和物体的姿态，右侧看视频，底部看数值曲线。

技术形态：FastAPI 后端（Python）+ Three.js 前端，Docker 一键部署，浏览器访问 `http://localhost:8868`。

## 2. 数据长什么样（Lance 数据集结构）

一个 `.lance` 数据集 = 多条**轨迹**（trajectory），每条轨迹是一次录制的完整片段。一条轨迹包含：

| 字段 | 内容 | 说明 |
|---|---|---|
| `index` | uuid、场景名（scene）、操作员（operator）、手势（gesture） | 轨迹的身份信息；scene 里是被操作物体的名字，逗号分隔 |
| `trajectory_metadata` | 总帧数、帧率、手名称、MANO 形状参数、相机信息 | |
| `hands` | 每只手的 MANO 参数序列：`mano_global_pos`、`mano_global_rot_aa`、`mano_hand_pose`、`mano_joint_pos`、`urdf_dof` | 形状都是 (帧数, ...)，逐帧驱动 3D 手模型 |
| `objects` | 每个被操作物体的 `pos` (T,3) + `rot_aa` (T,3) | 逐帧刚体位姿（轴角表示，单位米） |
| `cma_data` | 原始动捕数据：人体标记点、所有刚体的 `position`+`quaternion` | 刚体名单在 `body_names`（含手、腕、物体刚体） |
| `video` / `video_depth` | 各相机的彩色/深度视频帧 | |
| `atomic_actions` | 动作切分标注（动作名 + 起止时间） | |
| `quality_metrics` | 骨骼拉伸、位置跳变等质量指标 | |

## 3. 系统架构（知道这些就够）

```
浏览器 (Three.js 3D 场景 + 视频 + 曲线)
   │ HTTP JSON
FastAPI 后端
   │ 按帧计算
Lance 数据集（手/物体/视频）+ assets 资源（MANO 模型、URDF、物体 mesh）
```

要点：

- **assets 资源目录**提供渲染所需的模型文件：`assets/models/`（MANO 手模型）、`assets/operators/`（操作员 URDF）、`assets/objects/`（物体 mesh，只认 `<名字>_aligned.stl`）。
- 物体 mesh **首帧加载一次**，之后每帧只传位姿——这是大模型（如电钻 262k 顶点）能流畅播放的关键优化。
- 每个浏览器标签页有独立 session，可同时开多个页面看不同数据集。

## 4. 部署

### 4.1 拿到什么（三件套）

| 内容 | 来源 | 说明 |
|---|---|---|
| 代码仓库 | git clone 或压缩包 | 已含 `assets/models`、`assets/operators`、`assets/gestures`（约 12MB） |
| 物体网格包 `objects_full.tar.xz` | 百度网盘 | 42 个物体的 mesh，约 336MB，解压到 `assets/` |
| Lance 数据集 `.lance` | 百度网盘 | 要可视化的数据，放到本机任意目录 |

### 4.2 放置文件

```bash
# 物体网格（sha256 校验和文件可用来核对下载完整性）
sha256sum -c objects_full.tar.xz.sha256
tar -xf objects_full.tar.xz -C /path/to/lance_visualization/assets/
ls /path/to/lance_visualization/assets/objects/bottle/bottle_aligned.stl   # 应存在
```

缺这一步：3D 场景只显示手，不显示被操作的物体。

### 4.3 配置 `deploy/.env`

```bash
cd lance_visualization/deploy
cp .env.example .env
vim .env
```

```bash
BASE_IMAGE=python:3.10          # 公网基础镜像（默认是公司内网 Harbor，公网必须改这行）
HOST_DATA_PATH=/path/to/data    # 数据目录，挂到容器 /data
HOST_NAS_PATH=/path/to/data     # 同上，挂到容器同名路径；填 .lance 所在的上级目录
APP_PORT=8868
```

说明：

- Docker Hub 不可达时，`BASE_IMAGE` 换公共加速器（如 `docker.1ms.run/library/python:3.10`，可用性以当时 `docker pull` 实测为准）。
- `HOST_NAS_PATH` 挂到容器内**同名路径**，所以前端里直接填宿主机的真实路径。
- 数据库配置留空不影响可视化（仅关闭"最近数据源"列表）。

### 4.4 构建、启动、验证

```bash
docker compose up -d --build     # 首次 5-10 分钟，之后秒级

docker ps --filter name=human-viz   # 状态 Up 且无反复重启
docker logs human-viz               # 看到 Application startup complete
curl http://localhost:8868/         # 返回 HTML
```

## 5. 使用

1. 浏览器打开 `http://localhost:8868`
2. **右上角数据源框**填 `.lance` 路径（容器内路径 = 宿主机路径），或点"浏览"逐级选择
   - 注意：每次加载的是**一个具体 `.lance` 数据集**，不是它的父目录
3. 左侧轨迹列表点选轨迹（格式：`编号: 场景 / 手势 (操作员) - 帧数`）
   - 首次加载一条轨迹稍慢（要构建 MANO 顶点），之后有缓存
4. 拖底部帧轴或点播放：3D + 视频 + 曲线联动

左侧显示开关：

| 开关 | 数据量 | 建议 |
|---|---|---|
| MANO Mesh | 小（每帧手 mesh） | 常开 |
| MANO/URDF Joints | 很小（关节点） | 常开 |
| **URDF Mesh** | **大（每帧全量网格，未做传输优化）** | **播放时关闭**，暂停后可单独打开细看 |
| Object / Object Pose Axis | 小 | 常开 |

页面卡死时直接刷新：URL 里的 `?lance=...&traj=N` 参数会自动恢复数据源和轨迹。

## 6. 导出物体位姿（给客户分析）

仓库自带导出脚本 `tools/export_object_poses.py`，批量提取数据集中**每条轨迹、每个物体、每一帧的刚体位姿**，无需启动可视化服务，直接用 Python 跑：

```bash
# 全量导出整个数据集
python tools/export_object_poses.py /path/to/xxx.lance --out ./export_out

# 只导出第 0 条轨迹（验证用）
python tools/export_object_poses.py /path/to/xxx.lance --out ./export_out --index 0
```

每条轨迹输出一个目录：

```
traj_000_disposablecup_bottle_cap/
├── meta.json      # uuid、场景、操作员、手势、帧率、总帧数、物体名单、单位约定
├── poses.npz      # 程序化分析：timestamps(T,) + 每物体 pos(T,3) / rot_aa(T,3)
├── bottle.csv     # 人类可读：timestamp,pos_x,pos_y,pos_z,rot_aa_x,rot_aa_y,rot_aa_z
├── cap.csv
└── disposablecup.csv
```

数据约定（也写在每个 `meta.json` 的 `units` 字段里）：

- **pos**：物体在世界系（动捕棚标定原点）下的平移，单位米
- **rot_aa**：世界系下的旋转，轴角表示，弧度制。转旋转矩阵/四元数用 `scipy.spatial.transform.Rotation.from_rotvec(...)`
- **timestamp**：逐帧时间戳（秒），与手和物体的帧严格对齐（对齐在数据预处理阶段已完成）
- **NaN**：丢帧原样保留，不做插值；下游分析前自行决定填补或剔除策略

npz 读取示例：

```python
import numpy as np
d = np.load("traj_000_disposablecup_bottle_cap/poses.npz")
ts = d["timestamps"]            # (T,) 秒
bottle_pos = d["pos_1_bottle"]  # (T,3) 米
bottle_rot = d["rot_aa_1_bottle"]  # (T,3) 轴角弧度
# 数组键名规则：pos_<物体序号>_<物体名>，序号与 meta.json 的 objects 名单一致
```

参考性能：36 条轨迹（含一条 8 物体、8268 帧）全量导出约 4 秒、60MB。

## 7. 故障排查

| 现象 | 原因与处理 |
|---|---|
| `docker compose` 报 no configuration file | 必须在 `deploy/` 目录下执行 |
| 报 `empty section between colons` | 没建 `.env`：`cp .env.example .env` 并填好路径 |
| build 拉基础镜像超时 | Docker Hub 不可达，`.env` 的 `BASE_IMAGE` 换公共加速器 |
| 容器反复重启、日志为空 | 依赖段错误。确认 `deploy/requirements.txt` 是 `scipy>=1.7.0,<1.15`，不要放开该上限（scipy≥1.15 在新 Debian 基础镜像上 import 即崩溃） |
| 3D 场景没有物体只有手 | 物体 mesh 没放对：确认 `assets/objects/<名>/<名>_aligned.stl` 存在 |
| 页面崩溃/卡死 | 关掉 "URDF Mesh" 刷新 |
| "浏览"看不到数据目录 | 数据必须在 `HOST_DATA_PATH` 或 `HOST_NAS_PATH` 挂载范围内；改 `.env` 后 `docker compose up -d` 重建容器 |

## 8. 完全离线场景

构建需要公网。目标机器完全离线时，在有网机器上：

```bash
docker compose build
docker save human-viz:latest -o human-viz.tar
# 拷贝 human-viz.tar、代码、objects_full.tar.xz、.lance 数据到目标机器
docker load -i human-viz.tar
docker compose up -d    # 不带 --build
```
