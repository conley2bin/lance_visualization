from pathlib import Path

import yaml


def load_config(config_path: str = None) -> dict:
    """
    读取 viz_config.yaml，返回配置字典。
    config_path 为 None 时自动在 /data 和当前目录查找。
    """
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

    if config_path is None or not Path(config_path).exists():
        return _default_config()

    with open(config_path) as f:
        return yaml.safe_load(f)


def _default_config() -> dict:
    return {
        "paths": {
            "lance_dataset": "/mnt/nas-222-project/mocap/releases/v0.5/trajectories_preprocessed.lance",
            "mano_model": "/data/assets/models/MANO_RIGHT.pkl",
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
    """返回数据根目录（容器内为 /data）。"""
    return Path("/data")
