#!/usr/bin/env python3
"""Regenerate MANO object OBJ meshes from aligned STL files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import trimesh
except ImportError as exc:  # pragma: no cover - exercised only without deps.
    raise SystemExit(
        "Missing dependency: trimesh. Install the asset-processing environment "
        "before running this script."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OBJECTS_ROOT = REPO_ROOT / "objects"


def as_mesh(loaded):
    if isinstance(loaded, trimesh.Scene):
        meshes = [
            geometry
            for geometry in loaded.geometry.values()
            if isinstance(geometry, trimesh.Trimesh)
        ]
        if not meshes:
            raise ValueError("scene does not contain mesh geometry")
        return trimesh.util.concatenate(meshes)
    if isinstance(loaded, trimesh.Trimesh):
        return loaded
    raise TypeError(f"unsupported mesh type: {type(loaded)!r}")


def object_dirs(objects_root: Path, names: list[str] | None) -> list[Path]:
    if names:
        return [objects_root / name for name in names]
    return sorted(path for path in objects_root.iterdir() if path.is_dir())


def aligned_stl_for(object_dir: Path) -> Path:
    return object_dir / f"{object_dir.name}_aligned.stl"


def obj_for(object_dir: Path) -> Path:
    return object_dir / f"{object_dir.name}.obj"


def export_obj_bytes(stl_path: Path) -> bytes:
    mesh = as_mesh(trimesh.load_mesh(stl_path, force="mesh", process=False))
    data = mesh.export(file_type="obj")
    if isinstance(data, str):
        return data.encode("utf-8")
    return data


def convert_one(stl_path: Path, obj_path: Path, check: bool) -> str:
    data = export_obj_bytes(stl_path)
    old = obj_path.read_bytes() if obj_path.exists() else None

    if old == data:
        return "ok"
    if check:
        return "missing" if old is None else "diff"

    obj_path.write_bytes(data)
    return "created" if old is None else "updated"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate MANO <object>.obj files from "
            "objects/<object>/<object>_aligned.stl."
        )
    )
    parser.add_argument(
        "--objects-root",
        type=Path,
        default=DEFAULT_OBJECTS_ROOT,
        help="Path to the MANO objects directory.",
    )
    parser.add_argument(
        "--object",
        dest="objects",
        action="append",
        help="Object name to process. Can be passed multiple times.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check whether OBJ files match generated output.",
    )
    args = parser.parse_args()

    objects_root = args.objects_root
    if not objects_root.is_absolute():
        objects_root = (Path.cwd() / objects_root).resolve()

    if not objects_root.exists():
        parser.error(f"objects root does not exist: {objects_root}")

    counts: dict[str, int] = {}
    failed = False

    for object_dir in object_dirs(objects_root, args.objects):
        stl_path = aligned_stl_for(object_dir)
        obj_path = obj_for(object_dir)
        if not stl_path.exists():
            print(f"skip missing aligned STL: {stl_path}", file=sys.stderr)
            counts["skipped"] = counts.get("skipped", 0) + 1
            continue

        status = convert_one(stl_path, obj_path, check=args.check)
        counts[status] = counts.get(status, 0) + 1
        if status in {"diff", "missing"}:
            failed = True
        print(f"{status:7} {stl_path.relative_to(objects_root)} -> {obj_path.relative_to(objects_root)}")

    summary = " ".join(f"{key}={counts[key]}" for key in sorted(counts))
    print(f"summary {summary}" if summary else "summary no objects processed")
    return 1 if args.check and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
