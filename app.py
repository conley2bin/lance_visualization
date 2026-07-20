"""
Lance 可视化 FastAPI 服务

启动：uvicorn app:app --host 0.0.0.0 --port 8868
"""
from pathlib import Path
from collections import OrderedDict
from threading import Lock

import copy
import os
import subprocess
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
_MAX_CACHE_SIZE = int(os.environ.get("VIZ_STATE_CACHE_SIZE", "16"))
_DEFAULT_SESSION_ID = "default"
_MAX_SESSION_COUNT = int(os.environ.get("DATASET_SESSION_LIMIT", "8"))
_SESSION_TTL_SECONDS = int(os.environ.get("DATASET_SESSION_TTL_SECONDS", "1800"))
_sessions: OrderedDict[str, dict] = OrderedDict()
_state_cache: OrderedDict[tuple, object] = OrderedDict()
_state_build_lock_registry: dict[tuple, Lock] = {}
_state_build_lock_registry_lock = Lock()
_assets_version: str | None = None


@app.on_event("startup")
def startup():
    global _config, _project_root, _assets_version
    _config = load_config()
    _project_root = get_project_root(_config)
    _assets_version = _read_assets_version()
    session = _create_session(_build_empty_dataset_config(_config), session_id=_DEFAULT_SESSION_ID)
    adapter = session["adapter"]
    print(f"[startup] viewer adapter: {_config.get('viewer', {}).get('type', 'lance')}")
    print(f"[startup] 共 {adapter.total_items} 条轨迹")

    # 预加载默认轨迹到缓存，优化首次访问速度
    default_index = _config.get("defaults", {}).get("trajectory_index", 0)
    if adapter.total_items > 0:
        print(f"[startup] 预加载默认轨迹 {default_index}")
        _get_state(default_index, session_id=_DEFAULT_SESSION_ID)
        print(f"[startup] 预加载完成")
    else:
        print("[startup] 默认不加载任何 Lance 数据集")


def _clone_config(config: dict) -> dict:
    return copy.deepcopy(config)


def _build_empty_dataset_config(config: dict) -> dict:
    empty_config = _clone_config(config)
    empty_config.setdefault("paths", {})["lance_dataset"] = ""
    return empty_config


def _create_session(config: dict, session_id: str | None = None) -> dict:
    session_id = session_id or uuid.uuid4().hex[:12]
    session_config = _clone_config(config)
    adapter = create_viewer_adapter(session_config, _project_root)
    session = {
        "id": session_id,
        "config": session_config,
        "adapter": adapter,
        "last_access": time.time(),
    }
    _sessions[session_id] = session
    _sessions.move_to_end(session_id)
    _cleanup_sessions()
    return session


def _session_dataset_fingerprint(session: dict) -> str:
    adapter = session.get("adapter")
    loader = getattr(adapter, "loader", None)
    return str(getattr(loader, "dataset_fingerprint", ""))


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


def _assets_path() -> Path:
    return _project_root / "assets"


