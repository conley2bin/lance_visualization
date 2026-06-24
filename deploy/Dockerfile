# ============================================
# Lance 可视化 FastAPI 服务镜像
# ============================================
FROM 183.195.186.154:180/dockerhub/library/python:3.10

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
RUN python -m pip install --no-cache-dir -i "${UV_INDEX_URL}" uv

# 安装 Python 依赖
COPY deploy/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system pip

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# chumpy 使用 PyPI 发布包，避免构建时直接 clone GitHub 受 TLS 波动影响。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-build-isolation \
    chumpy==0.70

# manotorch 暂无稳定 PyPI 发布包，保留 GitHub 安装并加重试。
RUN --mount=type=cache,target=/root/.cache/uv \
    for attempt in 1 2 3 4 5; do \
        uv pip install --system git+https://github.com/lixiny/manotorch.git && break; \
        if [ "$attempt" = "5" ]; then exit 1; fi; \
        sleep 5; \
    done

# 复制应用代码（build context 为项目根目录）
COPY app.py .
COPY core ./core

EXPOSE 8868

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8868"]
