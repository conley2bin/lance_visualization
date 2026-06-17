from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from .adapters import CmaFramePayload, FramePayload, LoadPayload, MeshPayload, TrajectoryInfo, TrajectoryListItem, ViewerAdapter
from .cma import get_cma_frame_data
from .curves import get_curve_data, get_curve_options
from .data_loader import OptimizedLanceLoader
from .video import decode_video_frame, frame_to_base64
from .visualization import TrajectoryState, get_frame_data


class LanceViewerAdapter(ViewerAdapter):
    """当前 Lance 数据集的 adapter 实现。"""

    def __init__(self, lance_path: str, mano_model_path: str, hand: str, project_root: Path):
        self.loader = OptimizedLanceLoader(lance_path)
        self.mano_model_path = mano_model_path
        self.hand = hand
        self.project_root = project_root

    @property
    def total_items(self) -> int:
        return self.loader.total_rows

    def list_items(self) -> list[TrajectoryListItem]:
        options = self.loader.create_trajectory_options()
        return [{"label": label, "index": idx, "uuid": uuid} for label, idx, uuid in options]

    def get_item_info(self, index: int) -> TrajectoryInfo:
        self._validate_index(index)
        info = self.loader.get_trajectory_info(index)
        display_scene = info.get("display_scene") or info["scene"]
        return {
            **info,
            "title": f"{display_scene} / {info['gesture']}" if info.get("gesture") else display_scene,
            "subtitle": info["operator"],
            "total_frames": info["frames"],
        }

    def build_state(self, index: int) -> TrajectoryState:
        self._validate_index(index)
        lance_row = self.loader.load_trajectory_data(index)
        if lance_row is None:
            raise HTTPException(status_code=404, detail=f"轨迹 {index} 加载失败")
        return TrajectoryState(
            lance_row=lance_row,
            mano_model_path=self.mano_model_path,
            hand=self.hand,
            project_root=self.project_root,
        )

    def get_load_payload(self, index: int, state: TrajectoryState) -> LoadPayload:
        info = self.get_item_info(index)
        video_info = self.loader.get_video_blobs(index)
        return {
            **info,
            "total_frames": state.T,
            "num_cameras": video_info["num_cameras"],
            "has_urdf": state.urdf_helper is not None,
            "has_object_mesh": state.object_mesh is not None,
            "curve_options": self.get_curve_options(state),
        }

    def get_frame_payload(
        self,
        state: TrajectoryState,
        frame_idx: int,
        *,
        show_mano_mesh: bool = True,
        show_mano_joints: bool = False,
        show_urdf_joints: bool = False,
        show_urdf_mesh: bool = False,
        show_object: bool = True,
        show_origin: bool = False,
    ) -> FramePayload:
        frame = get_frame_data(
            state=state,
            frame_idx=frame_idx,
            show_mano_mesh=show_mano_mesh,
            show_mano_joints=show_mano_joints,
            show_urdf_joints=show_urdf_joints,
            show_urdf_mesh=show_urdf_mesh,
            show_object=show_object,
            show_origin=show_origin,
        )
        frame["title"] = frame.get("scene", "")
        return frame

    def get_object_mesh_payload(self, state: TrajectoryState) -> MeshPayload | None:
        if state.object_mesh is None:
            return None
        return {
            "x": state.object_mesh["vertices"][:, 0].tolist(),
            "y": state.object_mesh["vertices"][:, 1].tolist(),
            "z": state.object_mesh["vertices"][:, 2].tolist(),
            "i": state.object_mesh["faces"][:, 0].tolist(),
            "j": state.object_mesh["faces"][:, 1].tolist(),
            "k": state.object_mesh["faces"][:, 2].tolist(),
        }

    def get_video_frame_payload(
        self,
        index: int,
        cam_idx: int,
        frame_idx: int,
        stream: str = "color",
    ) -> dict[str, str] | None:
        video_blobs = self.loader.get_video_blobs(index)
        frame = decode_video_frame(video_blobs, cam_idx, frame_idx, stream)
        if frame is None:
            return None
        return {"data_uri": frame_to_base64(frame)}

    def get_cma_frame_payload(self, state: TrajectoryState, frame_idx: int) -> CmaFramePayload:
        return get_cma_frame_data(state.lance_row, frame_idx)

    def get_curve_options(self, state: TrajectoryState) -> list[str]:
        return get_curve_options(state)

    def get_curve_data(self, state: TrajectoryState, curve_name: str) -> list[float] | None:
        return get_curve_data(state, curve_name)

    def get_all_curve_data(self, state: TrajectoryState) -> dict[str, list[float]]:
        result = {}
        for name in self.get_curve_options(state):
            data = self.get_curve_data(state, name)
            if data is not None:
                result[name] = data
        return result

    def _validate_index(self, index: int) -> None:
        if index < 0 or index >= self.total_items:
            raise HTTPException(status_code=404, detail="轨迹索引超出范围")
