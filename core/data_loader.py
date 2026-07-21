import lance
from bisect import bisect_left
from collections import OrderedDict
from pathlib import Path
from threading import Condition, RLock
import time

from .operator_identity import normalize_operator_name


def _sort_text(value: str | None) -> str:
    return str(value or "").casefold()


def _display_scene(index_data: dict | None) -> str:
    return str(index_data.get("scene", "?")) if index_data else "?"


def _motion_interval_text(object_moves) -> str:
    if not object_moves:
        return ""
    intervals = []
    for move in object_moves:
        if not isinstance(move, dict):
            continue
        start = move.get("start_frame")
        end = move.get("end_frame")
        if start is None or end is None:
            continue
        intervals.append(f"{start}-{end}")
    return "; ".join(intervals)


def _manifest_fingerprint(lance_path: str) -> str:
    manifest = Path(lance_path) / "_latest.manifest"
    try:
        stat = manifest.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        try:
            stat = Path(lance_path).stat()
            return f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            return "missing"


def _num_cameras_from_capture_info(capture_info) -> int:
    if not isinstance(capture_info, dict):
        return 0
    return sum(1 for key, value in capture_info.items() if str(key).startswith("camera") and value is not None)


def _trajectory_label(index: int, index_data: dict | None, meta: dict | None) -> str:
    scene = _display_scene(index_data)
    operator = normalize_operator_name(index_data.get("operator", "?")) if index_data else "?"
    gesture = index_data.get("gesture", "") if index_data else ""
    frames = meta.get("total_frames", 0) if meta else 0
    frame_text = f"{frames}帧" if frames > 0 else "不可用"
    if gesture:
        return f"{index:03d}: {scene} / {gesture} ({operator}) - {frame_text}"
    return f"{index:03d}: {scene} ({operator}) - {frame_text}"


def _trajectory_uuid(index_data: dict | None) -> str:
    return str(index_data.get("uuid") or "") if index_data else ""


def _initial_trajectory_progress(total: int) -> dict:
    return {
        "status": "idle",
        "loaded": 0,
        "total": total,
        "percent": 0.0,
        "message": "轨迹列表未加载",
        "cached": False,
        "started_at": None,
        "updated_at": time.time(),
        "finished_at": None,
    }


class _TrajectoryOptionsEntry:
    def __init__(self, total_rows: int):
        self.lock = RLock()
        self.ready = Condition(self.lock)
        self.loading = False
        self.options: list[tuple[str, int, str, str]] | None = None
        self.progress = _initial_trajectory_progress(total_rows)


_trajectory_options_entries: dict[tuple[str, str], _TrajectoryOptionsEntry] = {}
_trajectory_options_entries_lock = RLock()


def _get_trajectory_options_entry(lance_path: str, dataset_fingerprint: str, total_rows: int) -> _TrajectoryOptionsEntry:
    key = (lance_path, dataset_fingerprint)
    with _trajectory_options_entries_lock:
        entry = _trajectory_options_entries.get(key)
        if entry is None:
            for stale_key in [stale for stale in _trajectory_options_entries if stale[0] == lance_path]:
                del _trajectory_options_entries[stale_key]
            entry = _TrajectoryOptionsEntry(total_rows)
            _trajectory_options_entries[key] = entry
        else:
            with entry.lock:
                entry.progress["total"] = total_rows
        return entry


def _dataset_fingerprint(dataset, total_rows: int, lance_path: str) -> str:
    try:
        version = dataset.version
    except Exception:
        version = "unknown"

    return ":".join([
        str(version),
        str(total_rows),
        _manifest_fingerprint(lance_path),
    ])


