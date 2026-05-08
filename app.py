"""
Lance 可视化 FastAPI 服务

启动：uvicorn app:app --host 0.0.0.0 --port 8868
"""
from pathlib import Path
from collections import OrderedDict

import copy
import os
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.adapters import ViewerAdapter
from core.config import get_project_root, load_config
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
_project_root: Path = Path("/data")
_MAX_CACHE_SIZE = 10  # 最多缓存10个轨迹状态
_DEFAULT_SESSION_ID = "default"
_MAX_SESSION_COUNT = int(os.environ.get("DATASET_SESSION_LIMIT", "16"))
_SESSION_TTL_SECONDS = int(os.environ.get("DATASET_SESSION_TTL_SECONDS", "1800"))
_sessions: OrderedDict[str, dict] = OrderedDict()


@app.on_event("startup")
def startup():
    global _config, _project_root
    _config = load_config()
    _project_root = get_project_root(_config)
    session = _create_session(_config, session_id=_DEFAULT_SESSION_ID)
    adapter = session["adapter"]
    print(f"[startup] viewer adapter: {_config.get('viewer', {}).get('type', 'lance')}")
    print(f"[startup] 共 {adapter.total_items} 条轨迹")

    # 预加载默认轨迹到缓存，优化首次访问速度
    default_index = _config.get("defaults", {}).get("trajectory_index", 0)
    print(f"[startup] 预加载默认轨迹 {default_index}")
    _get_state(default_index, session_id=_DEFAULT_SESSION_ID)
    print(f"[startup] 预加载完成")


def _clone_config(config: dict) -> dict:
    return copy.deepcopy(config)


def _create_session(config: dict, session_id: str | None = None) -> dict:
    session_id = session_id or uuid.uuid4().hex[:12]
    session_config = _clone_config(config)
    adapter = create_viewer_adapter(session_config, _project_root)
    session = {
        "id": session_id,
        "config": session_config,
        "adapter": adapter,
        "state_cache": OrderedDict(),
        "last_access": time.time(),
    }
    _sessions[session_id] = session
    _sessions.move_to_end(session_id)
    _cleanup_sessions()
    return session


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [
        sid for sid, session in _sessions.items()
        if sid != _DEFAULT_SESSION_ID and now - session.get("last_access", now) > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _sessions[sid]
        print(f"[session] 清理过期数据源 session: {sid}")

    while len([sid for sid in _sessions if sid != _DEFAULT_SESSION_ID]) > _MAX_SESSION_COUNT:
        for sid in list(_sessions.keys()):
            if sid != _DEFAULT_SESSION_ID:
                del _sessions[sid]
                print(f"[session] 清理最旧数据源 session: {sid}")
                break


def _get_session(session_id: str | None = None) -> dict:
    sid = session_id or _DEFAULT_SESSION_ID
    if sid not in _sessions:
        base_config = _config or load_config()
        _create_session(base_config, session_id=sid)

    session = _sessions[sid]
    session["last_access"] = time.time()
    _sessions.move_to_end(sid)
    _cleanup_sessions()
    return session


def _get_state(index: int, session_id: str | None = None):
    """获取（或构建）指定轨迹状态，带LRU缓存。"""
    session = _get_session(session_id)
    adapter: ViewerAdapter = session["adapter"]
    state_cache: OrderedDict[int, object] = session["state_cache"]

    if index in state_cache:
        state_cache.move_to_end(index)
        return state_cache[index]

    t0 = time.time()
    print(f"[cache] session={session['id']} 开始加载轨迹 {index}")
    state = adapter.build_state(index)
    t1 = time.time()
    print(f"[cache] session={session['id']} 轨迹状态构建完成 {index}，耗时 {t1 - t0:.2f}s")

    state_cache[index] = state
    if len(state_cache) > _MAX_CACHE_SIZE:
        oldest = next(iter(state_cache))
        del state_cache[oldest]
        print(f"[cache] session={session['id']} 清理轨迹 {oldest}，当前缓存: {len(state_cache)}")

    return state


def _get_browser_roots() -> list[Path]:
    """返回允许前端浏览的数据根目录。"""
    raw_roots = os.environ.get("DATA_BROWSER_ROOTS", "")
    candidates: list[Path] = []

    if raw_roots:
        candidates.extend(Path(p.strip()) for p in raw_roots.split(":") if p.strip())
    else:
        candidates.append(Path("/data"))
        mnt_root = Path("/mnt")
        if mnt_root.exists():
            candidates.extend(
                child for child in mnt_root.iterdir()
                if child.is_dir() and child.name.startswith("nas")
            )

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.exists() or not resolved.is_dir():
            continue
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            roots.append(resolved)
    return roots


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_browser_path(path: str | None, *, must_exist: bool = True) -> Path:
    roots = _get_browser_roots()
    if not roots:
        raise HTTPException(status_code=400, detail="没有可浏览的数据挂载目录")

    target = Path(path).expanduser() if path else roots[0]
    if not target.is_absolute():
        target = roots[0] / target
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"路径无效: {exc}") from exc

    if not any(_is_under_root(resolved, root) for root in roots):
        raise HTTPException(status_code=403, detail="路径不在允许浏览的数据目录内")
    if must_exist and not resolved.exists():
        raise HTTPException(status_code=404, detail="路径不存在")
    return resolved


