# 真人Lance数据可视化 (FastAPI + Three.js 可视化模板)

本项目用于将 notebook 中的时序可视化逻辑，沉淀为可复用的 **后端 API + 前端交互壳**。
当前已落地 Lance 数据集（MANO/URDF/物体/视频/曲线），并支持后续扩展到 parquet、触觉力觉、灵巧手等数据源。

---

## 1. 核心目标

- 提供统一的可视化 Web 服务：`FastAPI` 后端 + `Three.js` 前端
- 将“数据源差异”限制在 adapter 层，不污染 API 编排层与前端壳
- 支持在前端切换 Lance 数据源，并浏览容器已挂载的数据目录
- 形成通用模板：
  - notebook-specific 逻辑（比如 Lance/MANO）放在 adapter 实现
  - 通用 API 契约与页面交互保持稳定

---

## 2. 技术栈

- 后端：Python 3.10 + FastAPI + Uvicorn
- 数据层：Lance + PyArrow（当前实现）
- 3D/几何：MANO、URDF、trimesh
- 前端：单页 HTML + Three.js
- 通信：REST API（JSON）

---

## 3. 整体架构（实现框架）

```text
┌────────────────────────────────────┐
│ Frontend (Three.js SPA)            │
│ - 轨迹选择/搜索                    │
│ - 3D 场景渲染                      │
│ - 视频面板                          │
│ - 曲线面板                          │
└──────────────┬─────────────────────┘
               │ HTTP JSON
┌──────────────▼─────────────────────┐
│ FastAPI API Orchestration Layer     │
│ app.py                              │
│ - 路由与请求编排                    │
│ - 轨迹状态 LRU 缓存                 │
└──────────────┬─────────────────────┘
               │ Protocol
┌──────────────▼─────────────────────┐
│ Adapter Abstraction                 │
│ core/adapters.py (ViewerAdapter)    │
│ core/viewer_factory.py              │
└──────────────┬─────────────────────┘
               │ implementation
┌──────────────▼─────────────────────┐
│ Lance Adapter (current)             │
│ core/lance_adapter.py               │
│ - list/get metadata                 │
│ - build state                       │
│ - frame/video/curves payload        │
└──────────────┬─────────────────────┘
               │
┌──────────────▼─────────────────────┐
│ Data + Compute Layer                │
│ core/data_loader.py                 │
│ core/visualization.py               │
│ core/curves.py / core/video.py      │
└────────────────────────────────────┘
```

---

## 4. 后端实现方案（FastAPI）

### 4.1 分层职责

1. **配置层**：`core/config.py`
   - 读取可选的 `viz_config.yaml`（未提供时回退到默认配置）
   - 解析数据路径与资源目录等

2. **Adapter 抽象层**：`core/adapters.py`
   - 定义 `ViewerAdapter` Protocol
   - 定义统一 payload schema（TrajectoryInfo、FramePayload、LoadPayload 等）

3. **Adapter 实现层（Lance）**：`core/lance_adapter.py`
   - 负责 Lance 数据读取、状态构建、帧数据与曲线输出

4. **工厂层**：`core/viewer_factory.py`
   - 按 `viewer.type` 创建对应 adapter

5. **API 编排层**：`app.py`
   - 只做路由编排与缓存管理
   - 不直接耦合 Lance/MANO 具体实现

---

### 4.2 关键接口（API 契约）

- `GET /api/trajectories`：轨迹列表
- `GET /api/dataset/current`：当前 Lance 数据源与可浏览根目录
- `GET /api/dataset/browse`：浏览容器已挂载的数据目录
- `POST /api/dataset/load`：切换 Lance 数据源
- `GET /api/trajectory/{index}`：轨迹元信息
- `GET /api/trajectory/{index}/load`：轨迹加载信息（总帧数、曲线选项、可用资源）
- `GET /api/frame/{index}/{frame_idx}`：3D 帧数据
- `GET /api/object_mesh/{index}`：物体网格
- `GET /api/video/{index}/{cam_idx}/{frame_idx}`：视频帧
- `GET /api/curves/{index}`：曲线名列表
- `GET /api/curves/{index}/all`：全部曲线值
- `GET /api/curve/{index}/{curve_name}`：单曲线值

---

### 4.3 缓存与首次加载优化

- 轨迹状态缓存：`app.py` 中 `_state_cache`（LRU，默认最多 10 条）
- 启动预热：服务启动时预加载默认轨迹（`defaults.trajectory_index`）
- 列表性能优化：`core/data_loader.py` 中轨迹列表构建改为批量 `to_pylist()`，避免逐行 `as_py()`

#### 4.4 复杂模型卡顿关键优化

该优化针对`powerdrill`、`largeclamp` 等高面数模型（约 262k 顶点 / 524k 面）：

