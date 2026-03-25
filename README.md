# Lance 数据集可视化服务

基于 FastAPI + Three.js 的 Lance 格式运动捕捉数据集可视化工具，支持 MANO 手模型、URDF 机器人模型、物体 6DoF 姿态、同步视频回放及时间轴标注。

## 功能概览

- **3D 可视化**：MANO 手部网格/关节、URDF 机器人关节/网格、物体模型，帧级别同步渲染
- **视频回放**：多摄像头彩色/深度视频与 3D 场景帧同步
- **数据曲线**：时间序列数据的多曲线叠加显示
- **时间轴标注**：拖拽创建/编辑/保存帧级别标注区间，持久化为 JSON
- **轨迹搜索**：支持模糊搜索，从万级轨迹中快速定位

## 快速开始

### 方式一：Docker（推荐）

**1. 配置环境变量**

复制并编辑 `deploy/.env`：

```bash
cp deploy/.env.example deploy/.env  # 若有模板
# 或直接编辑
vim deploy/.env
```

必填项：

```env
HOST_DATA_PATH=/path/to/your/data     # 宿主机数据目录，将挂载为容器内 /data
HOST_NAS_PATH=/mnt/nas-222-project    # NAS 挂载路径（含 Lance 数据集）
LANCE_DATASET=/mnt/nas-222-project/mocap/releases/v0.5/trajectories_preprocessed.lance
```

**2. 构建并启动**

```bash
cd deploy
docker compose up -d --build
```

**3. 访问服务**

浏览器打开 `http://localhost:8868`

---

### 方式二：本地直接运行

