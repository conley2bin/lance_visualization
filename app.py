"""
Lance 可视化 FastAPI 服务

启动：uvicorn app:app --host 0.0.0.0 --port 8868
"""
import os
from pathlib import Path
from collections import OrderedDict

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import get_annotations_dir, get_project_root, load_config
from core.curves import get_curve_data, get_curve_options
from core.data_loader import OptimizedLanceLoader
from core.video import decode_video_frame, frame_to_base64
from core.visualization import TrajectoryState, get_frame_data

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


@app.get("/")
def index():
    return FileResponse(str(_FRONTEND / "index.html"))

# ---------------------------------------------------------------------------
# 全局状态（进程内单例）
# ---------------------------------------------------------------------------

_config: dict = {}
_loader: OptimizedLanceLoader | None = None
_project_root: Path = Path("/data")
_state_cache: OrderedDict[int, TrajectoryState] = OrderedDict()  # LRU缓存
_MAX_CACHE_SIZE = 10  # 最多缓存10个轨迹状态


@app.on_event("startup")
def startup():
    global _config, _loader, _project_root, _ANNO_DIR
    _config = load_config()
    _project_root = get_project_root(_config)
    _ANNO_DIR = get_annotations_dir(_config)
    lance_path = _config["paths"]["lance_dataset"]
    print(f"[startup] 加载 Lance 数据集: {lance_path}")
    _loader = OptimizedLanceLoader(lance_path)
    print(f"[startup] 共 {_loader.total_rows} 条轨迹")


def _get_state(index: int) -> TrajectoryState:
    """获取（或构建）指定轨迹的 TrajectoryState，带LRU缓存。"""
    if index in _state_cache:
        # 移到末尾表示最近使用
        _state_cache.move_to_end(index)
        return _state_cache[index]

    # 加载新轨迹
    import time
    t0 = time.time()
    print(f"[cache] 开始加载轨迹 {index}")
    lance_row = _loader.load_trajectory_data(index)
    if lance_row is None:
        raise HTTPException(status_code=404, detail=f"轨迹 {index} 加载失败")
    t1 = time.time()
    print(f"[cache] lance_row 加载完成 {index}，耗时 {t1-t0:.2f}s")
    mano_model_path = _config["paths"]["mano_model"]
    hand = _config.get("defaults", {}).get("hand", "right")
    print(f"[cache] 开始构建 TrajectoryState {index}")
    state = TrajectoryState(
        lance_row=lance_row,
        mano_model_path=mano_model_path,
        hand=hand,
        project_root=_project_root,
    )
    t2 = time.time()
    print(f"[cache] TrajectoryState 构建完成 {index}，耗时 {t2-t1:.2f}s，总耗时 {t2-t0:.2f}s")

    # 添加到缓存
    _state_cache[index] = state

    # 超过限制则删除最旧的
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
    options = _loader.create_trajectory_options()
    print(f"[API] /api/trajectories 完成，返回 {len(options)} 条")
    return [{"label": label, "index": idx} for label, idx in options]


@app.get("/api/trajectory/{index}")
def get_trajectory_info(index: int):
    """返回指定轨迹的元数据。"""
    if index < 0 or index >= _loader.total_rows:
        raise HTTPException(status_code=404, detail="轨迹索引超出范围")
    info = _loader.get_trajectory_info(index)
    return info


@app.get("/api/trajectory/{index}/load")
def load_trajectory(index: int):
    """
    预加载轨迹（构建 TrajectoryState）并返回基本信息。
    前端切换轨迹时调用，服务端会缓存计算结果。
    """
    print(f"[API] /api/trajectory/{index}/load 开始")
    if index < 0 or index >= _loader.total_rows:
        raise HTTPException(status_code=404, detail="轨迹索引超出范围")
    print(f"[API] 开始获取 state {index}")
    state = _get_state(index)
    print(f"[API] state {index} 获取完成")
    info = _loader.get_trajectory_info(index)
    print(f"[API] 开始获取 video blobs {index}")
    video_info = _loader.get_video_blobs(index)
    print(f"[API] 开始获取 curve options {index}")
    curve_opts = get_curve_options(state)
    result = {
        **info,
        "total_frames": state.T,
        "num_cameras": video_info["num_cameras"],
        "has_urdf": state.urdf_helper is not None,
        "has_object_mesh": state.object_mesh is not None,
        "curve_options": curve_opts,
    }
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
    return get_frame_data(
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
    if state.object_mesh is None:
        return None
    return {
        "x": state.object_mesh["vertices"][:, 0].tolist(),
        "y": state.object_mesh["vertices"][:, 1].tolist(),
        "z": state.object_mesh["vertices"][:, 2].tolist(),
        "i": state.object_mesh["faces"][:, 0].tolist(),
        "j": state.object_mesh["faces"][:, 1].tolist(),
        "k": state.object_mesh["faces"][:, 2].tolist(),
    }


@app.get("/api/video_debug/{index}")
def get_video_debug(index: int):
    """调试：返回视频数据结构信息。"""
    video_blobs = _loader.get_video_blobs(index)
    video = video_blobs.get("video")
    info = {"num_cameras": video_blobs["num_cameras"], "cameras": []}
    if video:
        for i, cam in enumerate(video):
            if isinstance(cam, dict):
                cam_info = {k: (len(v) if isinstance(v, (list, bytes)) else type(v).__name__) for k, v in cam.items()}
            else:
                cam_info = {"type": type(cam).__name__, "len": len(cam) if cam else 0}
            info["cameras"].append(cam_info)
            if i >= 3:
                info["cameras"].append("...")
                break
    return info


@app.get("/api/video/{index}/{cam_idx}/{frame_idx}")
def get_video_frame(index: int, cam_idx: int, frame_idx: int, stream: str = "color"):
    """返回指定帧的视频图像（base64 data URI）。"""
    video_blobs = _loader.get_video_blobs(index)
    frame = decode_video_frame(video_blobs, cam_idx, frame_idx, stream)
    if frame is None:
        raise HTTPException(status_code=404, detail="视频帧不可用")
    return {"data_uri": frame_to_base64(frame)}


@app.get("/api/curves/{index}")
def get_curves(index: int):
    """返回指定轨迹所有曲线选项名称。"""
    state = _get_state(index)
    return get_curve_options(state)


@app.get("/api/curves/{index}/all")
def get_all_curves(index: int):
    """返回指定轨迹的所有曲线数据（批量）。"""
    import time
    t0 = time.time()
    print(f"[API] /api/curves/{index}/all 开始")
    state = _get_state(index)
    t1 = time.time()
    curve_names = get_curve_options(state)
    result = {}
    for name in curve_names:
        data = get_curve_data(state, name)
        if data is not None:
            result[name] = data
    t2 = time.time()
    print(f"[API] /api/curves/{index}/all 完成，返回 {len(result)} 条曲线，get_state耗时 {t1-t0:.2f}s，计算曲线耗时 {t2-t1:.2f}s，总耗时 {t2-t0:.2f}s")
    return result


@app.get("/api/curve/{index}/{curve_name:path}")
def get_curve(index: int, curve_name: str):
    """返回指定曲线的全帧数据 float 列表。"""
    state = _get_state(index)
    data = get_curve_data(state, curve_name)
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
