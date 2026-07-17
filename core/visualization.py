"""
每帧 3D 可视化数据计算。

不依赖任何 ipywidgets / Plotly FigureWidget；
返回纯 Python dict，可直接序列化为 JSON 传给前端。
"""
from functools import lru_cache
from pathlib import Path
from threading import RLock

import numpy as np
import trimesh

from .mano import generate_mano_vertices, load_mano_faces, transform_mano_to_world
from .operator_identity import normalize_operator_key, normalize_operator_name
from .urdf_helper import URDFHelper


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _normalize_hand_name(name: str | None, fallback: str) -> str:
    value = str(name or "").lower()
    if "left" in value:
        return "left"
    if "right" in value:
        return "right"
    fallback_value = str(fallback or "").lower()
    if fallback_value in {"left", "right"}:
        return fallback_value
    return value or fallback_value or "right"


def _resolve_mano_model_path(mano_model_path: str, hand: str, project_root: Path) -> str:
    side = "LEFT" if hand == "left" else "RIGHT"
    requested = Path(mano_model_path) if mano_model_path else None
    candidates = [
        project_root / "assets" / "models" / f"MANO_{side}.pkl",
    ]
    if requested is not None:
        if requested.name:
            candidates.append(requested.with_name(f"MANO_{side}.pkl"))
        candidates.append(requested)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


def _resolve_urdf_path(project_root: Path, operator: str, hand: str) -> Path | None:
    operator_dir = project_root / "assets" / "operators" / normalize_operator_key(operator)
    if hand == "left":
        candidates = [
            operator_dir / "left" / "mano_hand.urdf",
            operator_dir / "mano_left_hand.urdf",
        ]
    else:
        candidates = [
            operator_dir / "right" / "mano_hand.urdf",
            operator_dir / "mano_right_hand.urdf",
            operator_dir / "mano_hand.urdf",
    ]
    return next((path for path in candidates if path.exists()), None)


@lru_cache(maxsize=128)
def _load_object_mesh_cached(project_root: str, object_name: str) -> dict | None:
    project_root_path = Path(project_root)
    objects_dir = project_root_path / "assets/objects"
    if not object_name or not objects_dir.exists():
        return None

    # 用 assets/objects 中的目录名做前缀匹配，兼容 cuboid2H → cuboid2 等变体
    known = sorted([d.name for d in objects_dir.iterdir() if d.is_dir()], key=len, reverse=True)
    matched = next((n for n in known if object_name.startswith(n)), None) or object_name
    obj_paths = [
        objects_dir / matched / f"{matched}_aligned.stl",
        objects_dir / f"{matched}_aligned.stl",
    ]
    for obj_path in obj_paths:
        if obj_path.exists():
            try:
                mesh = trimesh.load(str(obj_path))
                mesh.vertices = mesh.vertices * 0.001  # mm → m
                return {
                    "vertices": np.asarray(mesh.vertices, dtype=np.float32),
                    "faces": np.asarray(mesh.faces, dtype=np.int32),
                }
            except Exception:
                pass
    return None


@lru_cache(maxsize=256)
def _object_mesh_exists_cached(project_root: str, object_name: str) -> bool:
    project_root_path = Path(project_root)
    _, candidates = _object_mesh_candidates(project_root_path, object_name)
    return any(path.exists() for path in candidates)


class LazyObjectMesh:
    """延迟加载物体 mesh，只在真正请求时读磁盘。"""

    def __init__(self, project_root: Path, object_name: str):
        self.project_root = project_root
        self.object_name = object_name

    def exists(self) -> bool:
        return _object_mesh_exists_cached(str(self.project_root), self.object_name)

    def get(self) -> dict | None:
        return _load_object_mesh_cached(str(self.project_root), self.object_name)


def _load_object_mesh(project_root: Path, object_name: str) -> dict | None:
    return _load_object_mesh_cached(str(project_root), object_name)


def object_has_mesh(obj: dict) -> bool:
    mesh = obj.get("mesh")
    if hasattr(mesh, "exists"):
        return bool(mesh.exists())
    return mesh is not None


def object_mesh_data(obj: dict) -> dict | None:
    mesh = obj.get("mesh")
    if hasattr(mesh, "get"):
        return mesh.get()
    return mesh


def _object_mesh_candidates(project_root: Path, object_name: str) -> tuple[str, list[Path]]:
    objects_dir = project_root / "assets/objects"
    if not object_name or not objects_dir.exists():
        return object_name, []

    # 用 assets/objects 中的目录名做前缀匹配，兼容 cuboid2H → cuboid2 等变体
    known = sorted([d.name for d in objects_dir.iterdir() if d.is_dir()], key=len, reverse=True)
    matched = next((n for n in known if object_name.startswith(n)), None) or object_name
    return matched, [
        objects_dir / matched / f"{matched}_aligned.stl",
        objects_dir / f"{matched}_aligned.stl",
    ]


