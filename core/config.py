import os
from pathlib import Path

import yaml


def load_config(config_path: str = None) -> dict:
    """
    读取 viz_config.yaml，返回配置字典。
    config_path 为 None 时自动在 /data 和当前目录查找。
    环境变量优先级高于 yaml 文件。
    """
    config = None

    if config_path is None:
        candidates = [
            Path("/data/viz_config.yaml"),
            Path.cwd() / "viz_config.yaml",
            Path(__file__).parent.parent / "viz_config.yaml",
        ]
        for p in candidates:
            if p.exists():
                config_path = str(p)
                break

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)

    if config is None:
        config = _default_config()

    # 环境变量覆盖（优先级最高）
    for env_key, config_key in [
        ("LANCE_DATASET", "lance_dataset"),
        ("MANO_MODEL_PATH", "mano_model"),
    ]:
        val = os.environ.get(env_key)
        if val:
            config.setdefault("paths", {})[config_key] = val

    return config


def _default_config() -> dict:
    return {
        "paths": {
            "lance_dataset": os.environ.get(
                "LANCE_DATASET",
                "/mnt/nas-222-project/mocap/releases/v0.5/trajectories_preprocessed.lance",
            ),
            "mano_model": os.environ.get(
                "MANO_MODEL_PATH",
                "/app/assets/models/MANO_RIGHT.pkl",
            ),
            "urdf": "",
            "object_mesh": "",
            "annotations_dir": os.environ.get("ANNOTATIONS_DIR", "/app/annotations"),
            "project_root": os.environ.get("PROJECT_ROOT", "/app"),
        },
        "defaults": {
            "trajectory_index": 0,
            "camera_index": 0,
            "video_stream": "color",
            "playback_fps": 15,
            "hand": "right",
        },
    }


def get_annotations_dir(config: dict) -> Path:
    """返回标注文件保存目录，优先读取配置文件，其次环境变量。"""
    val = os.environ.get("ANNOTATIONS_DIR")
    if val:
        return Path(val)
    return Path(config.get("paths", {}).get("annotations_dir", "/app/annotations"))


def get_project_root(config: dict = None) -> Path:
    """返回 assets 等资源的根目录，优先读取环境变量，其次配置文件。"""
    val = os.environ.get("PROJECT_ROOT")
    if val:
        return Path(val)
    if config:
        return Path(config.get("paths", {}).get("project_root", "/app"))
    return Path("/app")
