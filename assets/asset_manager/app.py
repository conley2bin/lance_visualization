import os
import re
import shutil
import yaml
from flask import Flask, render_template, jsonify, request
from pathlib import Path
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Allowed image extensions
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def scan_gestures_from_filesystem():
    """Scan gestures directory and build data structure"""
    gestures_dir = PROJECT_ROOT / "gestures"
    data = {}

    for category_dir in sorted(gestures_dir.iterdir()):
        if not category_dir.is_dir() or category_dir.name == "gestures.yaml":
            continue

        category_path = f"gestures/{category_dir.name}"
        gesture_list = []

        for img_file in category_dir.iterdir():
            if img_file.is_file() and img_file.suffix.lower() in ALLOWED_EXTENSIONS:
                gesture_name = img_file.stem
                # Only include files with valid prefix format
                if extract_prefix(gesture_name):
                    gesture_list.append(gesture_name)
                else:
                    # Print warning in bold red
                    print(f"\033[1;31m{'=' * 60}\033[0m")
                    print(f"\033[1;31m警告：忽略不符合命名规范的文件\033[0m")
                    print(f"\033[1;31m文件: {category_dir.name}/{img_file.name}\033[0m")
                    print(f"\033[1;31m要求: 文件名必须符合 XXX-Name 格式（如 001-Palmar-Pinch.png）\033[0m")
                    print(f"\033[1;31m{'=' * 60}\033[0m")

        if gesture_list:
            data[category_path] = sorted(gesture_list)

    return data


def load_gestures():
    """Load gesture data by scanning filesystem"""
    gestures_dir = PROJECT_ROOT / "gestures"
    gestures = {}

    for category_dir in sorted(gestures_dir.iterdir()):
        if not category_dir.is_dir() or category_dir.name == "gestures.yaml":
            continue

        category = category_dir.name
        gestures[category] = []

        for img_file in sorted(category_dir.iterdir()):
            if img_file.is_file() and img_file.suffix.lower() in ALLOWED_EXTENSIONS:
                gesture_name = img_file.stem

                # Only include files with valid prefix format
                if extract_prefix(gesture_name):
                    img_path = f"/static_files/gestures/{category}/{img_file.name}"
                    gestures[category].append(
                        {"name": gesture_name, "image": img_path, "category": category}
                    )

    return gestures


def load_objects():
    """Load object data from objects/*/[object].yaml"""
    objects_dir = PROJECT_ROOT / "objects"
    objects = []

    for obj_dir in sorted(objects_dir.iterdir()):
        if not obj_dir.is_dir():
            continue

        obj_name = obj_dir.name
        obj_yaml = obj_dir / f"{obj_name}.yaml"

        if not obj_yaml.exists():
            continue

        with open(obj_yaml, "r", encoding="utf-8") as f:
            obj_data = yaml.safe_load(f)

        # Format dimensions dynamically based on available fields
        dimensions_str = ""
        dimensions = obj_data.get("dimensions", {})
        if dimensions:
            # Check for different dimension field combinations
            length = dimensions.get("length_cm")
            width = dimensions.get("width_cm")
            height = dimensions.get("height_cm")
            diameter = dimensions.get("diameter_cm")

            if length is not None and width is not None and height is not None:
                # Cuboid/Cube format
                dimensions_str = f"L×W×H: {length} × {width} × {height} cm"
            elif diameter is not None and height is not None:
                # Cylinder format
                dimensions_str = f"D×H: {diameter} × {height} cm"
            elif diameter is not None:
                # Sphere format
                dimensions_str = f"D: {diameter} cm"
            elif length is not None or width is not None or height is not None:
                # Partial dimensions
                parts = []
                if length is not None:
                    parts.append(f"L: {length}")
                if width is not None:
                    parts.append(f"W: {width}")
                if height is not None:
                    parts.append(f"H: {height}")
                dimensions_str = " × ".join(parts) + " cm"

        # Check if final_alignment.png exists
        img_path = obj_dir / "final_alignment.png"
        if img_path.exists():
            objects.append(
                {
                    "name": obj_name,
                    "category": obj_data.get("category", "other"),
                    "description": obj_data.get("description", ""),
                    "dimensions": dimensions_str,
                    "image": f"/static_files/objects/{obj_name}/final_alignment.png",
                }
            )

    return objects