def _mesh_payload(vertices: np.ndarray, faces: np.ndarray) -> dict:
    return {
        "x": vertices[:, 0].tolist(),
        "y": vertices[:, 1].tolist(),
        "z": vertices[:, 2].tolist(),
        "i": faces[:, 0].tolist(),
        "j": faces[:, 1].tolist(),
        "k": faces[:, 2].tolist(),
    }


class TrajectoryState:
    """
    持有单条轨迹的所有预计算数据。
    FastAPI 启动时或切换轨迹时创建一个实例并缓存。
    """

    def __init__(
        self,
        lance_row: dict,
        mano_model_path: str,
        hand: str,
        project_root: Path,
    ):
        self.payload_lock = RLock()
        index_data = dict(lance_row.get("index") or {})
        meta = dict(lance_row.get("trajectory_metadata") or {})
        object_names = _as_list(meta.get("object_names"))

        self.index_data = {
            "scene": index_data.get("scene", ""),
            "operator": index_data.get("operator", ""),
            "uuid": index_data.get("uuid", ""),
            "file_uuid": index_data.get("file_uuid", ""),
            "capMachine": index_data.get("capMachine", "unknown"),
        }
        self.hand = _normalize_hand_name(hand, "right")
        self.hands: list[dict] = []
        self.objects: list[dict] = []

        hand_rows = _as_list(lance_row.get("hands"))
        hand_names = _as_list(meta.get("hand_names"))
        mano_shapes = _as_list(meta.get("mano_hand_shapes"))
        operator = normalize_operator_name(self.index_data.get("operator", ""))

        for idx, hand_row in enumerate(hand_rows):
            hand_name = _normalize_hand_name(
                hand_names[idx] if idx < len(hand_names) else None,
                self.hand if idx == 0 else "right",
            )
            mano_beta = np.array(
                mano_shapes[idx] if idx < len(mano_shapes) else (mano_shapes[0] if mano_shapes else [0.0] * 10),
                dtype=np.float32,
            )
            mano_joint_pos = np.array(hand_row["mano_joint_pos"], dtype=np.float32)
            T = mano_joint_pos.shape[0]
            mano_joints = mano_joint_pos.reshape(T, 21, 3)
            global_orient = np.array(hand_row["mano_global_rot_aa"], dtype=np.float32)
            transl = np.array(hand_row["mano_global_pos"], dtype=np.float32)
            hand_pose = np.array(hand_row["mano_hand_pose"], dtype=np.float32)

            model_path = _resolve_mano_model_path(mano_model_path, hand_name, project_root)
            hand_state = {
                "name": hand_name,
                "mano_joints": mano_joints,
                "global_orient": global_orient,
                "transl": transl,
                "mano_vertices": generate_mano_vertices(model_path, hand_name, mano_beta, hand_pose, T),
                "mano_faces": load_mano_faces(model_path),
                "urdf_dof": np.array(hand_row["urdf_dof"], dtype=np.float32),
                "urdf_helper": None,
            }

            urdf_path = _resolve_urdf_path(project_root, operator, hand_name)
            if urdf_path is not None:
                helper = URDFHelper(str(urdf_path))
                if helper.model is not None:
                    hand_state["urdf_helper"] = helper

            self.hands.append(hand_state)

        if not self.hands:
            raise ValueError("Lance row does not contain any hand data")

        self.hand_names = [h["name"] for h in self.hands]
        self.T = min(h["mano_joints"].shape[0] for h in self.hands)

        # 兼容旧的单手字段访问：曲线模块和旧 payload 默认使用第一只手。
        first_hand = self.hands[0]
        self.mano_joints = first_hand["mano_joints"]
        self.global_orient = first_hand["global_orient"]
        self.transl = first_hand["transl"]
        self.mano_vertices = first_hand["mano_vertices"]
        self.mano_faces = first_hand["mano_faces"]
        self.urdf_dof = first_hand["urdf_dof"]
        self.urdf_helper: URDFHelper | None = first_hand["urdf_helper"]

        object_names = _as_list(meta.get("object_names"))
        for idx, object_row in enumerate(_as_list(lance_row.get("objects"))):
            object_name = str(object_names[idx] if idx < len(object_names) else f"object_{idx}")
            self.objects.append({
                "name": object_name,
                "pos": np.array(object_row["pos"], dtype=np.float32),
                "rot_aa": np.array(object_row["rot_aa"], dtype=np.float32),
                "mesh": LazyObjectMesh(project_root, object_name),
            })

        self.primary_object_idx = next(
            (idx for idx, obj in enumerate(self.objects) if object_has_mesh(obj)),
            0,
        )
        self.scene = self.index_data["scene"]
        self.trajectory_metadata = {
            "total_frames": meta.get("total_frames", self.T),
            "hand_names": hand_names,
            "mano_hand_shapes": mano_shapes,
            "object_names": object_names,
            "trajectory_info": meta.get("trajectory_info") or {},
        }
        self.lance_row = {
            "index": self.index_data,
            "trajectory_metadata": self.trajectory_metadata,
        }
        if "cma_data" in lance_row:
            self.lance_row["cma_data"] = lance_row["cma_data"]
        self.object_mesh: dict | None = None
        if self.objects:
            primary_object = self.objects[self.primary_object_idx]
            self.obj_pos = primary_object["pos"]
            self.obj_rot_aa = primary_object["rot_aa"]
        else:
            self.obj_pos = np.zeros((self.T, 3), dtype=np.float32)
            self.obj_rot_aa = np.zeros((self.T, 3), dtype=np.float32)


