import lance
from collections import OrderedDict


class OptimizedLanceLoader:
    """优化的 Lance 数据加载器，使用缓存和列选择。"""

    def __init__(self, lance_path: str):
        self.dataset = lance.dataset(lance_path)
        self.total_rows = self.dataset.count_rows()
        self._metadata_cache: dict = {}
        self._video_cache: OrderedDict = OrderedDict()
        self._max_video_cache = 3  # 最多缓存3个轨迹的视频

    def get_trajectory_info(self, index: int) -> dict:
        """获取指定轨迹的轻量信息（只加载 index + trajectory_metadata 列）。"""
        if index not in self._metadata_cache:
            try:
                row = self.dataset.take([index], columns=["index", "trajectory_metadata"])
                index_data = row["index"][0].as_py()
                meta = row["trajectory_metadata"][0].as_py()
                self._metadata_cache[index] = {
                    "scene": index_data["scene"],
                    "operator": index_data["operator"],
                    "frames": meta["total_frames"],
                    "uuid": (index_data.get("uuid") or "")[:16],
                    "capMachine": index_data.get("capMachine", "unknown"),
                }
            except Exception as e:
                self._metadata_cache[index] = {
                    "scene": f"Error: {e}",
                    "operator": "N/A",
                    "frames": 0,
                    "uuid": "unknown",
                    "capMachine": "unknown",
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

    def create_trajectory_options(self) -> list[tuple[str, int]]:
        """批量读取所有轨迹 metadata，返回 (label, index) 列表。"""
        table = self.dataset.to_table(columns=["index", "trajectory_metadata"])

        # 批量转换为 Python 对象，避免逐行调用 as_py()
        index_list = table["index"].to_pylist()
        meta_list = table["trajectory_metadata"].to_pylist()

        options = []
        for i, (index_data, meta) in enumerate(zip(index_list, meta_list)):
            frames = meta.get("total_frames", 0) if meta else 0
            if frames > 0:
                scene = index_data.get("scene", "?") if index_data else "?"
                operator = index_data.get("operator", "?") if index_data else "?"
                label = f"{i:03d}: {scene} ({operator}) - {frames}帧"
            else:
                label = f"{i:03d}: 不可用"
            options.append((label, i))
            # 同时填充 metadata cache
            if index_data and meta:
                self._metadata_cache[i] = {
                    "scene": index_data.get("scene", "?"),
                    "operator": index_data.get("operator", "?"),
                    "frames": frames,
                    "uuid": (index_data.get("uuid") or "")[:16],
                    "capMachine": index_data.get("capMachine", "unknown"),
                }
        return options
