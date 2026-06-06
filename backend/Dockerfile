FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install --no-cache-dir uv

# 先复制依赖文件并安装，利用 Docker 缓存（依赖不变时跳过）
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# 再复制应用代码（改动频繁，但不影响上层缓存）
COPY app ./app
COPY migrations ./migrations
RUN mkdir -p /app/config /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
