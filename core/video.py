import base64
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


def decode_video_frame(
    video_blobs: dict,
    cam_idx: int,
    frame_idx: int,
    stream: str = "color",
) -> np.ndarray | None:
    """
    解码指定摄像头/帧的图像，返回 RGB ndarray (H, W, 3)。
    stream: 'color' 或 'depth'
    """
    try:
        if cam_idx >= video_blobs["num_cameras"]:
            return None

        if stream == "color":
            cam_data = video_blobs["video"][cam_idx] if video_blobs["video"] else None
            if cam_data is None:
                return None
            # 兼容键名 "color" 或直接为帧列表
            blobs = cam_data.get("color", cam_data) if isinstance(cam_data, dict) else cam_data
            if not blobs or frame_idx >= len(blobs):
                return None
            blob = blobs[frame_idx]
            if blob is None:
                return None
            frame = cv2.imdecode(np.frombuffer(bytes(blob), np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return None
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        else:  # depth
            cam_data = video_blobs["video_depth"][cam_idx] if video_blobs["video_depth"] else None
            if cam_data is None:
                return None
            blobs = cam_data.get("depth", cam_data) if isinstance(cam_data, dict) else cam_data
            if not blobs or frame_idx >= len(blobs):
                return None
            blob = blobs[frame_idx]
            if blob is None:
                return None
            frame = cv2.imdecode(np.frombuffer(bytes(blob), np.uint8), cv2.IMREAD_UNCHANGED)
            if frame is None:
                return None
            depth_norm = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX)
            depth_color = cv2.applyColorMap(depth_norm.astype(np.uint8), cv2.COLORMAP_JET)
            return cv2.cvtColor(depth_color, cv2.COLOR_BGR2RGB)

    except Exception as e:
        print(f"[video] decode_video_frame 失败 cam={cam_idx} frame={frame_idx}: {e}")
        return None


def frame_to_base64(frame: np.ndarray) -> str | None:
    """将 RGB ndarray 转为 data URI（PNG base64）。"""
    if frame is None:
        return None
    img = Image.fromarray(frame)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"