class OptimizedLanceLoader:
    """优化的 Lance 数据加载器，使用缓存和列选择。"""

    def __init__(self, lance_path: str):
        self.lance_path = str(lance_path)
        self.dataset = lance.dataset(lance_path)
        self.total_rows = self.dataset.count_rows()
        self.dataset_fingerprint = _dataset_fingerprint(self.dataset, self.total_rows, self.lance_path)
        self._metadata_cache: dict = {}
        self._video_cache: OrderedDict = OrderedDict()
        self._max_video_cache = 3  # 最多缓存3个轨迹的视频
        self._fragment_offsets: dict[int, tuple[int, int, list[int]]] | None = None
        self._fragment_offsets_lock = RLock()
        self._trajectory_options_entry = _get_trajectory_options_entry(
            self.lance_path,
            self.dataset_fingerprint,
            self.total_rows,
        )

    def _load_fragment_offsets(self) -> dict[int, tuple[int, int, list[int]]]:
        """建立 Lance physical row id 到逻辑 dataset 行号的映射。"""
        if self._fragment_offsets is not None:
            return self._fragment_offsets

        with self._fragment_offsets_lock:
            if self._fragment_offsets is not None:
                return self._fragment_offsets

            offsets: dict[int, tuple[int, int, list[int]]] = {}
            logical_offset = 0
            fragments = sorted(
                self.dataset.get_fragments(),
                key=lambda fragment: int(fragment.fragment_id),
            )
            for fragment in fragments:
                fragment_id = int(fragment.fragment_id)
                physical_rows = int(fragment.physical_rows or fragment.count_rows())
                deleted_rows: list[int] = []
                try:
                    deletion_file = fragment.deletion_file()
                    if deletion_file:
                        deletion_path = Path(self.lance_path) / str(deletion_file)
                        if deletion_path.exists():
                            import pyarrow as pa
                            import pyarrow.ipc as ipc

                            with pa.memory_map(str(deletion_path), "r") as source:
                                deleted_rows = sorted(
                                    int(row["row_id"])
                                    for row in ipc.open_file(source).read_all().to_pylist()
                                )
                except Exception as exc:
                    print(f"[lance] 读取 fragment {fragment_id} deletion bitmap 失败: {exc}")

                offsets[fragment_id] = (logical_offset, physical_rows, deleted_rows)
                logical_offset += int(fragment.count_rows())

            self._fragment_offsets = offsets
            return offsets

    def _row_id_to_index(self, row_id) -> int:
        row_id = int(row_id)
        fragment_id = row_id >> 32
        physical_offset = row_id & 0xFFFFFFFF
        fragment_info = self._load_fragment_offsets().get(fragment_id)
        if fragment_info is None:
            return row_id

        logical_offset, physical_rows, deleted_rows = fragment_info
        if physical_offset >= physical_rows:
            return -1
        return logical_offset + physical_offset - bisect_left(deleted_rows, physical_offset)

    def get_trajectory_info(self, index: int) -> dict:
        """获取指定轨迹的轻量信息（只加载 index + trajectory_metadata 列）。"""
        if index not in self._metadata_cache:
            try:
                row = self.dataset.take([index], columns=["index", "trajectory_metadata"])
                index_data = row["index"][0].as_py()
                meta = row["trajectory_metadata"][0].as_py()
                self._metadata_cache[index] = {
                    "scene": index_data["scene"],
                    "display_scene": _display_scene(index_data),
                    "gesture": index_data.get("gesture", ""),
                    "operator": normalize_operator_name(index_data.get("operator", "N/A")),
                    "frames": meta["total_frames"],
                    "num_cameras": _num_cameras_from_capture_info(meta.get("capture_info")),
                    "motion_interval": _motion_interval_text((meta or {}).get("trajectory_info", {}).get("object_move")),
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
                    "num_cameras": 0,
                    "motion_interval": "",
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
        entry = self._trajectory_options_entry
        with entry.lock:
            entry.progress.update(updates)
            entry.progress["total"] = total
            entry.progress["loaded"] = loaded
            entry.progress["percent"] = round(max(0.0, min(100.0, percent)), 1)
            entry.progress["cached"] = entry.options is not None
            entry.progress["updated_at"] = time.time()
            entry.ready.notify_all()

    def get_trajectory_options_progress(self) -> dict:
        """返回轨迹列表构建进度，供前端显示完整列表加载状态。"""
        entry = self._trajectory_options_entry
        with entry.lock:
            progress = dict(entry.progress)
            progress["cached"] = entry.options is not None
            return progress

    def create_trajectory_options(self) -> list[tuple[str, int, str, str]]:
        """批量读取所有轨迹 metadata，返回 (label, index, uuid, motion_interval) 列表。"""
        entry = self._trajectory_options_entry
        with entry.lock:
            cached_options = entry.options
            if cached_options is not None:
                result = cached_options
            else:
                result = None

        if result is not None:
            self._set_trajectory_options_progress(
                status="ready",
                loaded=len(result),
                total=self.total_rows,
                message="轨迹列表已加载",
                finished_at=time.time(),
            )
            return result

        with entry.lock:
            while entry.loading:
                entry.ready.wait(timeout=1.0)
                if entry.options is not None:
                    result = entry.options
                    break
            else:
                result = None
            if result is not None:
                return result
            entry.loading = True

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
            loaded_rows = 0
            last_reported = 0
            operator_cache: dict[str, str] = {}
            batches = self.dataset.to_batches(
                columns=[
                    "index.scene",
                    "index.operator",
                    "index.uuid",
                    "trajectory_metadata.total_frames",
                    "trajectory_metadata.trajectory_info.object_move",
                ],
                batch_size=4096,
                with_row_id=True,
                scan_in_order=False,
            )
            for batch in batches:
                scene_list = batch["index.scene"].to_pylist()
                operator_list = batch["index.operator"].to_pylist()
                uuid_list = batch["index.uuid"].to_pylist()
                total_frames_list = batch["trajectory_metadata.total_frames"].to_pylist()
                object_move_list = batch["trajectory_metadata.trajectory_info.object_move"].to_pylist()
                row_ids = batch["_rowid"].to_pylist()

                for batch_offset, scene_raw in enumerate(scene_list):
                    i = self._row_id_to_index(row_ids[batch_offset])
                    if i < 0 or i >= self.total_rows:
                        continue
                    scene = str(scene_raw or "?")

                    operator_raw = operator_list[batch_offset] or "?"
                    operator = operator_cache.get(operator_raw)
                    if operator is None:
                        operator = normalize_operator_name(operator_raw)
                        operator_cache[operator_raw] = operator
                    frames = total_frames_list[batch_offset] or 0
                    frame_text = f"{frames}帧" if frames > 0 else "不可用"
                    motion_interval = _motion_interval_text(object_move_list[batch_offset])
                    label = f"{i:03d}: {scene} ({operator}) - {frame_text}"
                    uuid = uuid_list[batch_offset] or ""
                    options.append((label, i, uuid, motion_interval, _sort_text(scene), ""))
                    loaded_rows += 1

                if loaded_rows - last_reported >= 100 or loaded_rows >= self.total_rows:
                    last_reported = loaded_rows
                    self._set_trajectory_options_progress(
                        status="loading",
                        loaded=loaded_rows,
                        total=self.total_rows,
                        message="正在扫描 Lance metadata",
                    )

            self._set_trajectory_options_progress(
                status="loading",
                loaded=self.total_rows,
                total=self.total_rows,
                message="正在整理轨迹列表",
            )
            # 列表顺序以场景名优先，保持和之前一致的浏览习惯。
            options.sort(key=lambda item: (item[4], item[1]))
            result = [(label, index, uuid, motion_interval) for label, index, uuid, motion_interval, _, _ in options]
            with entry.lock:
                entry.options = result
                entry.loading = False
                entry.ready.notify_all()
            self._set_trajectory_options_progress(
                status="ready",
                loaded=len(result),
                total=self.total_rows,
                message="轨迹列表已加载",
                finished_at=time.time(),
            )
            return result
        except Exception as exc:
            self._set_trajectory_options_progress(
                status="error",
                loaded=0,
                total=self.total_rows,
                message=f"轨迹列表加载失败: {exc}",
                finished_at=time.time(),
            )
            with entry.lock:
                entry.loading = False
                entry.ready.notify_all()
            raise
