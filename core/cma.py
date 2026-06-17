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
        "human_lines": None,
        "body_markers": None,
        "object_pose": None,
        "object_transform": None,
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


def _display_name(raw: Any) -> str:
    name = str(raw)
    if name.startswith("Skeleton_"):
        parts = name.split("_", 2)
        if len(parts) == 3 and parts[1].isdigit():
            return parts[2]
    if name.startswith("Skeleton"):
        parts = name.split("_", 1)
        if len(parts) == 2 and parts[0][8:].isdigit():
            return parts[1]
    return name


def _valid_point(point: list[float] | None) -> bool:
    return bool(point and all(math.isfinite(v) for v in point) and math.hypot(*point) > 1e-9)


def _points_payload(names: list[str], positions: list[list[float] | None]) -> dict[str, list] | None:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    kept_names: list[str] = []
    for name, point in zip(names, positions):
        if not _valid_point(point):
            continue
        xs.append(float(point[0]))
        ys.append(float(point[1]))
        zs.append(float(point[2]))
        kept_names.append(name)
    if not xs:
        return None
    return {"x": xs, "y": ys, "z": zs, "names": kept_names}


def _make_human_line_pairs(names: list[str]) -> list[tuple[int, int]]:
    by_name = {name: i for i, name in enumerate(names)}
    pairs: list[tuple[int, int]] = []
    for side in ("LeftHand", "RightHand"):
        root = side
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            chain = [f"{side}{finger}{i}" for i in range(1, 5)]
            if root in by_name and chain[0] in by_name:
                pairs.append((by_name[root], by_name[chain[0]]))
            for a, b in zip(chain, chain[1:]):
                if a in by_name and b in by_name:
                    pairs.append((by_name[a], by_name[b]))
    return pairs


def _human_lines_payload(names: list[str], positions: list[list[float] | None]) -> dict[str, list[float]] | None:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for start, end in _make_human_line_pairs(names):
        a = positions[start] if start < len(positions) else None
        b = positions[end] if end < len(positions) else None
        if not _valid_point(a) or not _valid_point(b):
            continue
        xs.extend([float(a[0]), float(b[0])])
        ys.extend([float(a[1]), float(b[1])])
        zs.extend([float(a[2]), float(b[2])])
    if not xs:
        return None
    return {"x": xs, "y": ys, "z": zs}


def _quat_to_rotvec(quat: list[float] | None) -> list[float] | None:
    if quat is None:
        return None
    x, y, z, w = quat
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(norm) or norm <= 1e-8:
        return None
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    if w < 0:
        x, y, z, w = -x, -y, -z, -w
    sin_half = math.sqrt(x * x + y * y + z * z)
    if sin_half <= 1e-8:
        return [0.0, 0.0, 0.0]
    angle = 2.0 * math.atan2(sin_half, w)
    scale = angle / sin_half
    return [x * scale, y * scale, z * scale]


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
    marker_names = [_display_name(name) for name in _as_sequence(cma_data.get("human_marker_names"))]
    marker_positions: list[list[float] | None] = []
    for i, marker in enumerate(_frame_item(human_frames, frame_idx)):
        if not isinstance(marker, dict):
            marker_positions.append(None)
            continue
        marker_positions.append(_finite_xyz(marker.get("position")))
    if len(marker_names) < len(marker_positions):
        marker_names.extend(f"marker_{i}" for i in range(len(marker_names), len(marker_positions)))

    body_names = [_display_name(name) for name in _as_sequence(cma_data.get("body_names"))]
    body_positions: list[list[float] | None] = []
    bodies = []
    for i, body in enumerate(_frame_item(body_frames, frame_idx)):
        if not isinstance(body, dict):
            body_positions.append(None)
            continue
        position = _finite_xyz(body.get("position"))
        quaternion = _finite_quat(body.get("quaternion"))
        body_positions.append(position)
        if position is None or quaternion is None:
            continue
        bodies.append({
            "name": body_names[i] if i < len(body_names) else f"body_{i}",
            "position": position,
            "quaternion": quaternion,
        })
    if len(body_names) < len(body_positions):
        body_names.extend(f"body_{i}" for i in range(len(body_names), len(body_positions)))

    human_markers = _points_payload(marker_names, marker_positions)
    human_lines = _human_lines_payload(marker_names, marker_positions)
    body_markers = _points_payload(body_names, body_positions)
    object_pose = None
    for body in bodies:
        if body["name"].upper().startswith("CAMERA"):
            continue
        rot_aa = _quat_to_rotvec(body["quaternion"])
        if rot_aa is not None:
            object_pose = {"pos": body["position"], "rot_aa": rot_aa}
            break
    if object_pose is None and bodies:
        rot_aa = _quat_to_rotvec(bodies[0]["quaternion"])
        if rot_aa is not None:
            object_pose = {"pos": bodies[0]["position"], "rot_aa": rot_aa}

    if not human_markers and not body_markers and object_pose is None:
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
        "human_markers": human_markers,
        "human_lines": human_lines,
        "body_markers": body_markers,
        "object_pose": object_pose,
        "object_transform": {
            "position": object_pose["pos"],
            "rotation": object_pose["rot_aa"],
        } if object_pose else None,
        "bodies": bodies,
    }