def _is_lance_path(path: Path) -> bool:
    return path.name.endswith(".lance")


def _make_dataset_response(session: dict) -> dict:
    adapter: ViewerAdapter = session["adapter"]
    config = session["config"]
    return {
        "session_id": session["id"],
        "lance_path": config.get("paths", {}).get("lance_dataset", ""),
        "total_items": adapter.total_items,
        "viewer_type": config.get("viewer", {}).get("type", "lance"),
        "browser_roots": [str(root) for root in _get_browser_roots()],
    }


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


class DatasetLoadPayload(BaseModel):
    lance_path: str
    session_id: str | None = None


@app.get("/api/dataset/current")
def get_current_dataset(session_id: str | None = None):
    """返回当前 Lance 数据源和可浏览根目录。"""
    session = _get_session(session_id)
    return _make_dataset_response(session)


@app.get("/api/dataset/browse")
def browse_dataset(path: str | None = None):
    """浏览允许的数据挂载目录，只暴露目录和 .lance 数据集。"""
    target = _resolve_browser_path(path, must_exist=True)
    if not target.is_dir() or _is_lance_path(target):
        target = target.parent

    roots = _get_browser_roots()
    entries = []
    try:
        children = sorted(
            target.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"无法读取目录: {exc}") from exc

    for child in children:
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        selectable = _is_lance_path(child)
        if not is_dir and not selectable:
            continue
        entries.append({
            "name": child.name,
            "path": str(child),
            "type": "lance" if selectable else "directory",
            "selectable": selectable,
        })

    parent = target.parent.resolve()
    parent_path = str(parent) if any(_is_under_root(parent, root) for root in roots) else None
    return {
        "path": str(target),
        "parent": parent_path,
        "roots": [str(root) for root in roots],
        "entries": entries,
    }


