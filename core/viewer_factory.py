from __future__ import annotations

from pathlib import Path

from .adapters import EmptyViewerAdapter, ViewerAdapter
from .lance_adapter import LanceViewerAdapter


def create_viewer_adapter(config: dict, project_root: Path) -> ViewerAdapter:
    viewer_type = config.get("viewer", {}).get("type", "lance")
    if viewer_type != "lance":
        raise ValueError(f"Unsupported viewer adapter type: {viewer_type}")

    lance_path = config["paths"]["lance_dataset"]
    mano_model_path = config["paths"]["mano_model"]
    hand = config.get("defaults", {}).get("hand", "right")

    if not lance_path:
        print("[startup] 未选择 Lance 数据集，使用空 adapter")
        return EmptyViewerAdapter()

    print(f"[startup] 加载 Lance 数据集: {lance_path}")
    return LanceViewerAdapter(
        lance_path=lance_path,
        mano_model_path=mano_model_path,
        hand=hand,
        project_root=project_root,
    )
