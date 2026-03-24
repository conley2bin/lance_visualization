"""
曲线数据提取，对应 notebook 的 get_curve_options / get_curve_data。
"""
import re

import numpy as np

from .visualization import TrajectoryState


def get_curve_options(state: TrajectoryState) -> list[str]:
    """返回所有可绘制曲线的名称列表。"""
    options = [
        "mano.global_pos.x",
        "mano.global_pos.y",
        "mano.global_pos.z",
        "mano.global_rot_aa.x",
        "mano.global_rot_aa.y",
        "mano.global_rot_aa.z",
    ]
    for j in range(21):
        options += [
            f"mano.joint[{j}].pos.x",
            f"mano.joint[{j}].pos.y",
            f"mano.joint[{j}].pos.z",
        ]
    if state.urdf_helper and state.urdf_helper.model:
        for d in range(state.urdf_helper.model.nq):
            options.append(f"urdf.dof[{d}]")
    options += [
        "object.pos.x", "object.pos.y", "object.pos.z",
        "object.rot_aa.x", "object.rot_aa.y", "object.rot_aa.z",
    ]
    return options


def get_curve_data(state: TrajectoryState, curve_name: str) -> list[float] | None:
    """返回指定曲线的全帧数据（float list），找不到返回 None。"""
    axis_map = {"x": 0, "y": 1, "z": 2}

    m = re.match(r"mano\.global_pos\.([xyz])", curve_name)
    if m:
        return state.transl[:, axis_map[m.group(1)]].tolist()

    m = re.match(r"mano\.global_rot_aa\.([xyz])", curve_name)
    if m:
        return state.global_orient[:, axis_map[m.group(1)]].tolist()

    m = re.match(r"mano\.joint\[(\d+)\]\.pos\.([xyz])", curve_name)
    if m:
        j, ax = int(m.group(1)), m.group(2)
        if j < 21:
            return state.mano_joints[:, j, axis_map[ax]].tolist()

    m = re.match(r"urdf\.dof\[(\d+)\]", curve_name)
    if m:
        d = int(m.group(1))
        if state.urdf_helper and d < state.urdf_dof.shape[1]:
            return state.urdf_dof[:, d].tolist()

    m = re.match(r"object\.pos\.([xyz])", curve_name)
    if m:
        return state.obj_pos[:, axis_map[m.group(1)]].tolist()

    m = re.match(r"object\.rot_aa\.([xyz])", curve_name)
    if m:
        return state.obj_rot_aa[:, axis_map[m.group(1)]].tolist()

    return None
