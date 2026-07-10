"""
曲线数据提取，对应 notebook 的 get_curve_options / get_curve_data。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import numpy as np

from .cma import _as_sequence, _display_name, _finite_xyz, _valid_point

if TYPE_CHECKING:
    from .visualization import TrajectoryState


_AXIS_MAP = {"x": 0, "y": 1, "z": 2}
_AXES = ("x", "y", "z")


def _limit(state: TrajectoryState) -> int | None:
    return getattr(state, "T", None)


def _series(values: Any, state: TrajectoryState) -> list[float] | None:
    arr = np.asarray(values, dtype=np.float32)
    if arr.ndim != 1:
        return None
    limit = _limit(state)
    if limit is not None:
        arr = arr[:limit]
    return arr.tolist()


def _axis_series(values: Any, axis: str, state: TrajectoryState) -> list[float] | None:
    arr = np.asarray(values, dtype=np.float32)
    axis_idx = _AXIS_MAP[axis]
    if arr.ndim != 2 or arr.shape[1] <= axis_idx:
        return None
    limit = _limit(state)
    if limit is not None:
        arr = arr[:limit]
    return arr[:, axis_idx].tolist()


def _hand_prefixes(state: TrajectoryState) -> list[str]:
    prefixes: list[str] = []
    used: dict[str, int] = {}
    for idx, hand_state in enumerate(getattr(state, "hands", [])):
        name = str(hand_state.get("name") or "").lower()
        if name in {"left", "right"}:
            base = f"hand_{name}"
        else:
            base = f"hand{idx + 1}"
        used[base] = used.get(base, 0) + 1
        prefixes.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return prefixes


def _hand_for_prefix(state: TrajectoryState, prefix: str) -> dict | None:
    for hand_prefix, hand_state in zip(_hand_prefixes(state), getattr(state, "hands", [])):
        if hand_prefix == prefix:
            return hand_state
    return None


def _add_hand_options(options: list[str], prefix: str, hand_state: dict) -> None:
    options.extend(f"{prefix}.mano.global_pos.{axis}" for axis in _AXES)
    options.extend(f"{prefix}.mano.global_rot_aa.{axis}" for axis in _AXES)
    for joint_idx in range(21):
        options.extend(f"{prefix}.mano.joint[{joint_idx}].pos.{axis}" for axis in _AXES)

    urdf_helper = hand_state.get("urdf_helper")
    if urdf_helper and getattr(urdf_helper, "model", None):
        for dof_idx in range(urdf_helper.model.nq):
            options.append(f"{prefix}.urdf.dof[{dof_idx}]")


def _add_object_options(options: list[str], idx: int) -> None:
    prefix = f"object{idx + 1}"
    options.extend(f"{prefix}.pos.{axis}" for axis in _AXES)
    options.extend(f"{prefix}.rot_aa.{axis}" for axis in _AXES)


def _cma_marker_side(marker_name: str) -> str | None:
    if marker_name.startswith("LeftHand"):
        return "left"
    if marker_name.startswith("RightHand"):
        return "right"
    return None


def _cma_human_marker_frames(state: TrajectoryState) -> list:
    cma_data = state.lance_row.get("cma_data")
    if not isinstance(cma_data, dict):
        return []
    return _as_sequence(cma_data.get("human_marker_frames"))


def _cma_human_marker_names(state: TrajectoryState) -> list[str]:
    cma_data = state.lance_row.get("cma_data")
    if not isinstance(cma_data, dict):
        return []
    return [_display_name(name) for name in _as_sequence(cma_data.get("human_marker_names"))]


def _cma_marker_has_data(frames: list, marker_idx: int) -> bool:
    for frame in frames:
        markers = _as_sequence(frame)
        if marker_idx >= len(markers) or not isinstance(markers[marker_idx], dict):
            continue
        if _valid_point(_finite_xyz(markers[marker_idx].get("position"))):
            return True
    return False


def _add_cma_marker_options(options: list[str], state: TrajectoryState) -> None:
    frames = _cma_human_marker_frames(state)
    if not frames:
        return

    for marker_idx, marker_name in enumerate(_cma_human_marker_names(state)):
        side = _cma_marker_side(marker_name)
        if side is None or not _cma_marker_has_data(frames, marker_idx):
            continue
        marker_prefix = f"hand_{side}.cma.{marker_name}.pos"
        options.extend(f"{marker_prefix}.{axis}" for axis in _AXES)


def _get_object(state: TrajectoryState, prefix: str) -> dict | None:
    m = re.fullmatch(r"object(\d+)", prefix)
    if not m:
        return None
    idx = int(m.group(1)) - 1
    objects = getattr(state, "objects", [])
    if 0 <= idx < len(objects):
        return objects[idx]
    return None


def _get_hand_curve_data(
    state: TrajectoryState,
    hand_state: dict,
    curve_path: str,
) -> list[float] | list[float | None] | None:
    m = re.fullmatch(r"mano\.global_pos\.([xyz])", curve_path)
    if m:
        return _axis_series(hand_state.get("transl"), m.group(1), state)

    m = re.fullmatch(r"mano\.global_rot_aa\.([xyz])", curve_path)
    if m:
        return _axis_series(hand_state.get("global_orient"), m.group(1), state)

    m = re.fullmatch(r"mano\.joint\[(\d+)\]\.pos\.([xyz])", curve_path)
    if m:
        joint_idx, axis = int(m.group(1)), m.group(2)
        joints = np.asarray(hand_state.get("mano_joints"), dtype=np.float32)
        if joints.ndim == 3 and joint_idx < joints.shape[1]:
            return _axis_series(joints[:, joint_idx, :], axis, state)
        return None

    m = re.fullmatch(r"urdf\.dof\[(\d+)\]", curve_path)
    if m:
        dof_idx = int(m.group(1))
        dof = np.asarray(hand_state.get("urdf_dof"), dtype=np.float32)
        if dof.ndim == 2 and dof_idx < dof.shape[1]:
            return _series(dof[:, dof_idx], state)
        return None

    m = re.fullmatch(r"cma\.([^.]+)\.pos\.([xyz])", curve_path)
    if m:
        return _get_cma_marker_curve_data(state, m.group(1), m.group(2))

    return None


def _get_cma_marker_curve_data(
    state: TrajectoryState,
    marker_name: str,
    axis: str,
) -> list[float | None] | None:
    names = _cma_human_marker_names(state)
    try:
        marker_idx = names.index(marker_name)
    except ValueError:
        return None

    axis_idx = _AXIS_MAP[axis]
    frames = _cma_human_marker_frames(state)
    limit = _limit(state)
    if limit is not None:
        frames = frames[:limit]

    values: list[float | None] = []
    has_value = False
    for frame in frames:
        markers = _as_sequence(frame)
        if marker_idx >= len(markers) or not isinstance(markers[marker_idx], dict):
            values.append(None)
            continue
        point = _finite_xyz(markers[marker_idx].get("position"))
        if not _valid_point(point):
            values.append(None)
            continue
        values.append(point[axis_idx])
        has_value = True
    return values if has_value else None


def _get_object_curve_data(
    state: TrajectoryState,
    obj: dict,
    curve_path: str,
) -> list[float] | None:
    m = re.fullmatch(r"pos\.([xyz])", curve_path)
    if m:
        return _axis_series(obj.get("pos"), m.group(1), state)

    m = re.fullmatch(r"rot_aa\.([xyz])", curve_path)
    if m:
        return _axis_series(obj.get("rot_aa"), m.group(1), state)

    return None


def get_curve_options(state: TrajectoryState) -> list[str]:
    """返回所有可绘制曲线的名称列表。"""
    options: list[str] = []
    hands = getattr(state, "hands", [])
    objects = getattr(state, "objects", [])
    hand_prefixes = _hand_prefixes(state)

    for idx in range(max(len(objects), len(hands))):
        if idx < len(objects):
            _add_object_options(options, idx)
        if idx < len(hands):
            _add_hand_options(options, hand_prefixes[idx], hands[idx])

    _add_cma_marker_options(options, state)
    return options


def get_curve_data(
    state: TrajectoryState,
    curve_name: str,
) -> list[float] | list[float | None] | None:
    """返回指定曲线的全帧数据，找不到返回 None。"""
    if "." in curve_name:
        prefix, curve_path = curve_name.split(".", 1)

        obj = _get_object(state, prefix)
        if obj is not None:
            return _get_object_curve_data(state, obj, curve_path)

        hand_state = _hand_for_prefix(state, prefix)
        if hand_state is not None:
            return _get_hand_curve_data(state, hand_state, curve_path)

        m = re.fullmatch(r"cma\.([^.]+)\.pos\.([xyz])", curve_path)
        if prefix.startswith("hand_") and m:
            return _get_cma_marker_curve_data(state, m.group(1), m.group(2))

    # 兼容旧单手/单物体曲线名。
    m = re.fullmatch(r"mano\.(.+)", curve_name)
    if m and getattr(state, "hands", None):
        return _get_hand_curve_data(state, state.hands[0], f"mano.{m.group(1)}")

    m = re.fullmatch(r"urdf\.(.+)", curve_name)
    if m and getattr(state, "hands", None):
        return _get_hand_curve_data(state, state.hands[0], f"urdf.{m.group(1)}")

    m = re.fullmatch(r"object\.(.+)", curve_name)
    if m and getattr(state, "objects", None):
        primary_idx = getattr(state, "primary_object_idx", 0)
        objects = getattr(state, "objects", [])
        if 0 <= primary_idx < len(objects):
            return _get_object_curve_data(state, objects[primary_idx], m.group(1))

    return None
