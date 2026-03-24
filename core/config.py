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
        },
        "defaults": {
            "trajectory_index": 0,
            "camera_index": 0,
            "video_stream": "color",
            "playback_fps": 15,
        },
    }


def get_project_root() -> Path:
    """返回 assets 等资源的根目录。可通过 PROJECT_ROOT 环境变量覆盖。"""
    return Path(os.environ.get("PROJECT_ROOT", "/app"))