def _read_assets_version() -> str:
    assets = _assets_path()
    if not assets.exists():
        return f"missing:{assets}"

    try:
        proc = subprocess.run(
            ["git", "-C", str(assets), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        commit = proc.stdout.strip()
        if commit:
            return f"git:{commit}"
    except Exception:
        pass

    try:
        return f"mtime:{assets.stat().st_mtime_ns}"
    except OSError:
        return f"unknown:{assets}"


def _clear_state_caches() -> int:
    with _state_build_lock_registry_lock:
        cleared = len(_state_cache)
        _state_cache.clear()
        _state_build_lock_registry.clear()
        return cleared


def _ensure_assets_version_current() -> tuple[str, bool]:
    global _assets_version
    current = _read_assets_version()
    if _assets_version is None:
        _assets_version = current
        return current, False
    if current == _assets_version:
        return current, False

    previous = _assets_version
    _assets_version = current
    cleared = _clear_state_caches()
    print(f"[assets] version changed: {previous} -> {current}; cleared {cleared} cached trajectory states")
    return current, True


def _get_session(session_id: str | None = None) -> dict:
    sid = session_id or _DEFAULT_SESSION_ID
    if sid not in _sessions:
        base_config = _build_empty_dataset_config(_config or load_config())
        _create_session(base_config, session_id=sid)

    session = _sessions[sid]
    session["last_access"] = time.time()
    _sessions.move_to_end(sid)
    _cleanup_sessions()
    return session


def _state_cache_key(session: dict, index: int) -> tuple:
    config = session["config"]
    paths = config.get("paths", {})
    defaults = config.get("defaults", {})
    return (
        config.get("viewer", {}).get("type", "lance"),
        paths.get("lance_dataset", ""),
        _session_dataset_fingerprint(session),
        paths.get("mano_model", ""),
        defaults.get("hand", "right"),
        str(_project_root),
        _assets_version or "",
        int(index),
    )


def _get_state(index: int, session_id: str | None = None):
    """获取（或构建）指定轨迹状态，带LRU缓存。"""
    _ensure_assets_version_current()
    session = _get_session(session_id)
    adapter: ViewerAdapter = session["adapter"]
    key = _state_cache_key(session, index)

    with _state_build_lock_registry_lock:
        if key in _state_cache:
            _state_cache.move_to_end(key)
            return _state_cache[key]
        lock = _state_build_lock_registry.get(key)
        if lock is None:
            lock = Lock()
            _state_build_lock_registry[key] = lock

    with lock:
        with _state_build_lock_registry_lock:
            if key in _state_cache:
                _state_cache.move_to_end(key)
                return _state_cache[key]

        t0 = time.time()
        print(f"[cache] session={session['id']} 开始加载轨迹 {index}")
        state = adapter.build_state(index)
        t1 = time.time()
        print(f"[cache] session={session['id']} 轨迹状态构建完成 {index}，耗时 {t1 - t0:.2f}s")

        with _state_build_lock_registry_lock:
            _state_cache[key] = state
            _state_cache.move_to_end(key)
            if len(_state_cache) > _MAX_CACHE_SIZE:
                oldest = next(iter(_state_cache))
                del _state_cache[oldest]
                _state_build_lock_registry.pop(oldest, None)
                print(f"[cache] 清理共享轨迹缓存 index={oldest[-1]}，当前缓存: {len(_state_cache)}")

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
        "dataset_fingerprint": _session_dataset_fingerprint(session),
        "total_items": adapter.total_items,
        "default_trajectory_index": config.get("defaults", {}).get("trajectory_index", 0),
        "viewer_type": config.get("viewer", {}).get("type", "lance"),
        "browser_roots": [str(root) for root in _get_browser_roots()],
    }


def _get_database_dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("DEXSTREAM_DATABASE_URL")
    if dsn:
        return dsn

    host = os.getenv("DB_HOST")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    port = os.getenv("DB_PORT", "15432")
    if host and user and password and db_name:
        return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    raise RuntimeError("未配置数据库连接，请设置 DATABASE_URL 或 DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD")


def _ensure_dataset_selected(session: dict) -> None:
    lance_path = session["config"].get("paths", {}).get("lance_dataset", "")
    if not lance_path:
        raise HTTPException(status_code=400, detail="请先选择 Lance 数据源")


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


class DatasetLoadPayload(BaseModel):
    lance_path: str
    session_id: str | None = None
    include_trajectories: bool = True


class RecentDatasetNamespaceBinding(BaseModel):
    schema_name: str
    display_name: str


class RecentDatasetItem(BaseModel):
    dataset_path: str
    dataset_name: str
    source_schema: str | None = None
    created_at: str | None = None
    is_namespace_bound: bool = False
    namespace_bindings: list[RecentDatasetNamespaceBinding] = Field(default_factory=list)


class RecentDatasetsResponse(BaseModel):
    items: list[RecentDatasetItem]


@app.get("/api/assets/version")
def get_assets_version():
    """返回当前 assets 版本；如检测到变化，会清理轨迹状态缓存。"""
    version, changed = _ensure_assets_version_current()
    return {
        "version": version,
        "changed": changed,
    }


@app.get("/api/dataset/current")
def get_current_dataset(session_id: str | None = None):
    """返回当前 Lance 数据源和可浏览根目录。"""
    session = _get_session(session_id)
    return _make_dataset_response(session)


@app.get("/api/dataset/recent", response_model=RecentDatasetsResponse)
def get_recent_datasets():
    """从 public.lance_record 返回最近可选的 Lance 数据集路径。"""
    import psycopg2

    dsn = _get_database_dsn()
    conn = psycopg2.connect(dsn, connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    TRIM(params.info->>'lance_path') AS lance_path,
                    ns.schema_name,
                    ns.display_name
                FROM public.system_params params
                JOIN public.namespace ns
                  ON params.name = 'processing.daily_schedule.' || ns.schema_name
                WHERE LOWER(COALESCE(params.info->>'enabled', 'false')) = 'true'
                  AND NULLIF(TRIM(params.info->>'lance_path'), '') IS NOT NULL
                ORDER BY ns.display_name ASC, ns.schema_name ASC
                """
            )
            schedule_rows = cur.fetchall()

            cur.execute(
                """
                SELECT dataset_path, dataset_name, source_schema, created_at
                FROM (
                    SELECT
                        dataset_path,
                        dataset_name,
                        source_schema,
                        created_at,
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY dataset_path
                            ORDER BY created_at DESC, id DESC
                        ) AS rn
                    FROM public.lance_record
                    WHERE dataset_path IS NOT NULL
                      AND dataset_path <> ''
                ) ranked
                WHERE rn = 1
                ORDER BY created_at DESC, dataset_path ASC
                LIMIT 300
                """
            )
            rows = cur.fetchall()
    except Exception:
        return RecentDatasetsResponse(items=[])
    finally:
        conn.close()

    namespace_bindings_by_path: dict[str, list[RecentDatasetNamespaceBinding]] = {}
    for lance_path, schema_name, display_name in schedule_rows:
        try:
            resolved = _resolve_browser_path(lance_path, must_exist=True)
        except HTTPException:
            continue
        if not _is_lance_path(resolved):
            continue
        namespace_bindings_by_path.setdefault(str(resolved), []).append(
            RecentDatasetNamespaceBinding(
                schema_name=schema_name,
                display_name=display_name or schema_name,
            )
        )

    items: list[RecentDatasetItem] = []
    seen_paths: set[str] = set()
    for dataset_path, dataset_name, source_schema, created_at in rows:
        try:
            resolved = _resolve_browser_path(dataset_path, must_exist=True)
        except HTTPException:
            continue
        if not _is_lance_path(resolved):
            continue
        resolved_path = str(resolved)
        bindings = namespace_bindings_by_path.get(resolved_path, [])
        seen_paths.add(resolved_path)
        items.append(
            RecentDatasetItem(
                dataset_path=resolved_path,
                dataset_name=dataset_name or resolved.name,
                source_schema=source_schema,
                created_at=created_at.isoformat() if created_at else None,
                is_namespace_bound=bool(bindings),
                namespace_bindings=bindings,
            )
        )

    for dataset_path, bindings in namespace_bindings_by_path.items():
        if dataset_path in seen_paths:
            continue
        items.append(
            RecentDatasetItem(
                dataset_path=dataset_path,
                dataset_name=Path(dataset_path).name,
                source_schema=bindings[0].schema_name if bindings else None,
                created_at=None,
                is_namespace_bound=True,
                namespace_bindings=bindings,
            )
        )

    bound_items = [item for item in items if item.is_namespace_bound]
    unbound_items = [item for item in items if not item.is_namespace_bound]
    return RecentDatasetsResponse(items=bound_items + unbound_items)


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
    result = _make_dataset_response(new_session)
    if payload.include_trajectories:
        result["trajectories"] = new_session["adapter"].list_items()
    return result

@app.get("/api/trajectories")
def list_trajectories(session_id: str | None = None):
    """返回所有轨迹的列表，格式 [{label, index}, ...]。"""
    session = _get_session(session_id)
    _ensure_dataset_selected(session)
    adapter: ViewerAdapter = session["adapter"]
    print(f"[API] /api/trajectories 开始 session={session['id']}")
    options = adapter.list_items()
    print(f"[API] /api/trajectories 完成 session={session['id']}，返回 {len(options)} 条")
    return options


@app.get("/api/trajectories/progress")
def get_trajectory_list_progress(session_id: str | None = None):
    """返回轨迹列表构建进度，不返回半成品列表。"""
    session = _get_session(session_id)
    _ensure_dataset_selected(session)
    adapter: ViewerAdapter = session["adapter"]
    return adapter.get_trajectory_list_progress()


@app.get("/api/trajectory/{index}")
def get_trajectory_info(index: int, session_id: str | None = None):
    """返回指定轨迹的元数据。"""
    session = _get_session(session_id)
    _ensure_dataset_selected(session)
    return session["adapter"].get_item_info(index)


@app.get("/api/trajectory/{index}/load")
def load_trajectory(index: int, session_id: str | None = None):
    """
    预加载轨迹（构建状态）并返回基本信息。
    前端切换轨迹时调用，服务端会缓存计算结果。
    """
    session = _get_session(session_id)
    _ensure_dataset_selected(session)
    print(f"[API] /api/trajectory/{index}/load 开始 session={session['id']}")
    state = _get_state(index, session_id=session["id"])
    result = session["adapter"].get_load_payload(index, state)
    result["assets_version"] = _assets_version
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
    _ensure_dataset_selected(session)
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
    _ensure_dataset_selected(session)
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
    _ensure_dataset_selected(session)
    payload = session["adapter"].get_video_frame_payload(index, cam_idx, frame_idx, stream)
    if payload is None:
        raise HTTPException(status_code=404, detail="视频帧不可用")
    return payload


@app.get("/api/cma/{index}/{frame_idx}")
def get_cma_frame(index: int, frame_idx: int, session_id: str | None = None):
    """返回指定帧的原始 CMA 数据；缺失时返回 available=false。"""
    session = _get_session(session_id)
    _ensure_dataset_selected(session)
    state = _get_state(index, session_id=session["id"])
    return session["adapter"].get_cma_frame_payload(state, frame_idx)


@app.get("/api/curves/{index}")
def get_curves(index: int, session_id: str | None = None):
    """返回指定轨迹所有曲线选项名称。"""
    session = _get_session(session_id)
    _ensure_dataset_selected(session)
    state = _get_state(index, session_id=session["id"])
    return session["adapter"].get_curve_options(state)


@app.get("/api/curves/{index}/all")
def get_all_curves(index: int, session_id: str | None = None):
    """返回指定轨迹的所有曲线数据（批量）。"""
    import time

    t0 = time.time()
    session = _get_session(session_id)
    _ensure_dataset_selected(session)
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
    _ensure_dataset_selected(session)
    state = _get_state(index, session_id=session["id"])
    data = session["adapter"].get_curve_data(state, curve_name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"曲线 '{curve_name}' 不存在")
    return {"name": curve_name, "data": data}
