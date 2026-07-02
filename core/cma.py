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
        "human_hands": [],
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


def _is_camera_body(name: str) -> bool:
    return name.upper().startswith("CAMERA")


def _is_human_body(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith((
        "lefthand",
        "righthand",
        "leftwrist",
        "rightwrist",
        "leftarm",
        "rightarm",
        "leftforearm",
        "rightforearm",
    ))


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


def _valid_index_by_name(
    names: list[str],
    positions: list[list[float] | None],
) -> dict[str, int]:
    by_name: dict[str, int] = {}
    for i, (name, point) in enumerate(zip(names, positions)):
        if name in by_name or not _valid_point(point):
            continue
        by_name[name] = i
    return by_name


def _human_lines_payload(names: list[str], positions: list[list[float] | None]) -> dict[str, list[float]] | None:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    by_name = _valid_index_by_name(names, positions)
    for side in ("LeftHand", "RightHand"):
        root = side
        for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            chain = [f"{side}{finger}{i}" for i in range(1, 5)]
            segments = [(root, chain[0]), *zip(chain, chain[1:])]
            for start_name, end_name in segments:
                start = by_name.get(start_name)
                end = by_name.get(end_name)
                if start is None or end is None:
                    continue
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


def _side_points_payload(
    side: str,
    names: list[str],
    positions: list[list[float] | None],
) -> dict[str, list] | None:
    side_names: list[str] = []
    side_positions: list[list[float] | None] = []
    seen: set[str] = set()
    for name, point in zip(names, positions):
        if not name.startswith(side) or name in seen or not _valid_point(point):
            continue
        seen.add(name)
        side_names.append(name)
        side_positions.append(point)
    return _points_payload(side_names, side_positions)


def _side_lines_payload(
    side: str,
    names: list[str],
    positions: list[list[float] | None],
) -> dict[str, list[float]] | None:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    by_name = _valid_index_by_name(names, positions)
    root = side
    for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
        chain = [f"{side}{finger}{i}" for i in range(1, 5)]
        segments = [(root, chain[0]), *zip(chain, chain[1:])]
        for start_name, end_name in segments:
            start = by_name.get(start_name)
            end = by_name.get(end_name)
            if start is None or end is None:
                continue
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


def _human_hands_payload(names: list[str], positions: list[list[float] | None]) -> list[dict[str, Any]]:
    hands: list[dict[str, Any]] = []
    for side in ("LeftHand", "RightHand"):
        markers = _side_points_payload(side, names, positions)
        lines = _side_lines_payload(side, names, positions)
        if markers or lines:
            hands.append({
                "name": "left" if side == "LeftHand" else "right",
                "markers": markers,
                "lines": lines,
            })
    return hands


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
    meta = lance_row.get("trajectory_metadata") or {}

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
    human_hands = _human_hands_payload(marker_names, marker_positions)
    body_markers = _points_payload(body_names, body_positions)
    object_pose = None
    object_names = {str(name) for name in _as_sequence(meta.get("object_names"))}
    ordered_bodies = sorted(
        bodies,
        key=lambda body: 0 if body["name"] in object_names else 1,
    )
    for body in ordered_bodies:
        if _is_camera_body(body["name"]) or _is_human_body(body["name"]):
            continue
        rot_aa = _quat_to_rotvec(body["quaternion"])
        if rot_aa is not None:
            object_pose = {"pos": body["position"], "rot_aa": rot_aa, "name": body["name"]}
            break
    if object_pose is None and ordered_bodies:
        rot_aa = _quat_to_rotvec(ordered_bodies[0]["quaternion"])
        if rot_aa is not None:
            object_pose = {
                "pos": ordered_bodies[0]["position"],
                "rot_aa": rot_aa,
                "name": ordered_bodies[0]["name"],
            }

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
        "human_hands": human_hands,
        "body_markers": body_markers,
        "object_pose": object_pose,
        "object_transform": {
            "position": object_pose["pos"],
            "rotation": object_pose["rot_aa"],
        } if object_pose else None,
        "bodies": bodies,
    }