def get_frame_data(
    state: TrajectoryState,
    frame_idx: int,
    show_mano_mesh: bool = True,
    show_mano_joints: bool = False,
    show_urdf_joints: bool = False,
    show_urdf_mesh: bool = False,
    show_object: bool = True,
    show_origin: bool = False,
) -> dict:
    """
    计算指定帧的所有 3D 数据，返回可 JSON 序列化的 dict。

    结构：
    {
        "frame_idx": int,
        "total_frames": int,
        "scene": str,
        "mano_mesh":   {"x", "y", "z", "i", "j", "k"} | None,
        "mano_joints": {"x", "y", "z", "names"}        | None,
        "urdf_joints": {"x", "y", "z", "names"}        | None,
        "urdf_meshes": [{"x", "y", "z", "i", "j", "k"}, ...]  | None,
        "object_mesh": {"x", "y", "z", "i", "j", "k"} | None,
        "show_origin": bool,
    }
    """
    frame_idx = max(0, min(frame_idx, state.T - 1))
    result: dict = {
        "frame_idx": frame_idx,
        "total_frames": state.T,
        "scene": state.scene,
        "hands": [],
        "mano_mesh": None,
        "mano_joints": None,
        "urdf_joints": None,
        "urdf_meshes": None,
        "object_mesh": None,
        "object_poses": [],
        "object_pose": None,
        "show_origin": show_origin,
    }

    for hand_state in state.hands:
        hand_payload = {
            "name": hand_state["name"],
            "mano_mesh": None,
            "mano_joints": None,
            "urdf_joints": None,
            "urdf_meshes": None,
        }

        world_joints = None
        if show_mano_mesh or show_mano_joints:
            vw, world_joints = transform_mano_to_world(
                hand_state["mano_vertices"][frame_idx],
                hand_state["mano_joints"][frame_idx],
                hand_state["global_orient"][frame_idx],
                hand_state["transl"][frame_idx],
            )
            if show_mano_mesh:
                hand_payload["mano_mesh"] = _mesh_payload(vw, hand_state["mano_faces"])

        if show_mano_joints and world_joints is not None:
            hand_payload["mano_joints"] = {
                "x": world_joints[:, 0].tolist(),
                "y": world_joints[:, 1].tolist(),
                "z": world_joints[:, 2].tolist(),
                "names": [f"{hand_state['name']} Joint {i}" for i in range(21)],
            }

        urdf_helper = hand_state["urdf_helper"]
        if urdf_helper and (show_urdf_joints or show_urdf_mesh):
            urdf_helper.forward_kinematics(hand_state["urdf_dof"][frame_idx])

            if show_urdf_joints:
                pts = urdf_helper.extract_joint_positions()
                if pts is not None:
                    hand_payload["urdf_joints"] = {
                        "x": pts[:, 0].tolist(),
                        "y": pts[:, 1].tolist(),
                        "z": pts[:, 2].tolist(),
                        "names": [f"{hand_state['name']} URDF {n}" for n in urdf_helper.get_joint_names()],
                    }

            if show_urdf_mesh:
                hand_payload["urdf_meshes"] = [
                    _mesh_payload(m["vertices"], m["faces"])
                    for m in urdf_helper.get_transformed_meshes()
                ]

        result["hands"].append(hand_payload)

    # 兼容旧前端字段：默认映射第一只手。
    if result["hands"]:
        first = result["hands"][0]
        result["mano_mesh"] = first["mano_mesh"]
        result["mano_joints"] = first["mano_joints"]
        result["urdf_joints"] = first["urdf_joints"]
        result["urdf_meshes"] = first["urdf_meshes"]

    # Object mesh
    if show_object:
        for obj in state.objects:
            has_mesh = object_has_mesh(obj)
            result["object_poses"].append({
                "name": obj["name"],
                "pos": obj["pos"][frame_idx].tolist(),
                "rot_aa": obj["rot_aa"][frame_idx].tolist(),
                "has_mesh": has_mesh,
            })

        if state.objects:
            primary = state.objects[state.primary_object_idx]
            has_mesh = object_has_mesh(primary)
            primary_pose = {
                "pos": primary["pos"][frame_idx].tolist(),
                "rot_aa": primary["rot_aa"][frame_idx].tolist(),
                "name": primary["name"],
                "has_mesh": has_mesh,
            }
            result["object_pose"] = primary_pose
            if has_mesh:
                result["object_transform"] = {
                    "position": primary_pose["pos"],
                    "rotation": primary_pose["rot_aa"],
                }

    return result
