import lance
from collections import OrderedDict
from threading import RLock
import time

from .operator_identity import normalize_operator_name


def _sort_text(value: str | None) -> str:
    return str(value or "").casefold()


def _display_scene(index_data: dict | None, meta: dict | None) -> str:
    object_names = meta.get("object_names") if meta else None
    if isinstance(object_names, list) and object_names:
        return str(object_names[0] or "?")
    return str(index_data.get("scene", "?")) if index_data else "?"


def _trajectory_label(index: int, index_data: dict | None, meta: dict | None) -> str:
    scene = _display_scene(index_data, meta)
    operator = normalize_operator_name(index_data.get("operator", "?")) if index_data else "?"
    gesture = index_data.get("gesture", "") if index_data else ""
    frames = meta.get("total_frames", 0) if meta else 0
    frame_text = f"{frames}帧" if frames > 0 else "不可用"
    if gesture:
        return f"{index:03d}: {scene} ({operator}) / {gesture}- {frame_text}"
    return f"{index:03d}: {scene} ({operator}) - {frame_text}"


def _trajectory_uuid(index_data: dict | None) -> str:
    return str(index_data.get("uuid") or "") if index_data else ""


class OptimizedLanceLoader:
    """优化的 Lance 数据加载器，使用缓存和列选择。"""

    def __init__(self, lance_path: str):
        self.dataset = lance.dataset(lance_path)
        self.total_rows = self.dataset.count_rows()
        self._metadata_cache: dict = {}
        self._video_cache: OrderedDict = OrderedDict()
        self._max_video_cache = 3  # 最多缓存3个轨迹的视频
        self._trajectory_options_cache: list[tuple[str, int, str]] | None = None
        self._trajectory_progress_lock = RLock()
        self._trajectory_options_progress: dict = {
            "status": "idle",
            "loaded": 0,
            "total": self.total_rows,
            "percent": 0.0,
            "message": "轨迹列表未加载",
            "cached": False,
            "started_at": None,
            "updated_at": time.time(),
            "finished_at": None,
        }

    def get_trajectory_info(self, index: int) -> dict:
        """获取指定轨迹的轻量信息（只加载 index + trajectory_metadata 列）。"""
        if index not in self._metadata_cache:
            try:
                row = self.dataset.take([index], columns=["index", "trajectory_metadata"])
                index_data = row["index"][0].as_py()
                meta = row["trajectory_metadata"][0].as_py()
                self._metadata_cache[index] = {
                    "scene": index_data["scene"],
                    "display_scene": _display_scene(index_data, meta),
                    "gesture": index_data.get("gesture", ""),
                    "operator": normalize_operator_name(index_data.get("operator", "N/A")),
                    "frames": meta["total_frames"],
                    "label": _trajectory_label(index, index_data, meta),
                    "uuid": (index_data.get("uuid") or "")[:16],
                    "capMachine": index_data.get("capMachine", "unknown"),
                    "index_data": index_data,
                }
            except Exception as e:
                self._metadata_cache[index] = {
                    "scene": f"Error: {e}",
                    "display_scene": f"Error: {e}",
                    "gesture": "",
                    "operator": "N/A",
                    "frames": 0,
                    "label": f"{index:03d}: 不可用",
                    "uuid": "unknown",
                    "capMachine": "unknown",
                    "index_data": {},
                }
        return self._metadata_cache[index]

    def load_trajectory_data(self, index: int) -> dict | None:
        """加载轨迹数据（排除视频列以节省内存）。"""
        try:
            # 排除video和video_depth列，这些通过get_video_blobs单独加载
            columns = [col for col in self.dataset.schema.names
                      if col not in ["video", "video_depth"]]
            row = self.dataset.take([index], columns=columns)
            return {key: row[key][0].as_py() for key in row.schema.names}
        except Exception as e:
            print(f"加载轨迹 {index} 失败: {e}")
            return None

    def get_video_blobs(self, index: int) -> dict:
        """获取视频 blobs（带LRU缓存）。"""
        if index in self._video_cache:
            self._video_cache.move_to_end(index)
            return self._video_cache[index]

        row = self.dataset.take([index], columns=["video", "video_depth"])
        video = row["video"][0].as_py()
        video_depth = row["video_depth"][0].as_py()
        result = {
            "video": video,
            "video_depth": video_depth,
            "num_cameras": len(video) if video else 0,
        }
        self._video_cache[index] = result

        # 超过限制则删除最旧的
        if len(self._video_cache) > self._max_video_cache:
            oldest = next(iter(self._video_cache))
            del self._video_cache[oldest]
            print(f"[video_cache] 清理轨迹 {oldest} 视频，当前缓存: {len(self._video_cache)}")

        return result

    def _set_trajectory_options_progress(self, **updates) -> None:
        total = int(updates.get("total", self.total_rows) or 0)
        loaded = int(updates.get("loaded", 0) or 0)
        percent = (loaded / total * 100.0) if total else 0.0
        with self._trajectory_progress_lock:
            self._trajectory_options_progress.update(updates)
            self._trajectory_options_progress["total"] = total
            self._trajectory_options_progress["loaded"] = loaded
            self._trajectory_options_progress["percent"] = round(max(0.0, min(100.0, percent)), 1)
            self._trajectory_options_progress["cached"] = self._trajectory_options_cache is not None
            self._trajectory_options_progress["updated_at"] = time.time()

    def get_trajectory_options_progress(self) -> dict:
        """返回轨迹列表构建进度，供前端显示完整列表加载状态。"""
        with self._trajectory_progress_lock:
            progress = dict(self._trajectory_options_progress)
        progress["cached"] = self._trajectory_options_cache is not None
        return progress

    def create_trajectory_options(self) -> list[tuple[str, int, str]]:
        """批量读取所有轨迹 metadata，返回 (label, index, uuid) 列表。"""
        if self._trajectory_options_cache is not None:
            self._set_trajectory_options_progress(
                status="ready",
                loaded=len(self._trajectory_options_cache),
                total=self.total_rows,
                message="轨迹列表已加载",
                finished_at=time.time(),
            )
            return list(self._trajectory_options_cache)

        started_at = time.time()
        self._set_trajectory_options_progress(
            status="loading",
            loaded=0,
            total=self.total_rows,
            message="正在扫描 Lance metadata",
            started_at=started_at,
            finished_at=None,
        )

        try:
            options = []
            row_index = 0
            last_reported = 0
            operator_cache: dict[str, str] = {}
            batches = self.dataset.to_batches(
                columns=[
                    "index.scene",
                    "index.operator",
                    "index.gesture",
                    "index.uuid",
                    "trajectory_metadata.total_frames",
                    "trajectory_metadata.object_names",
                ],
                batch_size=4096,
                scan_in_order=False,
            )
            for batch in batches:
                scene_list = batch["index.scene"].to_pylist()
                operator_list = batch["index.operator"].to_pylist()
                gesture_list = batch["index.gesture"].to_pylist()
                uuid_list = batch["index.uuid"].to_pylist()
                total_frames_list = batch["trajectory_metadata.total_frames"].to_pylist()
                object_names_list = batch["trajectory_metadata.object_names"].to_pylist()

                for batch_offset, scene_raw in enumerate(scene_list):
                    i = row_index
                    object_names = object_names_list[batch_offset] or []
                    if object_names:
                        scene = str(object_names[0] or "?")
                    else:
                        scene = str(scene_raw or "?")

                    operator_raw = operator_list[batch_offset] or "?"
                    operator = operator_cache.get(operator_raw)
                    if operator is None:
                        operator = normalize_operator_name(operator_raw)
                        operator_cache[operator_raw] = operator
                    gesture = gesture_list[batch_offset] or ""
                    frames = total_frames_list[batch_offset] or 0
                    frame_text = f"{frames}帧" if frames > 0 else "不可用"
                    if gesture:
                        label = f"{i:03d}: {scene} ({operator}) / {gesture}- {frame_text}"
                    else:
                        label = f"{i:03d}: {scene} ({operator}) - {frame_text}"
                    uuid = uuid_list[batch_offset] or ""
                    options.append((label, i, uuid, _sort_text(scene), _sort_text(gesture)))
                    row_index += 1

                if row_index - last_reported >= 100 or row_index >= self.total_rows:
                    last_reported = row_index
                    self._set_trajectory_options_progress(
                        status="loading",
                        loaded=row_index,
                        total=self.total_rows,
                        message="正在扫描 Lance metadata",
                    )

            self._set_trajectory_options_progress(
                status="loading",
                loaded=self.total_rows,
                total=self.total_rows,
                message="正在整理轨迹列表",
            )
            options.sort(key=lambda item: (item[3], item[4], item[1]))
            result = [(label, index, uuid) for label, index, uuid, _, _ in options]
            self._trajectory_options_cache = result
            self._set_trajectory_options_progress(
                status="ready",
                loaded=len(result),
                total=self.total_rows,
                message="轨迹列表已加载",
                finished_at=time.time(),
            )
            return list(result)
        except Exception as exc:
            self._set_trajectory_options_progress(
                status="error",
                loaded=0,
                total=self.total_rows,
                message=f"轨迹列表加载失败: {exc}",
                finished_at=time.time(),
            )
            raise
