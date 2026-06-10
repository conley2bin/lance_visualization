from __future__ import annotations

from typing import Any, Protocol, TypedDict


class TrajectoryListItem(TypedDict):
    label: str
    index: int
    uuid: str


class TrajectoryInfo(TypedDict, total=False):
    label: str
    title: str
    subtitle: str
    total_frames: int
    scene: str
    display_scene: str
    gesture: str
    operator: str
    frames: int
    uuid: str
    capMachine: str
    index_data: dict[str, Any]


class MeshPayload(TypedDict):
    x: list[float]
    y: list[float]
    z: list[float]
    i: list[int]
    j: list[int]
    k: list[int]


class PointsPayload(TypedDict):
    x: list[float]
    y: list[float]
    z: list[float]
    names: list[str]


class ObjectTransformPayload(TypedDict):
    position: list[float]
    rotation: list[float]


class ObjectPosePayload(TypedDict):
    pos: list[float]
    rot_aa: list[float]


class FramePayload(TypedDict, total=False):
    frame_idx: int
    total_frames: int
    scene: str
    title: str
    mano_mesh: MeshPayload | None
    mano_joints: PointsPayload | None
    urdf_joints: PointsPayload | None
    urdf_meshes: list[MeshPayload] | None
    object_mesh: MeshPayload | None
    object_transform: ObjectTransformPayload | None
    object_pose: ObjectPosePayload | None
    show_origin: bool


class LoadPayload(TypedDict, total=False):
    total_frames: int
    num_cameras: int
    has_urdf: bool
    has_object_mesh: bool
    curve_options: list[str]
    label: str
    title: str
    subtitle: str
    scene: str
    display_scene: str
    gesture: str
    operator: str
    frames: int
    uuid: str
    capMachine: str
    index_data: dict[str, Any]


class ViewerAdapter(Protocol):
    """通用可视化数据适配器接口。"""

    @property
    def total_items(self) -> int:
        ...

    def list_items(self) -> list[TrajectoryListItem]:
        ...

    def get_item_info(self, index: int) -> TrajectoryInfo:
        ...

    def build_state(self, index: int) -> Any:
        ...

    def get_load_payload(self, index: int, state: Any) -> LoadPayload:
        ...

    def get_frame_payload(
        self,
        state: Any,
        frame_idx: int,
        *,
        show_mano_mesh: bool = True,
        show_mano_joints: bool = False,
        show_urdf_joints: bool = False,
        show_urdf_mesh: bool = False,
        show_object: bool = True,
        show_origin: bool = False,
    ) -> FramePayload:
        ...

    def get_object_mesh_payload(self, state: Any) -> MeshPayload | None:
        ...

    def get_video_frame_payload(
        self,
        index: int,
        cam_idx: int,
        frame_idx: int,
        stream: str = "color",
    ) -> dict[str, Any] | None:
        ...

    def get_curve_options(self, state: Any) -> list[str]:
        ...

    def get_curve_data(self, state: Any, curve_name: str) -> list[float] | None:
        ...

    def get_all_curve_data(self, state: Any) -> dict[str, list[float]]:
        ...


class EmptyViewerAdapter:
    """未选择 Lance 数据源时的占位 adapter。"""

    @property
    def total_items(self) -> int:
        return 0

    def list_items(self) -> list[TrajectoryListItem]:
        return []

    def get_item_info(self, index: int) -> TrajectoryInfo:
        raise RuntimeError("请先选择 Lance 数据源")

    def build_state(self, index: int) -> Any:
        raise RuntimeError("请先选择 Lance 数据源")

    def get_load_payload(self, index: int, state: Any) -> LoadPayload:
        raise RuntimeError("请先选择 Lance 数据源")

    def get_frame_payload(
        self,
        state: Any,
        frame_idx: int,
        *,
        show_mano_mesh: bool = True,
        show_mano_joints: bool = False,
        show_urdf_joints: bool = False,
        show_urdf_mesh: bool = False,
        show_object: bool = True,
        show_origin: bool = False,
    ) -> FramePayload:
        raise RuntimeError("请先选择 Lance 数据源")

    def get_object_mesh_payload(self, state: Any) -> MeshPayload | None:
        raise RuntimeError("请先选择 Lance 数据源")

    def get_video_frame_payload(
        self,
        index: int,
        cam_idx: int,
        frame_idx: int,
        stream: str = "color",
    ) -> dict[str, Any] | None:
        raise RuntimeError("请先选择 Lance 数据源")

    def get_curve_options(self, state: Any) -> list[str]:
        raise RuntimeError("请先选择 Lance 数据源")

    def get_curve_data(self, state: Any, curve_name: str) -> list[float] | None:
        raise RuntimeError("请先选择 Lance 数据源")

    def get_all_curve_data(self, state: Any) -> dict[str, list[float]]:
        raise RuntimeError("请先选择 Lance 数据源")