def load_scene():
    """Load scene.yaml for gesture-object mappings"""
    scene_file = PROJECT_ROOT / "scene.yaml"
    with open(scene_file, "r", encoding="utf-8") as f:
        scene = yaml.safe_load(f)
    return scene if scene else {}


def save_scene(scene_data):
    """Save scene.yaml with sorted objects"""
    scene_file = PROJECT_ROOT / "scene.yaml"

    # Sort objects alphabetically for each gesture
    for gesture_name, objects in scene_data.items():
        if isinstance(objects, list):
            scene_data[gesture_name] = sorted(objects)

    with open(scene_file, "w", encoding="utf-8") as f:
        yaml.dump(
            scene_data,
            f,
            allow_unicode=True,
            default_flow_style=True,
            width=float("inf"),
        )


def load_gestures_yaml():
    """Load gestures.yaml as raw dict"""
    gestures_file = PROJECT_ROOT / "gestures" / "gestures.yaml"
    with open(gestures_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_gestures_yaml(data):
    """Save gestures.yaml with flow style"""
    gestures_file = PROJECT_ROOT / "gestures" / "gestures.yaml"
    with open(gestures_file, "w", encoding="utf-8") as f:
        yaml.dump(
            data, f, allow_unicode=True, default_flow_style=True, width=float("inf")
        )


def extract_prefix(gesture_name):
    """Extract number prefix from gesture name (e.g., '001-Palmar-Pinch' -> '001')"""
    match = re.match(r"^(\d{3})-", gesture_name)
    if match:
        prefix = match.group(1)
        # Validate range 001-999
        prefix_int = int(prefix)
        if 1 <= prefix_int <= 999:
            return prefix
    return None


def get_gesture_types():
    """Get list of gesture types (subdirectories in gestures/)"""
    gestures_dir = PROJECT_ROOT / "gestures"
    types = []
    for item in gestures_dir.iterdir():
        if item.is_dir():
            types.append(item.name)
    return sorted(types)


def get_used_prefixes(gesture_type):
    """Get list of used prefixes for a gesture type"""
    data = load_gestures_yaml()
    category_path = f"gestures/{gesture_type}"
    gesture_list = data.get(category_path, [])

    prefixes = []
    for gesture_name in gesture_list:
        prefix = extract_prefix(gesture_name)
        if prefix:
            prefixes.append(int(prefix))

    return sorted(prefixes)


def get_all_used_prefixes():
    """Get list of all used prefixes across all gesture types"""
    data = load_gestures_yaml()
    prefixes = []

    for category_path, gesture_list in data.items():
        for gesture_name in gesture_list:
            prefix = extract_prefix(gesture_name)
            if prefix:
                prefixes.append(int(prefix))

    return sorted(set(prefixes))


def check_consistency():
    """Check filesystem for naming convention violations"""
    gestures_dir = PROJECT_ROOT / "gestures"

    issues = {
        "invalid_filenames": [],  # Files without valid XXX-Name format
        "duplicate_prefixes": [],  # Duplicate prefixes across categories
        "empty_categories": [],  # Empty category directories
        "invalid_category_names": [],  # Category names with invalid characters
    }

    all_prefixes = {}  # {prefix: [(category, gesture_name), ...]}

    # Check each category directory
    for category_dir in gestures_dir.iterdir():
        if not category_dir.is_dir() or category_dir.name == "gestures.yaml":
            continue

        category = category_dir.name

        # Check category name format
        if not re.match(r"^[a-zA-Z0-9_-]+$", category):
            issues["invalid_category_names"].append(category)

        # Check for images in directory
        image_files = [
            f
            for f in category_dir.iterdir()
            if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS
        ]

        if not image_files:
            issues["empty_categories"].append(category)
            continue

        # Check each image file
        for img_file in image_files:
            gesture_name = img_file.stem
            prefix = extract_prefix(gesture_name)

            if not prefix:
                issues["invalid_filenames"].append(
                    {"category": category, "file": img_file.name, "name": gesture_name}
                )
            else:
                # Track prefixes for duplicate detection
                prefix_int = int(prefix)
                if prefix_int not in all_prefixes:
                    all_prefixes[prefix_int] = []
                all_prefixes[prefix_int].append((category, gesture_name))

    # Check for duplicate prefixes
    for prefix, gestures in all_prefixes.items():
        if len(gestures) > 1:
            issues["duplicate_prefixes"].append(
                {"prefix": str(prefix).zfill(3), "gestures": gestures}
            )

    return issues


def fix_consistency(issue_type):
    """Fix specific type of consistency issue"""
    gestures_dir = PROJECT_ROOT / "gestures"
    result = {"fixed": [], "manual_action_required": []}

    if issue_type == "invalid_filenames":
        # Cannot auto-fix - requires manual renaming
        result["manual_action_required"].append(
            "无效文件名需要手动重命名为 XXX-Name 格式"
        )

    elif issue_type == "duplicate_prefixes":
        # Cannot auto-fix - requires manual resolution
        result["manual_action_required"].append(
            "重复前缀需要手动修改其中一个手势的前缀"
        )

    elif issue_type == "empty_categories":
        # Delete empty directories
        for category_dir in gestures_dir.iterdir():
            if not category_dir.is_dir() or category_dir.name == "gestures.yaml":
                continue

            image_files = [
                f
                for f in category_dir.iterdir()
                if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS
            ]

            if not image_files:
                shutil.rmtree(category_dir)
                result["fixed"].append(f"删除空目录: {category_dir.name}")

    elif issue_type == "invalid_category_names":
        # Cannot auto-fix - requires manual renaming
        result["manual_action_required"].append(
            "无效分类名称需要手动重命名（只能包含字母、数字、连字符、下划线）"
        )

    # Regenerate gestures.yaml after fixes
    if result["fixed"]:
        gestures_data = scan_gestures_from_filesystem()
        save_gestures_yaml(gestures_data)

    return result


@app.route("/")
def home():
    """Home page - main entry point"""
    return render_template("home.html")


@app.route("/scene")
def scene_index():
    """Scene management - gesture selection page"""
    return render_template("index.html")


@app.route("/scene/editor/<gesture_name>")
def scene_editor(gesture_name):
    """Scene management - object selection page for a specific gesture"""
    return render_template("object_selector.html", gesture_name=gesture_name)


@app.route("/gesture")
def gesture_editor():
    """Gesture management page (to be implemented)"""
    return render_template("gesture_editor.html")


@app.route("/api/gestures")
def api_gestures():
    """API: Get all gestures data"""
    gestures = load_gestures()

    # Flatten into single list with category info
    all_gestures = []
    categories = []

    for category, gesture_list in gestures.items():
        categories.append(category)
        all_gestures.extend(gesture_list)

    return jsonify(
        {"gestures": all_gestures, "categories": ["all"] + sorted(categories)}
    )


@app.route("/api/objects")
def api_objects():
    """API: Get all objects data"""
    objects = load_objects()

    # Extract unique categories
    categories = sorted(set(obj["category"] for obj in objects))

    return jsonify({"objects": objects, "categories": ["all"] + categories})


@app.route("/api/scene/<gesture_name>")
def api_scene_get(gesture_name):
    """API: Get objects for a specific gesture"""
    scene = load_scene()
    objects = scene.get(gesture_name, [])
    return jsonify({"gesture": gesture_name, "objects": objects})


@app.route("/api/scene/<gesture_name>", methods=["POST"])
def api_scene_update(gesture_name):
    """API: Update objects for a specific gesture"""
    data = request.json
    selected_objects = data.get("objects", [])

    scene = load_scene()
    scene[gesture_name] = sorted(selected_objects)
    save_scene(scene)

    return jsonify(
        {"success": True, "gesture": gesture_name, "objects": scene[gesture_name]}
    )


@app.route("/static_files/<path:filepath>")
def serve_static_files(filepath):
    """Serve static files from project root"""
    from flask import send_from_directory

    return send_from_directory(PROJECT_ROOT, filepath)


@app.route("/api/gesture/types")
def api_gesture_types():
    """API: Get all gesture types"""
    types = get_gesture_types()
    return jsonify({"types": types})


@app.route("/api/gesture/prefixes/<gesture_type>")
def api_gesture_prefixes(gesture_type):
    """API: Get used prefixes for a gesture type"""
    used_prefixes = get_used_prefixes(gesture_type)
    return jsonify({"used_prefixes": used_prefixes})


@app.route("/api/gesture/all-prefixes")
def api_gesture_all_prefixes():
    """API: Get all used prefixes across all gesture types"""
    used_prefixes = get_all_used_prefixes()
    return jsonify({"used_prefixes": used_prefixes})


@app.route("/api/gesture/create", methods=["POST"])
def api_gesture_create():
    """API: Create new gestures (batch upload)"""
    try:
        gesture_type = request.form.get("type")
        new_type = request.form.get("new_type")
        files = request.files.getlist("images")

        if not files:
            return jsonify({"success": False, "error": "未上传图片"}), 400

        # Determine target type
        if new_type:
            # Validate new type name
            if not re.match(r"^[a-zA-Z0-9_-]+$", new_type):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "类型名称只能包含字母、数字、连字符、下划线",
                        }
                    ),
                    400,
                )
            target_type = new_type
            # Create directory if not exists
            type_dir = PROJECT_ROOT / "gestures" / target_type
            type_dir.mkdir(exist_ok=True)
        elif gesture_type:
            target_type = gesture_type
        else:
            return jsonify({"success": False, "error": "未选择手势类型"}), 400

        # Load current gestures.yaml
        data = load_gestures_yaml()
        category_path = f"gestures/{target_type}"
        gesture_list = data.get(category_path, [])

        # Get gesture names from form
        gesture_names = request.form.getlist("names")
        if len(gesture_names) != len(files):
            return (
                jsonify({"success": False, "error": "手势名称数量与图片数量不匹配"}),
                400,
            )

        # Check if manual prefix mode
        manual_prefix = request.form.get("manual_prefix") == "true"
        manual_prefixes = []
        if manual_prefix:
            manual_prefixes = request.form.getlist("prefixes")
            if len(manual_prefixes) != len(files):
                return (
                    jsonify({"success": False, "error": "序号数量与图片数量不匹配"}),
                    400,
                )

        # Get all used prefixes globally
        all_used_prefixes = get_all_used_prefixes()
        next_prefix = 1
        if all_used_prefixes:
            next_prefix = max(all_used_prefixes) + 1

        # Validate and save files
        saved_gestures = []
        for i, (file, gesture_name) in enumerate(zip(files, gesture_names)):
            # Validate name
            if not gesture_name:
                return jsonify({"success": False, "error": "手势名称不能为空"}), 400

            # Remove prefix if user accidentally included it
            gesture_name = re.sub(r"^\d+-", "", gesture_name).strip()

            # Validate filename: no spaces, only letters, numbers, hyphens, underscores
            if not re.match(r"^[a-zA-Z0-9_-]+$", gesture_name):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f'手势名称 "{gesture_name}" 格式不正确，仅支持字母、数字、连字符、下划线',
                        }
                    ),
                    400,
                )

            # Determine prefix
            if manual_prefix:
                try:
                    prefix = int(manual_prefixes[i])
                    if prefix < 1 or prefix > 999:
                        return (
                            jsonify(
                                {"success": False, "error": f"序号必须在 1-999 之间"}
                            ),
                            400,
                        )
                    if prefix in all_used_prefixes:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"序号 {str(prefix).zfill(3)} 已被使用",
                                }
                            ),
                            400,
                        )
                except (ValueError, IndexError):
                    return jsonify({"success": False, "error": "序号格式不正确"}), 400
            else:
                prefix = next_prefix
                next_prefix += 1

            # Add prefix to name
            prefixed_name = f"{str(prefix).zfill(3)}-{gesture_name}"

            if prefixed_name in gesture_list:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f'手势名称 "{prefixed_name}" 已存在',
                        }
                    ),
                    400,
                )

            # Check file extension
            file_ext = Path(file.filename).suffix.lower()
            if file_ext not in ALLOWED_EXTENSIONS:
                return (
                    jsonify(
                        {"success": False, "error": f"不支持的图片格式: {file_ext}"}
                    ),
                    400,
                )

            # Save file
            target_path = (
                PROJECT_ROOT / "gestures" / target_type / f"{prefixed_name}{file_ext}"
            )
            file.save(str(target_path))

            saved_gestures.append(prefixed_name)

        # Update gestures.yaml
        gesture_list.extend(saved_gestures)
        gesture_list.sort()
        data[category_path] = gesture_list
        save_gestures_yaml(data)

        return jsonify({"success": True, "gestures": saved_gestures})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gesture/delete", methods=["POST"])