**环境要求**：Python 3.10（不兼容 3.11+，原因见[依赖说明](#依赖说明)）

**1. 安装依赖**

```bash
pip install -r deploy/requirements.txt

# 额外安装（需网络访问 GitHub）
pip install --no-build-isolation git+https://github.com/mattloper/chumpy
pip install --no-build-isolation git+https://github.com/lixiny/manotorch.git
```

**2. 准备配置**

将项目根目录的 `viz_config.yaml` 按实际路径修改（该文件已包含所有配置项及注释）：

```bash
vim viz_config.yaml
```

**3. 启动服务**

```bash
uvicorn app:app --host 0.0.0.0 --port 8868 --reload
```

---

## 配置文件说明

服务启动时按以下优先级查找配置（先找到即停止）：

1. `/data/viz_config.yaml`（Docker 环境默认挂载位置）
2. 当前工作目录下的 `viz_config.yaml`
3. 项目根目录下的 `viz_config.yaml`

**环境变量优先级高于配置文件**，可覆盖任意配置项。

### 完整配置结构

```yaml
paths:
  # Lance 数据集路径（必填）
  lance_dataset: /mnt/nas-222-project/mocap/releases/v0.5/trajectories_preprocessed.lance

  # MANO 手模型文件路径（.pkl 格式）
  # 使用左手数据时改为 MANO_LEFT.pkl
  mano_model: /app/assets/models/MANO_RIGHT.pkl

  # URDF 模型路径（可选，不填则不渲染机器人模型）
  urdf: ""

  # 物体网格路径（可选，通常从 assets/objects/ 自动读取）
  object_mesh: ""

  # 标注文件保存目录（Docker 下需挂载为可读写卷）
  annotations_dir: /app/annotations

  # 资源根目录（assets/ 所在的父目录）
  project_root: /app

defaults:
  # 服务启动后默认选中的轨迹索引
  trajectory_index: 0

  # 默认摄像头索引（0 表示第一个摄像头）
  camera_index: 0

  # 默认视频流类型：color（彩色）或 depth（深度）
  video_stream: color

  # 自动播放帧率（FPS），影响播放速度
  playback_fps: 15

  # 手型：right（右手）或 left（左手），需与 mano_model 对应
  hand: right
```

### 环境变量参考

| 变量名 | 对应配置 | 说明 |
|--------|---------|------|
| `LANCE_DATASET` | `paths.lance_dataset` | Lance 数据集路径 |
| `MANO_MODEL_PATH` | `paths.mano_model` | MANO 模型文件路径 |
| `ANNOTATIONS_DIR` | `paths.annotations_dir` | 标注文件保存目录 |
| `PROJECT_ROOT` | `paths.project_root` | 项目资源根目录 |

---

## deploy/.env 说明

`deploy/.env` 专用于 Docker Compose 卷挂载，与上面的 `viz_config.yaml` 是两套独立配置。

```env
# ===== 宿主机路径（卷挂载来源）=====

# 数据目录，将挂载为容器内 /data
HOST_DATA_PATH=/home/user/data

# NAS 挂载路径，挂载为容器内 /mnt/nas-222-project 和 /mnt/nas-222
HOST_NAS_PATH=/mnt/nas-222-project

# assets/ 目录（MANO 模型、物体 STL 等），挂载为 /app/assets
HOST_ASSETS_PATH=../assets

# 标注文件保存目录，挂载为 /app/annotations（可读写）
HOST_ANNOTATIONS_PATH=../annotations

# ===== Docker 服务配置 =====

# 服务端口，同时影响容器端口映射
APP_PORT=8868

# 时区
TZ=Asia/Shanghai

# 应用配置（Lance 路径、MANO 模型、播放参数等）请编辑 viz_config.yaml
```

---

## API 接口说明

服务启动后提供以下 REST API（基础路径为服务根路径）：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/trajectories` | GET | 获取全部轨迹列表，返回 `[{label, index}]` |
| `/api/trajectory/{index}` | GET | 获取轨迹元数据（场景、操作员、帧数等） |
| `/api/trajectory/{index}/load` | GET | 预加载轨迹，返回完整信息及可用曲线列表 |
| `/api/frame/{index}/{frame_idx}` | GET | 获取指定帧 3D 数据（顶点、面片） |
| `/api/video/{index}/{cam_idx}/{frame_idx}` | GET | 获取指定帧视频图像（base64） |
| `/api/curves/{index}` | GET | 获取轨迹所有可用曲线名称 |
| `/api/curve/{index}/{curve_name}` | GET | 获取指定曲线的全帧数据 |
| `/api/annotations/{index}` | GET | 读取轨迹标注 |
| `/api/annotations/{index}` | POST | 保存轨迹标注 |

---

## 数据格式要求

### Lance 数据集列结构

每条轨迹对应数据集中的一行（row），需包含以下列：

| 列名 | 形状 | 说明 |
|------|------|------|
| `index` | dict | 包含 `scene`、`operator`、`uuid`、`capMachine` |
| `trajectory_metadata` | dict | 包含 `total_frames`、`mano_hand_shapes`、`object_names` |
| `hands[*].mano_joint_pos` | `(T, 63)` | 21 个关节位置，需 reshape 为 `(T, 21, 3)` |
| `hands[*].mano_global_rot_aa` | `(T, 3)` | 全局旋转（轴角） |
| `hands[*].mano_global_pos` | `(T, 3)` | 全局位置（米） |
| `hands[*].mano_hand_pose` | `(T, 45)` | 手指 pose（15 关节 × 3） |
| `hands[*].urdf_dof` | `(T, nDOF)` | 机器人 URDF 自由度值 |
| `objects[*].pos` | `(T, 3)` | 物体位置 |
| `objects[*].rot_aa` | `(T, 3)` | 物体旋转（轴角） |
| `video` | binary array | RGB 视频（每帧 JPEG 压缩） |
| `video_depth` | binary array | 深度视频（每帧 PNG 压缩） |

其中 `T` 为轨迹总帧数。

### 坐标系约定

数据坐标系 → Three.js 坐标系的映射：

```
Three.js = (data.x,  data.z,  -data.y)
```

| 轴 | 方向 | 颜色 |
|----|------|------|
| X  | 右   | 红   |
| Y  | 前（数据）→ Three.js Z 负方向 | 绿 |
| Z  | 上（数据）→ Three.js Y 正方向 | 蓝 |

### 标注文件格式

标注保存为 JSON，路径为 `{ANNOTATIONS_DIR}/{trajectory_index}.json`：

```json
{
  "trajectory_index": 0,
  "annotations": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "start": 10,
      "end": 50,
      "label": "grasp",
      "color": "#ef4444"
    }
  ]
}
```

---

## 项目结构

```
lance_viz_new/
├── app.py                  # FastAPI 主应用
├── core/
│   ├── config.py           # 配置加载
│   ├── data_loader.py      # Lance 数据集读取
│   ├── visualization.py    # 3D 数据计算（MANO、URDF、物体）
│   ├── curves.py           # 时间序列曲线提取
│   ├── mano.py             # MANO 手模型推理
│   ├── urdf_helper.py      # URDF 正向运动学
│   └── video.py            # 视频帧解码
├── frontend/
│   ├── index.html          # 单页前端应用
│   └── three.module.min.js # Three.js r168
├── assets/
│   ├── models/             # MANO_LEFT.pkl, MANO_RIGHT.pkl
│   ├── objects/            # 物体 STL 模型（22 种物体）
│   ├── operators/          # 操作人员数据
│   ├── gestures/           # 手势分类数据
│   └── scene.yaml          # 手势-物体映射关系
├── annotations/            # 标注文件（本地生成，不入 Git）
└── deploy/
    ├── Dockerfile
    ├── docker-compose.yml
    ├── requirements.txt
    └── .env                # 本地环境配置（不入 Git）
```

---

## 依赖说明

**Python 版本必须使用 3.10**，原因：

- `chumpy`：依赖 `numpy` 旧 API，在 Python 3.11+ 中存在兼容性问题
- `manotorch`：间接依赖 `chumpy`，受相同限制

主要依赖版本约束：

```
numpy>=1.24.0,<1.27.0   # 上限避免 chumpy 兼容性问题
datasets<3.2.0           # 高版本 API 变更
pin==2.6.21              # Pinocchio 固定版本（运动学计算）
```

---

## 与采集系统集成（DexStream_Web）

本服务可通过 Nginx 反向代理嵌入采集系统，以 `<iframe>` 方式集成。

Nginx 配置关键点（`/viz/` 末尾斜杠不可省略）：

```nginx
location /viz/ {
    proxy_pass http://host.docker.internal:8868/;  # 末尾 / 用于剥离 /viz/ 前缀
    proxy_hide_header X-Frame-Options;
    proxy_hide_header Content-Security-Policy;
}
```

前端 iframe：

```html
<iframe src="/viz/" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads"></iframe>
```
