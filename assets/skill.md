1. MANO 物体 OBJ 存放在 `objects/<object>/<object>.obj`，来源必须是同目录的 `<object>_aligned.stl`。不要用 `<object>.stl` 更新 OBJ；同名 STL 是未对齐源模型。 
   i. 查看一下 aligned STL 和 OBJ 是否一致：用 `trimesh.load(..., process=False)` 从每个 `*_aligned.stl` 导出 OBJ bytes，并与当前 `<object>.obj` 做 byte-level 比较。确保 OBJ 是从 aligned STL 生成的。

2. 使用 `stl2obj.py` 批量更新 OBJ：

   ```bash
   python stl2obj.py
   ```

   只更新某些物体：

   ```bash
   python stl2obj.py --object bowl --object powerdrill
   ```

3. 更新前后可以用 check 模式确认 OBJ 是否和 aligned STL 一致：

   ```bash
   python stl2obj.py --check
   ```

   `--check` 返回非 0 表示存在缺失或不一致的 OBJ。

4. 转换逻辑使用 `trimesh.load_mesh(stl_path, force="mesh", process=False)` 和 `mesh.export(file_type="obj")`，保留 STL 原始三角面顺序，不做 mesh processing。

5. 运行脚本前需要有 `trimesh`。可使用父仓库 README 中的 asset-processing 环境，或在当前 Python 环境安装 `trimesh`。

6. `Assets/sim/mano_assets` 是父仓库中的子模块。修改 OBJ/STL 或本目录脚本后，先在本子模块提交，再回到父仓库提交 submodule 指针。
