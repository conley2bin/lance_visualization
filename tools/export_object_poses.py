#!/usr/bin/env python3
"""导出 Lance 数据集中每条轨迹的物体（刚体）逐帧位姿。

数据来源与可视化项目一致（core/visualization.py 读取的相同列）：
  - objects:  每个物体的 pos(T,3) + rot_aa(T,3)，世界系，单位米/弧度
  - timestamp: 逐帧时间戳（秒），120fps，数据预处理阶段已完成对齐
NaN（若有）原样保留。

用法：
  python tools/export_object_poses.py <lance路径> --out <输出目录>            # 全量导出
  python tools/export_object_poses.py <lance路径> --out <输出目录> --index 0  # 只导出第 0 条

每条轨迹输出一个目录：
  meta.json   轨迹元信息（场景/操作员/手势/uuid/帧率/帧数/物体名单）
  poses.npz   timestamps(T,) + 每个物体的 pos_<i>_<name>(T,3), rot_aa_<i>_<name>(T,3)
  <name>.csv  每物体一个 CSV：timestamp,pos_x,pos_y,pos_z,rot_aa_x,rot_aa_y,rot_aa_z
"""
import argparse
import json
import re
import sys
from pathlib import Path

import lance
import numpy as np

COLUMNS = ["index", "timestamp", "objects", "trajectory_metadata"]


def sanitize(name: str) -> str:
    """物体名转安全文件名。"""
    name = name.strip().replace(" ", "_")
    return re.sub(r"[^\w\-]", "_", name) or "unnamed"


def scene_object_names(scene: str, n_objects: int) -> list[str]:
    names = [s.strip() for s in str(scene or "").replace("，", ",").split(",") if s.strip()]
    return [names[i] if i < len(names) else f"object_{i}" for i in range(n_objects)]


def export_trajectory(ds, index: int, out_root: Path) -> Path | None:
    row = ds.take([index], columns=COLUMNS)
    r = {k: row[k][0].as_py() for k in row.schema.names}

    idx = r["index"] or {}
    meta = r["trajectory_metadata"] or {}
    ts = np.asarray(r["timestamp"] or [], dtype=np.float64)
    objects = r["objects"] or []
    if not objects:
        print(f"[跳过] 轨迹 {index}: 无物体数据")
        return None

    names = scene_object_names(idx.get("scene", ""), len(objects))
    traj_dir = out_root / f"traj_{index:03d}_{sanitize(idx.get('scene', ''))}"
    traj_dir.mkdir(parents=True, exist_ok=True)

    # meta.json
    info = {
        "trajectory_index": index,
        "uuid": idx.get("uuid", ""),
        "scene": idx.get("scene", ""),
        "operator": idx.get("operator", ""),
        "gesture": idx.get("gesture", ""),
        "data_fps": meta.get("data_fps"),
        "total_frames": meta.get("total_frames"),
        "num_timestamps": int(ts.shape[0]),
        "objects": names,
        "units": {"timestamp": "s", "pos": "m", "rot_aa": "rad (axis-angle, world frame)"},
        "nan_policy": "as-is",
    }
    (traj_dir / "meta.json").write_text(json.dumps(info, ensure_ascii=False, indent=2))

    # poses.npz + 每物体 CSV
    npz_data = {"timestamps": ts}
    header = "timestamp,pos_x,pos_y,pos_z,rot_aa_x,rot_aa_y,rot_aa_z"
    for i, obj in enumerate(objects):
        pos = np.asarray(obj["pos"], dtype=np.float64)
        rot = np.asarray(obj["rot_aa"], dtype=np.float64)
        npz_data[f"pos_{i}_{sanitize(names[i])}"] = pos
        npz_data[f"rot_aa_{i}_{sanitize(names[i])}"] = rot

        n = min(len(ts), len(pos), len(rot))
        block = np.column_stack([ts[:n], pos[:n], rot[:n]])
        np.savetxt(
            traj_dir / f"{sanitize(names[i])}.csv",
            block,
            delimiter=",",
            header=header,
            comments="",
            fmt="%.9g",
        )

    np.savez_compressed(traj_dir / "poses.npz", **npz_data)
    print(f"[完成] 轨迹 {index}: {len(objects)} 个物体, {len(ts)} 帧 -> {traj_dir}")
    return traj_dir


def main():
    ap = argparse.ArgumentParser(description="导出 Lance 轨迹的物体逐帧位姿")
    ap.add_argument("lance_path", help=".lance 数据集路径")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--index", type=int, default=None, help="只导出指定轨迹（默认全量）")
    args = ap.parse_args()

    ds = lance.dataset(args.lance_path)
    total = ds.count_rows()
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    indices = [args.index] if args.index is not None else range(total)
    done = 0
    for i in indices:
        if i < 0 or i >= total:
            print(f"[错误] 轨迹索引 {i} 超出范围 (0..{total - 1})")
            sys.exit(1)
        try:
            if export_trajectory(ds, i, out_root) is not None:
                done += 1
        except Exception as e:
            print(f"[失败] 轨迹 {i}: {e}")
    print(f"\n共导出 {done} 条轨迹 -> {out_root}")


if __name__ == "__main__":
    main()
