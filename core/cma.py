from __future__ import annotations

import math
from typing import Any


def _unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "frame_idx": 0,
        "total_frames": 0,
        "frame_counter": None,
        "timestamp_ms": None,
        "human_markers": None,
        "bodies": [],
    }


def _as_sequence(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    return []


def _finite_xyz(value: Any) -> list[float] | None:
    coords = _as_sequence(value)
    if len(coords) < 3:
        return None
    try:
        xyz = [float(coords[0]), float(coords[1]), float(coords[2])]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in xyz):
        return None
    return xyz


def _finite_quat(value: Any) -> list[float] | None:
    coords = _as_sequence(value)
    if len(coords) < 4:
        return None
    try:
        quat = [float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3])]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in quat):
        return None
    return quat


def _frame_item(frames: Any, frame_idx: int) -> list:
    frame_list = _as_sequence(frames)
    if frame_idx < 0 or frame_idx >= len(frame_list):
        return []
    return _as_sequence(frame_list[frame_idx])


def _scalar_at(values: Any, frame_idx: int) -> int | float | None:
    seq = _as_sequence(values)
    if frame_idx < 0 or frame_idx >= len(seq):
        return None
    value = seq[frame_idx]
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None


def get_cma_frame_data(lance_row: dict[str, Any], frame_idx: int) -> dict[str, Any]:
    cma_data = lance_row.get("cma_data")
    if not isinstance(cma_data, dict):
        return _unavailable()

    human_frames = _as_sequence(cma_data.get("human_marker_frames"))
    body_frames = _as_sequence(cma_data.get("body_frames"))
    total_frames = max(len(human_frames), len(body_frames))
    if total_frames <= 0:
        return _unavailable()

    frame_idx = max(0, min(int(frame_idx), total_frames - 1))
    marker_names = [str(name) for name in _as_sequence(cma_data.get("human_marker_names"))]
    marker_x: list[float] = []
    marker_y: list[float] = []
    marker_z: list[float] = []
    visible_marker_names: list[str] = []
    for i, marker in enumerate(_frame_item(human_frames, frame_idx)):
        if not isinstance(marker, dict):
            continue
        position = _finite_xyz(marker.get("position"))
        if position is None:
            continue
        marker_x.append(position[0])
        marker_y.append(position[1])
        marker_z.append(position[2])
        visible_marker_names.append(marker_names[i] if i < len(marker_names) else f"marker_{i}")

    body_names = [str(name) for name in _as_sequence(cma_data.get("body_names"))]
    bodies = []
    for i, body in enumerate(_frame_item(body_frames, frame_idx)):
        if not isinstance(body, dict):
            continue
        position = _finite_xyz(body.get("position"))
        quaternion = _finite_quat(body.get("quaternion"))
        if position is None or quaternion is None:
            continue
        bodies.append({
            "name": body_names[i] if i < len(body_names) else f"body_{i}",
            "position": position,
            "quaternion": quaternion,
        })

    if not marker_x and not bodies:
        result = _unavailable()
        result["frame_idx"] = frame_idx
        result["total_frames"] = total_frames
        return result

    return {
        "available": True,
        "frame_idx": frame_idx,
        "total_frames": total_frames,
        "frame_counter": _scalar_at(cma_data.get("frame_counters"), frame_idx),
        "timestamp_ms": _scalar_at(cma_data.get("timestamp_ms"), frame_idx),
        "human_markers": {
            "x": marker_x,
            "y": marker_y,
            "z": marker_z,
            "names": visible_marker_names,
        } if marker_x else None,
        "bodies": bodies,
    }
