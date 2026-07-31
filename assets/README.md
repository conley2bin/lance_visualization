# MANO Assets Manager

手势-物体映射管理系统，提供 GUI 编辑器和 PostgreSQL 数据库同步。

## 快速开始

```bash
# 安装依赖
uv sync

# 启动应用
uv run python asset_manager.py
```

应用启动后自动打开浏览器访问 http://127.0.0.1:5000

按 Ctrl+C 停止服务时自动同步数据到 PostgreSQL 数据库。

## 项目结构

```
mano_assets/
├── asset_manager/          # Flask Web 应用
│   ├── app.py             # 主应用入口
│   ├── db/                # 数据库模块
│   │   ├── config.py      # 数据库配置
│   │   ├── database.py    # 连接管理
│   │   └── scene.py       # 同步逻辑
│   ├── static/            # CSS/JS 静态文件
│   └── templates/         # HTML 模板
├── gestures/              # 手势数据和图片
│   ├── grasp/             # 抓握类手势
│   │   ├── 001-Palmar-Pinch.png
│   │   ├── 002-Prismatic-3-Finger.png
│   │   └── ...
│   └── in_hand/           # 手内操作类手势
│       ├── 020-Rolling.png
│       ├── 021-Sliding.png
│       └── ...
├── objects/               # 物体数据
│   ├── banana/
│   │   ├── banana.yaml            # 元数据文件
│   │   ├── banana.stl             # 3D 模型
│   │   ├── banana_aligned.stl     # 对齐后模型
│   │   ├── banana_drilled.stl     # 钻孔后模型
│   │   ├── banana.json            # 配置文件
│   │   └── final_alignment.png    # 预览图片
│   ├── cube1/
│   │   ├── cube1.yaml
│   │   ├── cube1.stl
│   │   ├── cube1_aligned.stl
│   │   ├── cube1_drilled.stl
│   │   ├── cube1.json
│   │   └── final_alignment.png
│   └── ...
├── models/                # MANO模型
├── operators/             # 操作人员信息
├── scene.yaml             # 场景配置
├── asset_manager.py       # 启动脚本
├── pyproject.toml         # 项目依赖配置
├── uv.lock                # 依赖锁定文件
├── .gitignore             # Git 忽略配置
├── .python-version        # Python 版本配置
└── __init__.py            # Python 包初始化
```

## 文件命名规范

### Gestures 目录

**手势命名格式**：`XXX-Name`
- `XXX`：三位数字前缀（001-999），全局唯一
- `Name`：描述性名称，只能包含字母、数字、连字符、下划线

**图片文件**：
- 文件名必须与手势名称完全一致
- 支持扩展名：`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`

**分类目录**：
- 只能包含：大小写字母、数字、连字符、下划线
- 不能包含空格

### Objects 目录

**目录命名**：建议使用小写字母和数字组合

**元数据文件**：`{object_name}.yaml`（必须与目录名一致）

必需字段：
- `id`：物体标识符
- `category`：物体分类
- `description`：物体描述
- `dimensions`：尺寸信息（可以为空 `{}`）
- `weight_kg`：重量（可以为空）

**预览图片**：`final_alignment.png`（固定名称）

## 数据验证

### 自动检查时机

- **启动时**：扫描文件系统后自动检查，发现问题输出警告但不阻止启动
- **关闭时**：Ctrl+C 关闭应用前检查，发现问题输出警告并取消数据库同步

### 检查项

- 文件名格式符合 `XXX-Name` 规范
- 前缀全局唯一
- 分类目录非空
- 分类目录名符合规范

### 自动修复

- 空目录在启动时和关闭时自动删除

## 数据库配置

默认配置在 `asset_manager/db/config.py` 中定义。

可选：创建 `.env` 文件覆盖默认配置：

```env
DB_HOST=192.168.10.222
DB_PORT=15432
DB_NAME=dex_database
DB_USER=admin
DB_PASSWORD=your_password
```

**配置优先级**：.env 文件 > config.py 默认值

## 数据库同步

### 同步时机

- Ctrl+C 关闭应用时触发
- 同步前自动检查数据完整性，发现问题则取消同步

### 数据源

- scene.yaml - 手势-物体映射关系
- 文件系统扫描 - 手势分类和图片路径
- objects/\*/[object].yaml - 物体分类和路径

### 同步策略

增量同步：INSERT 新记录、UPDATE 变更记录、DELETE 删除记录

唯一键：(gesture, object) 组合

### 数据库表结构

`scenes` 表字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| scene_id | SERIAL | 场景记录唯一标识符 |
| gesture | VARCHAR(100) | 手势名称（如 001-Palmar-Pinch） |
| gesture_category | VARCHAR(50) | 手势分类（如 grasp） |
| gesture_image_path | VARCHAR(255) | 手势图片相对路径 |
| object | VARCHAR(100) | 物体名称（如 cube1） |
| object_category | VARCHAR(50) | 物体分类（如 cube） |
| object_folder_path | VARCHAR(255) | 物体文件夹相对路径 |
| created_at | TIMESTAMP | 记录创建时间 |
| updated_at | TIMESTAMP | 记录最后更新时间 |

约束：UNIQUE(gesture, object)

## 重要说明

### gestures.yaml

自动生成的缓存文件：
- 启动时自动扫描文件系统生成
- 所有功能直接读取文件系统，不依赖此文件
- 可以安全删除，下次启动自动重建

### scene.yaml

手势-物体映射关系的数据源：
- 存储映射关系（无法从文件系统推断）
- Web 应用依赖此文件
- 由 Scene Editor 自动管理
- **不应手动编辑**

## 依赖

- Python >= 3.13
- Flask >= 3.1.2
- PyYAML >= 6.0.3
- psycopg2-binary >= 2.9.11
- python-dotenv >= 1.2.1

使用 uv 管理依赖和虚拟环境。
