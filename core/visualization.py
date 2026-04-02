"""
每帧 3D 可视化数据计算。

不依赖任何 ipywidgets / Plotly FigureWidget；
返回纯 Python dict，可直接序列化为 JSON 传给前端。
"""
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from .mano import generate_mano_vertices, load_mano_faces, transform_mano_to_world
from .urdf_helper import URDFHelper


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
        hands = lance_row["hands"][0]
        objects = lance_row["objects"][0]

        self.lance_row = lance_row
        self.hand = hand

        # MANO
        mano_beta = np.array(
            lance_row["trajectory_metadata"]["mano_hand_shapes"][0], dtype=np.float32
        )
        mano_joint_pos = np.array(hands["mano_joint_pos"], dtype=np.float32)
        self.T = mano_joint_pos.shape[0]
        self.mano_joints = mano_joint_pos.reshape(self.T, 21, 3)
        self.global_orient = np.array(hands["mano_global_rot_aa"], dtype=np.float32)
        self.transl = np.array(hands["mano_global_pos"], dtype=np.float32)
        hand_pose = np.array(hands["mano_hand_pose"], dtype=np.float32)

        self.mano_vertices = generate_mano_vertices(
            mano_model_path, hand, mano_beta, hand_pose, self.T
        )
        self.mano_faces = load_mano_faces(mano_model_path)

        # URDF
        self.urdf_dof = np.array(hands["urdf_dof"], dtype=np.float32)
        operator = lance_row["index"]["operator"]
        urdf_path = project_root / f"assets/operators/{operator}/mano_hand.urdf"
        self.urdf_helper: URDFHelper | None = None
        if urdf_path.exists():
            h = URDFHelper(str(urdf_path))
            if h.model is not None:
                self.urdf_helper = h

        # Object
        self.obj_pos = np.array(objects["pos"], dtype=np.float32)
        self.obj_rot_aa = np.array(objects["rot_aa"], dtype=np.float32)
        self.object_mesh: dict | None = None
        object_name = lance_row["trajectory_metadata"]["object_names"][0]
        for obj_path in [
            project_root / f"assets/objects/{object_name}/{object_name}_aligned.stl",
            project_root / f"assets/objects/{object_name}_aligned.stl",
            project_root / f"assets/objects/{object_name}/{object_name}.stl",
            project_root / f"assets/objects/{object_name}.stl",
        ]:
            if obj_path.exists():
                try:
                    mesh = trimesh.load(str(obj_path))
                    mesh.vertices = mesh.vertices * 0.001  # mm → m
                    self.object_mesh = {
                        "vertices": np.asarray(mesh.vertices, dtype=np.float32),
                        "faces": np.asarray(mesh.faces, dtype=np.int32),
                    }
                    break
                except Exception:
                    pass


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
        "scene": state.lance_row["index"]["scene"],
        "mano_mesh": None,
        "mano_joints": None,
        "urdf_joints": None,
        "urdf_meshes": None,
        "object_mesh": None,
        "show_origin": show_origin,
    }

    # MANO mesh
    if show_mano_mesh:
        vw, jw = transform_mano_to_world(
            state.mano_vertices[frame_idx],
            state.mano_joints[frame_idx],
            state.global_orient[frame_idx],
            state.transl[frame_idx],
        )
        result["mano_mesh"] = {
            "x": vw[:, 0].tolist(),
            "y": vw[:, 1].tolist(),
            "z": vw[:, 2].tolist(),
            "i": state.mano_faces[:, 0].tolist(),
            "j": state.mano_faces[:, 1].tolist(),
            "k": state.mano_faces[:, 2].tolist(),
        }

    # MANO joints
    if show_mano_joints:
        _, jw = transform_mano_to_world(
            state.mano_vertices[frame_idx],
            state.mano_joints[frame_idx],
            state.global_orient[frame_idx],
            state.transl[frame_idx],
        )
        result["mano_joints"] = {
            "x": jw[:, 0].tolist(),
            "y": jw[:, 1].tolist(),
            "z": jw[:, 2].tolist(),
            "names": [f"Joint {i}" for i in range(21)],
        }

    # URDF
    if state.urdf_helper and (show_urdf_joints or show_urdf_mesh):
        state.urdf_helper.forward_kinematics(state.urdf_dof[frame_idx])

        if show_urdf_joints:
            pts = state.urdf_helper.extract_joint_positions()
            if pts is not None:
                result["urdf_joints"] = {
                    "x": pts[:, 0].tolist(),
                    "y": pts[:, 1].tolist(),
                    "z": pts[:, 2].tolist(),
                    "names": [f"URDF {n}" for n in state.urdf_helper.get_joint_names()],
                }

        if show_urdf_mesh:
            meshes = state.urdf_helper.get_transformed_meshes()
            result["urdf_meshes"] = [
                {
                    "x": m["vertices"][:, 0].tolist(),
                    "y": m["vertices"][:, 1].tolist(),
                    "z": m["vertices"][:, 2].tolist(),
                    "i": m["faces"][:, 0].tolist(),
                    "j": m["faces"][:, 1].tolist(),
                    "k": m["faces"][:, 2].tolist(),
                }
                for m in meshes
            ]

    # Object mesh
    if show_object and state.object_mesh:
        result["object_transform"] = {
            "position": state.obj_pos[frame_idx].tolist(),
            "rotation": state.obj_rot_aa[frame_idx].tolist(),
        }

    return result