def api_gesture_delete():
    """API: Delete gestures"""
    try:
        gesture_names = request.json.get("gestures", [])
        if not gesture_names:
            return jsonify({"success": False, "error": "未选择手势"}), 400

        # Create deleted_gestures directory
        deleted_dir = PROJECT_ROOT / "deleted_gestures"
        deleted_dir.mkdir(exist_ok=True)

        # Load gestures.yaml
        data = load_gestures_yaml()

        deleted_gestures = []
        categories_to_check = set()
        for gesture_name in gesture_names:
            # Find gesture in yaml
            found = False
            for category_path, gesture_list in data.items():
                if gesture_name in gesture_list:
                    category = category_path.split("/")[-1]

                    # Find and move image file
                    gesture_dir = PROJECT_ROOT / "gestures" / category
                    moved = False
                    for ext in ALLOWED_EXTENSIONS:
                        img_file = gesture_dir / f"{gesture_name}{ext}"
                        if img_file.exists():
                            target_file = deleted_dir / f"{gesture_name}{ext}"
                            shutil.move(str(img_file), str(target_file))
                            moved = True
                            break

                    if not moved:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"未找到手势图片: {gesture_name}",
                                }
                            ),
                            404,
                        )

                    # Remove from yaml
                    gesture_list.remove(gesture_name)
                    data[category_path] = gesture_list
                    deleted_gestures.append(gesture_name)
                    categories_to_check.add(category)
                    found = True
                    break

            if not found:
                return (
                    jsonify({"success": False, "error": f"未找到手势: {gesture_name}"}),
                    404,
                )

        # Check and delete empty category directories
        for category in categories_to_check:
            gesture_dir = PROJECT_ROOT / "gestures" / category
            # Check if directory has any image files
            image_files = [
                f
                for f in gesture_dir.iterdir()
                if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS
            ]
            if not image_files:
                shutil.rmtree(gesture_dir)

        # Regenerate gestures.yaml from filesystem
        gestures_data = scan_gestures_from_filesystem()
        save_gestures_yaml(gestures_data)

        return jsonify({"success": True, "deleted": deleted_gestures})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gesture/check-consistency")
