# ============================================
# Lance 可视化 FastAPI 服务镜像
# ============================================
FROM 192.168.10.11/dockerhub/library/python:3.10

WORKDIR /app

# 环境变量：使用清华源加速 PyPI 和 PyTorch 下载
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_EXTRA_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pytorch/whl/cpu/

# 替换 Debian 源为清华镜像（避免 DNS 解析问题）
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources

# 系统依赖
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（使用 pip 安装，稳定可靠）
RUN python -m pip install --no-cache-dir -i "${UV_INDEX_URL}" uv

# 复制并安装 Python 依赖
COPY deploy/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system pip

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# 安装 chumpy（禁用构建隔离，保留依赖）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-build-isolation \
    git+https://github.com/mattloper/chumpy

# 安装 manotorch
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system \
    git+https://github.com/lixiny/manotorch.git

# 复制应用代码（构建上下文为项目根目录）
COPY app.py .
COPY core ./core

EXPOSE 8868

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8868"]