@app.post("/api/dataset/load")
def load_dataset(payload: DatasetLoadPayload):
    """切换 Lance 数据源，并重建 adapter/state cache。"""
    lance_path = _resolve_browser_path(payload.lance_path, must_exist=True)
    if not _is_lance_path(lance_path):
        raise HTTPException(status_code=400, detail="请选择 .lance 数据集路径")

    current_session = _get_session(payload.session_id)
    new_config = _clone_config(current_session["config"])
    new_config["paths"]["lance_dataset"] = str(lance_path)
    session_id = payload.session_id if payload.session_id and payload.session_id != _DEFAULT_SESSION_ID else uuid.uuid4().hex[:12]

    try:
        new_session = _create_session(new_config, session_id=session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Lance 数据源加载失败: {exc}") from exc

    print(f"[dataset] session={new_session['id']} 已切换 Lance 数据源: {lance_path}")
    return {
        **_make_dataset_response(new_session),
        "trajectories": new_session["adapter"].list_items(),
    }

@app.get("/api/trajectories")
def list_trajectories(session_id: str | None = None):
    """返回所有轨迹的列表，格式 [{label, index}, ...]。"""
    session = _get_session(session_id)
    adapter: ViewerAdapter = session["adapter"]
    print(f"[API] /api/trajectories 开始 session={session['id']}")
    options = adapter.list_items()
    print(f"[API] /api/trajectories 完成 session={session['id']}，返回 {len(options)} 条")
    return options


@app.get("/api/trajectory/{index}")
def get_trajectory_info(index: int, session_id: str | None = None):
    """返回指定轨迹的元数据。"""
    session = _get_session(session_id)
    return session["adapter"].get_item_info(index)


@app.get("/api/trajectory/{index}/load")
def load_trajectory(index: int, session_id: str | None = None):
    """
    预加载轨迹（构建状态）并返回基本信息。
    前端切换轨迹时调用，服务端会缓存计算结果。
    """
    session = _get_session(session_id)
    print(f"[API] /api/trajectory/{index}/load 开始 session={session['id']}")
    state = _get_state(index, session_id=session["id"])
    result = session["adapter"].get_load_payload(index, state)
    print(f"[API] /api/trajectory/{index}/load 完成 session={session['id']}，返回数据大小: {len(str(result))} 字节")
    return result


@app.get("/api/frame/{index}/{frame_idx}")
def get_frame(
    index: int,
    frame_idx: int,
    session_id: str | None = None,
    show_mano_mesh: bool = True,
    show_mano_joints: bool = False,
    show_urdf_joints: bool = False,
    show_urdf_mesh: bool = False,
    show_object: bool = True,
    show_origin: bool = False,
):
    """返回指定帧的 3D 数据（mesh/joints 顶点坐标 + faces 索引）。"""
    session = _get_session(session_id)
    state = _get_state(index, session_id=session["id"])
    return session["adapter"].get_frame_payload(
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
def get_object_mesh(index: int, session_id: str | None = None):
    """返回物体网格（只需加载一次）。"""
    session = _get_session(session_id)
    state = _get_state(index, session_id=session["id"])
    return session["adapter"].get_object_mesh_payload(state)


@app.get("/api/video/{index}/{cam_idx}/{frame_idx}")
def get_video_frame(
    index: int,
    cam_idx: int,
    frame_idx: int,
    stream: str = "color",
    session_id: str | None = None,
):
    """返回指定帧的视频图像（base64 data URI）。"""
    session = _get_session(session_id)
    payload = session["adapter"].get_video_frame_payload(index, cam_idx, frame_idx, stream)
    if payload is None:
        raise HTTPException(status_code=404, detail="视频帧不可用")
    return payload


@app.get("/api/curves/{index}")
def get_curves(index: int, session_id: str | None = None):
    """返回指定轨迹所有曲线选项名称。"""
    session = _get_session(session_id)
    state = _get_state(index, session_id=session["id"])
    return session["adapter"].get_curve_options(state)


@app.get("/api/curves/{index}/all")
def get_all_curves(index: int, session_id: str | None = None):
    """返回指定轨迹的所有曲线数据（批量）。"""
    import time

    t0 = time.time()
    session = _get_session(session_id)
    print(f"[API] /api/curves/{index}/all 开始 session={session['id']}")
    state = _get_state(index, session_id=session["id"])
    t1 = time.time()
    result = session["adapter"].get_all_curve_data(state)
    t2 = time.time()
    print(f"[API] /api/curves/{index}/all 完成 session={session['id']}，返回 {len(result)} 条曲线，get_state耗时 {t1-t0:.2f}s，计算曲线耗时 {t2-t1:.2f}s，总耗时 {t2-t0:.2f}s")
    return result


@app.get("/api/curve/{index}/{curve_name:path}")
def get_curve(index: int, curve_name: str, session_id: str | None = None):
    """返回指定曲线的全帧数据 float 列表。"""
    session = _get_session(session_id)
    state = _get_state(index, session_id=session["id"])
    data = session["adapter"].get_curve_data(state, curve_name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"曲线 '{curve_name}' 不存在")
    return {"name": curve_name, "data": data}

