"""
Scene database operations

Handles synchronization of scene data from YAML files to PostgreSQL database.
"""

import yaml
from pathlib import Path
from .database import Database

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Allowed image extensions
ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]


def load_scene_yaml():
    """Load scene.yaml file"""
    scene_file = PROJECT_ROOT / "scene.yaml"
    with open(scene_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_gestures_yaml():
    """Load gestures.yaml file"""
    gestures_file = PROJECT_ROOT / "gestures" / "gestures.yaml"
    with open(gestures_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_gesture_category(gesture_name, gestures_data=None):
    """
    Get gesture category by scanning filesystem

    Args:
        gesture_name: e.g., "01-Palmar-Pinch"
        gestures_data: unused, kept for compatibility

    Returns:
        str: category name (e.g., "grasp")
        None: if gesture not found
    """
    gestures_dir = PROJECT_ROOT / "gestures"

    for category_dir in gestures_dir.iterdir():
        if not category_dir.is_dir():
            continue

        category = category_dir.name

        # Check if gesture image exists in this category
        for ext in ALLOWED_EXTENSIONS:
            img_file = category_dir / f"{gesture_name}{ext}"
            if img_file.exists():
                return category

    return None


def get_gesture_image_path(gesture_name, gesture_category):
    """
    Detect actual gesture image path with extension

    Args:
        gesture_name: e.g., "01-Palmar-Pinch"
        gesture_category: e.g., "grasp"

    Returns:
        str: image path (e.g., "gestures/grasp/01-Palmar-Pinch.png")
        None: if file not found
    """
    for ext in ALLOWED_EXTENSIONS:
        img_file = PROJECT_ROOT / "gestures" / gesture_category / f"{gesture_name}{ext}"
        if img_file.exists():
            return f"gestures/{gesture_category}/{gesture_name}{ext}"
    return None


def get_object_info(object_name):
    """
    Get object category from object YAML file

    Args:
        object_name: e.g., "cube1"

    Returns:
        dict: {"category": "cube", "folder_path": "objects/cube1"}
        None: if file not found or category missing
    """
    obj_yaml = PROJECT_ROOT / "objects" / object_name / f"{object_name}.yaml"

    if not obj_yaml.exists():
        return None

    with open(obj_yaml, "r", encoding="utf-8") as f:
        obj_data = yaml.safe_load(f)

    category = obj_data.get("category")
    if not category:
        return None

    return {
        "category": category,
        "folder_path": f"objects/{object_name}"
    }


def build_scene_records():
    """
    Build scene records from YAML files

    Returns:
        list: list of scene records
        None: if validation fails
    """
    scene_data = load_scene_yaml()

    records = []

    # Sort gestures by prefix number for initial insertion
    sorted_gestures = sorted(scene_data.keys())

    for gesture_name in sorted_gestures:
        object_list = scene_data[gesture_name]

        # Get gesture info by scanning filesystem
        gesture_category = get_gesture_category(gesture_name)
        if gesture_category is None:
            print(f"错误：手势图片文件不存在")
            print(f"  手势: {gesture_name}")
            print("取消同步")
            return None

        gesture_image_path = get_gesture_image_path(gesture_name, gesture_category)
        if gesture_image_path is None:
            print(f"错误：找不到手势图片文件")
            print(f"  手势: {gesture_name}")
            print(f"  分类: {gesture_category}")
            print(f"  期望位置: gestures/{gesture_category}/{gesture_name}.[扩展名]")
            print(f"  支持格式: png, jpg, jpeg, gif, webp, bmp")
            print("取消同步")
            return None

        # Process each object
        for object_name in object_list:
            object_info = get_object_info(object_name)
            if object_info is None:
                print(f"错误：物体信息缺失")
                print(f"  物体: {object_name}")
                print(f"  期望文件: objects/{object_name}/{object_name}.yaml")
                print(f"  需要包含 'category' 字段")
                print("取消同步")
                return None

            # Build record
            record = {
                "gesture": gesture_name,
                "gesture_category": gesture_category,
                "gesture_image_path": gesture_image_path,
                "object": object_name,
                "object_category": object_info["category"],
                "object_folder_path": object_info["folder_path"]
            }
            records.append(record)

    return records


def create_table(db):
    """Create scenes table if not exists"""
    query = """
    CREATE TABLE IF NOT EXISTS scenes (
        scene_id SERIAL PRIMARY KEY,
        gesture VARCHAR(100) NOT NULL,
        gesture_category VARCHAR(50),
        gesture_image_path VARCHAR(255),
        object VARCHAR(100) NOT NULL,
        object_category VARCHAR(50),
        object_folder_path VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(gesture, object)
    )
    """
    if not db.execute_query(query):
        return False

    # Add column comments
    comments = [
        "COMMENT ON COLUMN scenes.scene_id IS '场景记录的唯一标识符'",
        "COMMENT ON COLUMN scenes.gesture IS '手势名称（如 01-Palmar-Pinch）'",
        "COMMENT ON COLUMN scenes.gesture_category IS '手势分类（如 grasp）'",
        "COMMENT ON COLUMN scenes.gesture_image_path IS 'mano_assets项目中手势图片相对路径（如 gestures/grasp/01-Palmar-Pinch.png）'",
        "COMMENT ON COLUMN scenes.object IS '物体名称（如 cube1）'",
        "COMMENT ON COLUMN scenes.object_category IS '物体分类（如 cube）'",
        "COMMENT ON COLUMN scenes.object_folder_path IS 'mano_assets项目中物体文件夹相对路径（如 objects/cube1）'",
        "COMMENT ON COLUMN scenes.created_at IS '记录创建时间'",
        "COMMENT ON COLUMN scenes.updated_at IS '记录最后更新时间'"
    ]

    for comment in comments:
        db.execute_query(comment)

    return True


def get_db_records(db):
    """Get all records from database"""
    query = "SELECT * FROM scenes ORDER BY scene_id"
    return db.fetch_all(query)


def record_key(record):
    """Get unique key for a record (gesture, object)"""
    return (record["gesture"], record["object"])


def records_equal(yaml_record, db_record):
    """Check if YAML record equals database record (excluding timestamps)"""
    fields = ["gesture", "gesture_category", "gesture_image_path",
              "object", "object_category", "object_folder_path"]

    for field in fields:
        if yaml_record.get(field) != db_record.get(field):
            return False
    return True


def sync_scenes_to_db():
    """
    Synchronize scene data from YAML files to PostgreSQL database

    Returns:
        bool: True if successful, False otherwise
    """
    print("\n" + "=" * 60)
    print("同步 scene 数据到数据库")
    print("=" * 60)

    # Build records from YAML
    print("\n1. 读取 YAML 文件...")
    yaml_records = build_scene_records()

    if yaml_records is None:
        return False

    print(f"   从 YAML 读取 {len(yaml_records)} 条记录")

    # Connect to database
    print("\n2. 连接数据库...")
    db = Database()
    if not db.connect():
        print("   错误：无法连接到数据库")
        print("   提醒：未更新远程数据库的 scene 表格")
        return False

    try:
        # Create table if not exists
        print("\n3. 检查表结构...")
        if not create_table(db):
            print("   错误：无法创建表")
            return False
        print("   表结构正常")

        # Get existing records
        print("\n4. 读取数据库现有记录...")
        db_records = get_db_records(db)
        print(f"   数据库中有 {len(db_records)} 条记录")

        # Build lookup dictionaries
        yaml_dict = {record_key(r): r for r in yaml_records}
        db_dict = {record_key(r): r for r in db_records}

        # Find differences
        yaml_keys = set(yaml_dict.keys())
        db_keys = set(db_dict.keys())

        to_insert = yaml_keys - db_keys
        to_delete = db_keys - yaml_keys
        to_check = yaml_keys & db_keys

        # Count updates
        to_update = []
        for key in to_check:
            if not records_equal(yaml_dict[key], db_dict[key]):
                to_update.append(key)

        print(f"\n5. 分析差异...")
        print(f"   新增: {len(to_insert)} 条")
        print(f"   更新: {len(to_update)} 条")
        print(f"   删除: {len(to_delete)} 条")
        print(f"   保持: {len(to_check) - len(to_update)} 条")

        if len(to_insert) == 0 and len(to_update) == 0 and len(to_delete) == 0:
            print("\n   数据库已是最新状态，无需同步")
            return True

        # Perform sync
        print(f"\n6. 执行同步...")

        # Insert new records (maintain order from yaml_records)
        if to_insert:
            insert_query = """
            INSERT INTO scenes (gesture, gesture_category, gesture_image_path,
                              object, object_category, object_folder_path)
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            # Iterate through yaml_records to maintain order
            for record in yaml_records:
                key = record_key(record)
                if key in to_insert:
                    params = (
                        record["gesture"],
                        record["gesture_category"],
                        record["gesture_image_path"],
                        record["object"],
                        record["object_category"],
                        record["object_folder_path"]
                    )
                    db.execute_query(insert_query, params)
            print(f"   插入 {len(to_insert)} 条新记录")

        # Update existing records
        if to_update:
            update_query = """
            UPDATE scenes
            SET gesture_category = %s,
                gesture_image_path = %s,
                object_category = %s,
                object_folder_path = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE gesture = %s AND object = %s
            """
            for key in to_update:
                record = yaml_dict[key]
                params = (
                    record["gesture_category"],
                    record["gesture_image_path"],
                    record["object_category"],
                    record["object_folder_path"],
                    record["gesture"],
                    record["object"]
                )
                db.execute_query(update_query, params)
            print(f"   更新 {len(to_update)} 条记录")

        # Delete removed records
        if to_delete:
            delete_query = "DELETE FROM scenes WHERE gesture = %s AND object = %s"
            for key in to_delete:
                db.execute_query(delete_query, key)
            print(f"   删除 {len(to_delete)} 条记录")

        # Get final record count
        final_records = get_db_records(db)

        print("\n" + "=" * 60)
        print("同步完成")
        print("=" * 60)
        print(f"数据库当前共有 {len(final_records)} 条记录")
        return True

    except Exception as e:
        print(f"\n   错误：同步过程中发生异常")
        print(f"   {str(e)}")
        return False

    finally:
        db.disconnect()
