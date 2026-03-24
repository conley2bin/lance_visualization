from pathlib import Path

import numpy as np
import trimesh

PINOCCHIO_AVAILABLE = False
try:
    import pinocchio as pin
    from lxml import etree
    PINOCCHIO_AVAILABLE = True
except ImportError:
    pass


class URDFHelper:
    """URDF 加载和运动学计算辅助类。"""

    def __init__(self, urdf_path: str = None):
        self.urdf_path = urdf_path
        self.model = None
        self.data = None
        self.skeleton = None
        self.mesh_pairs = None
        self.mesh_map = {}

        if urdf_path and PINOCCHIO_AVAILABLE:
            self.load_urdf(urdf_path)

    def load_urdf(self, urdf_path: str) -> bool:
        if not PINOCCHIO_AVAILABLE:
            return False

        urdf_path = Path(urdf_path)
        if not urdf_path.exists():
            return False

        try:
            self.urdf_path = str(urdf_path)
            self.model = pin.buildModelFromUrdf(self.urdf_path)
            self.data = self.model.createData()
            self.skeleton = self._parse_skeleton()
            self.mesh_map = self._parse_urdf_visual_meshes()
            self.mesh_pairs = self._load_urdf_meshes()
            return True
        except Exception as e:
            print(f"URDF 加载失败: {e}")
            return False

    def _parse_skeleton(self) -> list:
        if not self.model:
            return []
        connections = []
        for i in range(1, self.model.njoints):
            parent_id = self.model.parents[i]
            if parent_id > 0:
                connections.append((parent_id - 1, i - 1))
        return connections

    def _parse_urdf_visual_meshes(self) -> dict:
        if not self.urdf_path:
            return {}
        tree = etree.parse(str(self.urdf_path))
        root = tree.getroot()
        mesh_map = {}
        for link in root.findall("link"):
            link_name = link.get("name")
            visual = link.find("visual")
            if visual is not None:
                geometry = visual.find("geometry")
                if geometry is not None:
                    mesh_elem = geometry.find("mesh")
                    if mesh_elem is not None:
                        mesh_map[link_name] = mesh_elem.get("filename")
        return mesh_map

    def _load_urdf_meshes(self) -> list | None:
        if not self.mesh_map:
            return None
        urdf_dir = Path(self.urdf_path).parent
        mesh_frame_pairs = []
        for link_name, mesh_filename in self.mesh_map.items():
            if mesh_filename.startswith("meshes/"):
                mesh_filename = mesh_filename[7:]
            mesh_path = urdf_dir / "meshes" / mesh_filename
            if not mesh_path.exists():
                continue
            try:
                mesh = trimesh.load(str(mesh_path))
                link_frame_idx = next(
                    (i for i in range(len(self.model.frames))
                     if self.model.frames[i].name == link_name),
                    None,
                )
                if link_frame_idx is not None:
                    mesh_frame_pairs.append(({
                        "vertices": np.asarray(mesh.vertices, dtype=np.float32),
                        "faces": np.asarray(mesh.faces, dtype=np.int32),
                    }, link_frame_idx))
            except Exception as e:
                print(f"无法加载 mesh {mesh_path}: {e}")
        return mesh_frame_pairs if mesh_frame_pairs else None

    def forward_kinematics(self, q: np.ndarray) -> bool:
        if not self.model or not self.data:
            return False
        try:
            pin.forwardKinematics(self.model, self.data, q)
            pin.updateFramePlacements(self.model, self.data)
            return True
        except Exception:
            return False

    def extract_joint_positions(self) -> np.ndarray | None:
        if not self.data:
            return None
        return np.array([self.data.oMi[i].translation for i in range(1, self.model.njoints)])

    def get_transformed_meshes(self) -> list[dict]:
        if not self.mesh_pairs or not self.data:
            return []
        result = []
        for mesh_data, link_frame_idx in self.mesh_pairs:
            T = self.data.oMf[link_frame_idx].homogeneous
            vertices = mesh_data["vertices"]
            vertices_homo = np.hstack([vertices, np.ones((len(vertices), 1))])
            vertices_transformed = (T @ vertices_homo.T).T[:, :3]
            result.append({"vertices": vertices_transformed, "faces": mesh_data["faces"]})
        return result

    def get_joint_names(self) -> list[str]:
        if not self.model:
            return []
        return [self.model.names[i] for i in range(1, self.model.njoints)]
