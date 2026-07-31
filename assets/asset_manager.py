#!/usr/bin/env python3
"""Asset Manager Launcher

Quick launcher for the MANO Assets Management GUI application.
Checks dependencies and starts the Flask server.
"""

import sys
import subprocess
import webbrowser
import time
from pathlib import Path

def check_dependencies():
    """Check if required packages are installed"""
    missing = []

    try:
        import flask
    except ImportError:
        missing.append('flask')

    try:
        import yaml
    except ImportError:
        missing.append('pyyaml')

    return missing

def install_dependencies(packages):
    """Install missing packages"""
    print(f"Missing dependencies: {', '.join(packages)}")
    print(f"Installing: pip install {' '.join(packages)}")

    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + packages)
        print("Dependencies installed successfully!")
        return True
    except subprocess.CalledProcessError:
        print("Failed to install dependencies.")
        print(f"Please run manually: pip install {' '.join(packages)}")
        return False

def main():
    """Main launcher function"""
    print("=" * 60)
    print("MANO Assets Manager")
    print("=" * 60)

    # Check dependencies
    missing = check_dependencies()
    if missing:
        response = input(f"\nMissing packages: {', '.join(missing)}\nInstall now? (y/n): ")
        if response.lower() == 'y':
            if not install_dependencies(missing):
                sys.exit(1)
        else:
            print(f"\nPlease install manually: pip install {' '.join(missing)}")
            sys.exit(1)

    print("\nStarting Asset Manager...")
    print("Server will start at: http://127.0.0.1:5000")
    print("Press Ctrl+C to stop the server")
    print("-" * 60)

    # Change to asset_manager directory
    editor_dir = Path(__file__).parent / 'asset_manager'

    # Open browser after a short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://127.0.0.1:5000')

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    # Start Flask app
    try:
        subprocess.run([sys.executable, str(editor_dir / 'app.py')])
    except KeyboardInterrupt:
        print("\n\n正在关闭 Asset Manager...")

        # Check consistency before syncing to database
        try:
            sys.path.insert(0, str(Path(__file__).parent / 'asset_manager'))
            from app import check_consistency, PROJECT_ROOT, scan_gestures_from_filesystem, save_gestures_yaml
            import shutil

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

            # Check for remaining issues
            has_issues = any(issues.values())

            if has_issues:
                print("\n\033[1;31m发现以下问题，取消数据库同步：\033[0m")

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

                print("\n\033[1;33m请修复这些问题后再同步数据库\033[0m")
            else:
                # Sync data to database
                from db.scene import sync_scenes_to_db
                sync_scenes_to_db()

        except Exception as e:
            print(f"\n警告：未更新远程数据库的 scene 表格")
            print(f"错误信息: {str(e)}")

        print("\nGoodbye!")

if __name__ == '__main__':
    main()