1. **旧问题（导致切帧 3-5 分钟）**
   - 旧路径在每一帧都返回完整 `object_mesh`（顶点+面片）
   - 单帧数据可达约 18MB，播放/拖帧时重复传输与 JSON 解析，导致严重卡顿

2. **当前方案**
   - 新增一次性网格接口：`GET /api/object_mesh/{index}`
   - 帧接口仅返回物体位姿：`object_transform`（position + rotation）
   - 前端首条轨迹只加载一次物体 mesh，后续每帧只更新 transform，不再重复下载 mesh

3. **效果**
   - 将“每帧大网格传输”改为“首帧一次 + 每帧小位姿数据”
   - 大幅降低切帧延迟与卡顿风险，是复杂模型可交互的关键优化

> 结论：复杂模型场景下，性能收益最大的改动是“mesh 与 transform 解耦传输”，而不是单纯调整缓存条数。

---

## 5. 前端实现方案（Three.js）

### 5.1 页面结构

`frontend/index.html` 为单页应用，包含：

- 顶部控制：轨迹搜索、轨迹切换、播放控制
- 左侧/中间：3D 场景（Three.js）
- 右侧：视频帧
- 底部：曲线图

### 5.2 核心流程

1. 启动时请求 `/api/trajectories`
2. 选择默认轨迹，调用 `/api/trajectory/{index}/load`
3. 若存在物体模型，调用 `/api/object_mesh/{index}` **仅加载一次静态 mesh**
4. 拉取首帧 `/api/frame/...` 与视频 `/api/video/...`
5. 每次切帧只刷新 frame/video；其中物体仅更新 `object_transform`，不重复拉取 mesh
6. 用户拖动帧轴时增量刷新 frame/video

右上角数据源输入框支持直接输入容器内可访问的 `.lance` 路径，也支持通过“浏览”选择已挂载目录中的 `.lance` 数据集。浏览范围默认包含 `/data` 和 `/mnt` 下名称以 `nas` 开头的目录；如需显式指定，可设置环境变量 `DATA_BROWSER_ROOTS`，多个路径用 `:` 分隔。

每个前端页面会通过 `sessionStorage` 持有独立的 `session_id`。切换数据源后，后端会为该页面维护独立的 adapter 和轨迹 LRU 缓存，因此多个页面可以同时查看不同 Lance 数据源。

### 5.3 渲染策略

- Three.js 负责 3D mesh 与 points 可视化
- 曲线面板使用 canvas 绘制

---

## 6. 配置说明

配置文件：可选的 `viz_config.yaml`

如果未提供该文件，服务会使用 `core/config.py` 中的默认配置，并允许通过环境变量覆盖关键路径。

关键字段：

```yaml
paths:
  lance_dataset: /path/to/trajectories_preprocessed.lance
  mano_model: /app/assets/models/MANO_RIGHT.pkl
  urdf: ""
  object_mesh: ""
  project_root: /app

viewer:
  type: lance

defaults:
  trajectory_index: 0
  camera_index: 0
  video_stream: color
  playback_fps: 15
  hand: right
```

说明：
- `viewer.type` 用于选择 adapter（当前支持 `lance`）
- 后续新增数据源时，扩展 adapter 并在工厂注册即可

---

## 7. 快速启动

### Docker（推荐）

```bash
cd deploy
docker compose up -d --build
```

访问：`http://localhost:8868`

### 本地运行

```bash
pip install -r deploy/requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8868 --reload
```

---

## 8. 项目目录（当前）

```text
human_viz/
├── app.py
├── core/
│   ├── adapters.py          # 通用接口与 payload schema
│   ├── viewer_factory.py    # adapter 工厂
│   ├── lance_adapter.py     # Lance 实现
│   ├── config.py
│   ├── data_loader.py
│   ├── visualization.py
│   ├── curves.py
│   ├── video.py
│   ├── mano.py
│   └── urdf_helper.py
├── frontend/
│   └── index.html
├── assets/
└── deploy/
```

---

## 9. 如何扩展到新数据源（模板复用）

以 parquet / tactile / dex-hand 为例：

1. 在 `core/` 新建实现类（如 `parquet_adapter.py`）并实现 `ViewerAdapter`
2. 在 `core/viewer_factory.py` 注册新的 `viewer.type`
3. 如需覆盖默认行为，可通过可选 `viz_config.yaml` 或环境变量切换 `viewer.type`
4. 保持 API 返回契约稳定，前端无需大改（仅按新 payload 增量适配）

---

## 10. 设计原则

- API 编排层与数据语义解耦
- 把 notebook 专属逻辑限制在 adapter 实现层
- 稳定前端壳与 API 契约，降低迁移成本
- 优先优化首屏关键路径（轨迹列表、首帧、视频）

---
