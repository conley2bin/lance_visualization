import pickle
from pathlib import Path

import numpy as np
import torch
from manotorch.manolayer import ManoLayer
from scipy.spatial.transform import Rotation


def generate_mano_vertices(
    mano_model_path: str,
    hand: str,
    beta: np.ndarray,
    hand_pose: np.ndarray,
    T: int,
) -> np.ndarray:
    """生成 MANO 顶点（模板空间），shape (T, V, 3)。"""
    mano_assets_root = str(Path(mano_model_path).parent.parent)
    mano_layer = ManoLayer(
        mano_assets_root=mano_assets_root,
        use_pca=False,
        flat_hand_mean=True,
        side=hand,
    )
    beta_batch = torch.from_numpy(beta).float().unsqueeze(0).repeat(T, 1)
    hand_pose_t = torch.from_numpy(hand_pose).float()
    with torch.no_grad():
        output = mano_layer(hand_pose_t, beta_batch)
        vertices_template = output.verts.cpu().numpy()
    return vertices_template.astype(np.float32)


def load_mano_faces(mano_model_path: str) -> np.ndarray:
    """从 MANO pkl 文件加载 faces，shape (F, 3)。"""
    with open(mano_model_path, "rb") as f:
        mano_data = pickle.load(f, encoding="latin1")
    return mano_data["f"]


def transform_mano_to_world(
    vertices: np.ndarray,
    joints: np.ndarray,
    global_orient: np.ndarray,
    transl: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """将单帧 MANO 从模板空间变换到世界空间。"""
    rot_matrix = Rotation.from_rotvec(global_orient).as_matrix()
    vertices_world = (rot_matrix @ vertices.T).T + transl
    joints_world = (rot_matrix @ joints.T).T + transl
    return vertices_world, joints_world
