# ============================================
# Lance 可视化 FastAPI 服务镜像
# ============================================
FROM 183.195.186.154:180/dockerhub/library/python:3.10

WORKDIR /app

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG PYTORCH_CPU_WHEEL_URL=https://download.pytorch.org/whl/cpu/torch-2.5.1%2Bcpu-cp310-cp310-linux_x86_64.whl

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

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
RUN python -m pip install --no-cache-dir -i "${UV_INDEX_URL}" uv

# 安装 Python 依赖
COPY deploy/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system pip

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps "${PYTORCH_CPU_WHEEL_URL}"

# chumpy（需要禁用构建隔离）和 manotorch
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-build-isolation --no-deps \
    git+https://github.com/mattloper/chumpy

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system \
    git+https://github.com/lixiny/manotorch.git

# 复制应用代码（build context 为项目根目录）
COPY app.py .
COPY core ./core

EXPOSE 8868

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8868"]