def api_gesture_check_consistency():
    """API: Check for consistency issues"""
    try:
        issues = check_consistency()
        return jsonify({"success": True, "issues": issues})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gesture/fix-consistency", methods=["POST"])
def api_gesture_fix_consistency():
    """API: Fix consistency issues"""
    try:
        issue_type = request.json.get("type")
        if not issue_type:
            return jsonify({"success": False, "error": "未指定问题类型"}), 400

        result = fix_consistency(issue_type)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    # Scan filesystem and generate/update gestures.yaml on startup
    print("扫描手势目录...")
    gestures_data = scan_gestures_from_filesystem()
    save_gestures_yaml(gestures_data)
    print(f"已生成/更新 gestures.yaml，共 {sum(len(v) for v in gestures_data.values())} 个手势")

    # Check and fix issues on startup
    print("\n检查数据完整性...")
    issues = check_consistency()

    # Auto-fix empty categories
    if issues["empty_categories"]:
        print(f"\n发现空目录 ({len(issues['empty_categories'])} 个)，自动删除：")
        for category in issues["empty_categories"]:
            category_dir = PROJECT_ROOT / "gestures" / category
            if category_dir.exists():
                shutil.rmtree(category_dir)
                print(f"  - 已删除: {category}")
        # Regenerate gestures.yaml after deletion
        gestures_data = scan_gestures_from_filesystem()
        save_gestures_yaml(gestures_data)
        # Re-check after fixing
        issues = check_consistency()

    # Report remaining issues
    has_issues = any(issues.values())
    if has_issues:
        print("\n\033[1;31m发现以下问题：\033[0m")

        if issues["invalid_filenames"]:
            print(f"\n\033[1;31m无效文件名 ({len(issues['invalid_filenames'])} 个)：\033[0m")
            for item in issues["invalid_filenames"]:
                print(f"  - {item['category']}/{item['file']}")

        if issues["duplicate_prefixes"]:
            print(f"\n\033[1;31m重复前缀 ({len(issues['duplicate_prefixes'])} 个)：\033[0m")
            for item in issues["duplicate_prefixes"]:
                print(f"  - 前缀 {item['prefix']}: {item['gestures']}")

        if issues["invalid_category_names"]:
            print(f"\n\033[1;31m无效分类名称 ({len(issues['invalid_category_names'])} 个)：\033[0m")
            for category in issues["invalid_category_names"]:
                print(f"  - {category}")

        print("\n\033[1;33m请访问 Gesture Editor 页面修复这些问题\033[0m\n")
    else:
        print("数据完整性检查通过\n")

    app.run(debug=True, port=5000)
