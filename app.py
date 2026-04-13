"""
Lance 可视化 FastAPI 服务

启动：uvicorn app:app --host 0.0.0.0 --port 8868
"""
from pathlib import Path
from collections import OrderedDict

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.adapters import ViewerAdapter
from core.config import get_annotations_dir, get_project_root, load_config
from core.viewer_factory import create_viewer_adapter

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Lance Visualization API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件（plotly.min.js 等）和首页
_FRONTEND = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")
app.mount("/viz/static", StaticFiles(directory=str(_FRONTEND)), name="viz_static")


@app.get("/")
def index():
    return FileResponse(str(_FRONTEND / "index.html"))


# ---------------------------------------------------------------------------
# 全局状态（进程内单例）
# ---------------------------------------------------------------------------

_config: dict = {}
_adapter: ViewerAdapter | None = None
_project_root: Path = Path("/data")
_state_cache: OrderedDict[int, object] = OrderedDict()  # LRU缓存
_MAX_CACHE_SIZE = 10  # 最多缓存10个轨迹状态


@app.on_event("startup")
def startup():
    global _config, _adapter, _project_root, _ANNO_DIR
    _config = load_config()
    _project_root = get_project_root(_config)
    _ANNO_DIR = get_annotations_dir(_config)
    _adapter = create_viewer_adapter(_config, _project_root)
    print(f"[startup] viewer adapter: {_config.get('viewer', {}).get('type', 'lance')}")
    print(f"[startup] 共 {_adapter.total_items} 条轨迹")

    # 预加载默认轨迹到缓存，优化首次访问速度
    default_index = _config.get("defaults", {}).get("trajectory_index", 0)
    print(f"[startup] 预加载默认轨迹 {default_index}")
    _get_state(default_index)
    print(f"[startup] 预加载完成")


def _get_state(index: int):
    """获取（或构建）指定轨迹状态，带LRU缓存。"""
    if index in _state_cache:
        _state_cache.move_to_end(index)
        return _state_cache[index]

    import time

    t0 = time.time()
    print(f"[cache] 开始加载轨迹 {index}")
    state = _adapter.build_state(index)
    t1 = time.time()
    print(f"[cache] 轨迹状态构建完成 {index}，耗时 {t1 - t0:.2f}s")

    _state_cache[index] = state
    if len(_state_cache) > _MAX_CACHE_SIZE:
        oldest = next(iter(_state_cache))
        del _state_cache[oldest]
        print(f"[cache] 清理轨迹 {oldest}，当前缓存: {len(_state_cache)}")

    return state


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@app.get("/api/trajectories")
def list_trajectories():
    """返回所有轨迹的列表，格式 [{label, index}, ...]。"""
    print("[API] /api/trajectories 开始")
    options = _adapter.list_items()
    print(f"[API] /api/trajectories 完成，返回 {len(options)} 条")
    return options


@app.get("/api/trajectory/{index}")
def get_trajectory_info(index: int):
    """返回指定轨迹的元数据。"""
    return _adapter.get_item_info(index)


@app.get("/api/trajectory/{index}/load")
def load_trajectory(index: int):
    """
    预加载轨迹（构建状态）并返回基本信息。
    前端切换轨迹时调用，服务端会缓存计算结果。
    """
    print(f"[API] /api/trajectory/{index}/load 开始")
    state = _get_state(index)
    result = _adapter.get_load_payload(index, state)
    print(f"[API] /api/trajectory/{index}/load 完成，返回数据大小: {len(str(result))} 字节")
    return result


@app.get("/api/frame/{index}/{frame_idx}")
def get_frame(
    index: int,
    frame_idx: int,
    show_mano_mesh: bool = True,
    show_mano_joints: bool = False,
    show_urdf_joints: bool = False,
    show_urdf_mesh: bool = False,
    show_object: bool = True,
    show_origin: bool = False,
):
    """返回指定帧的 3D 数据（mesh/joints 顶点坐标 + faces 索引）。"""
    state = _get_state(index)
    return _adapter.get_frame_payload(
        state=state,
        frame_idx=frame_idx,
        show_mano_mesh=show_mano_mesh,
        show_mano_joints=show_mano_joints,
        show_urdf_joints=show_urdf_joints,
        show_urdf_mesh=show_urdf_mesh,
        show_object=show_object,
        show_origin=show_origin,
    )


@app.get("/api/object_mesh/{index}")
def get_object_mesh(index: int):
    """返回物体网格（只需加载一次）。"""
    state = _get_state(index)
    return _adapter.get_object_mesh_payload(state)


@app.get("/api/video/{index}/{cam_idx}/{frame_idx}")
def get_video_frame(index: int, cam_idx: int, frame_idx: int, stream: str = "color"):
    """返回指定帧的视频图像（base64 data URI）。"""
    payload = _adapter.get_video_frame_payload(index, cam_idx, frame_idx, stream)
    if payload is None:
        raise HTTPException(status_code=404, detail="视频帧不可用")
    return payload


@app.get("/api/curves/{index}")
def get_curves(index: int):
    """返回指定轨迹所有曲线选项名称。"""
    state = _get_state(index)
    return _adapter.get_curve_options(state)


@app.get("/api/curves/{index}/all")
def get_all_curves(index: int):
    """返回指定轨迹的所有曲线数据（批量）。"""
    import time

    t0 = time.time()
    print(f"[API] /api/curves/{index}/all 开始")
    state = _get_state(index)
    t1 = time.time()
    result = _adapter.get_all_curve_data(state)
    t2 = time.time()
    print(f"[API] /api/curves/{index}/all 完成，返回 {len(result)} 条曲线，get_state耗时 {t1-t0:.2f}s，计算曲线耗时 {t2-t1:.2f}s，总耗时 {t2-t0:.2f}s")
    return result


@app.get("/api/curve/{index}/{curve_name:path}")
def get_curve(index: int, curve_name: str):
    """返回指定曲线的全帧数据 float 列表。"""
    state = _get_state(index)
    data = _adapter.get_curve_data(state, curve_name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"曲线 '{curve_name}' 不存在")
    return {"name": curve_name, "data": data}


# ---------------------------------------------------------------------------
# 时间轴标注
# ---------------------------------------------------------------------------

_ANNO_DIR: Path = Path("/app/annotations")  # 启动时由 startup() 覆盖


class Annotation(BaseModel):
    id: str
    start: int
    end: int
    label: str
    color: str = "#ef4444"


class AnnotationPayload(BaseModel):
    trajectory_index: int
    annotations: list[Annotation]


@app.get("/api/annotations/{index}")
def get_annotations(index: int):
    """读取指定轨迹的标注文件。"""
    path = _ANNO_DIR / f"{index}.json"
    if not path.exists():
        return {"trajectory_index": index, "annotations": []}
    return json.loads(path.read_text())


@app.post("/api/annotations/{index}")
def save_annotations(index: int, payload: AnnotationPayload):
    """保存指定轨迹的标注到 JSON 文件。"""
    _ANNO_DIR.mkdir(parents=True, exist_ok=True)
    path = _ANNO_DIR / f"{index}.json"
    path.write_text(payload.model_dump_json(indent=2))
    return {"ok": True}
