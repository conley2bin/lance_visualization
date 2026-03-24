# syntax=docker/dockerfile:1
# ============================================
# Lance 可视化 FastAPI 服务镜像
# ============================================
FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

# 系统依赖
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl

# 安装 uv
ADD https://astral.sh/uv/install.sh /tmp/install-uv.sh
RUN sh /tmp/install-uv.sh && rm /tmp/install-uv.sh
ENV PATH="/root/.local/bin:$PATH"

# 安装 Python 依赖
COPY deploy/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system pip

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# chumpy（需要禁用构建隔离）和 manotorch
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-build-isolation \
    git+https://github.com/mattloper/chumpy

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system \
    git+https://github.com/lixiny/manotorch.git

# 复制应用代码（build context 为项目根目录）
COPY app.py .
COPY core ./core

RUN mkdir -p /data

EXPOSE 8868

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8868"]
