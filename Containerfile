# Imagen multi-arquitectura (linux/amd64, linux/arm64) para Podman/Docker
FROM docker.io/library/python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="webcam-follow" \
      org.opencontainers.image.description="Detección de movimiento, personas y objetos desde RTSP o webcam"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CONTAINER=1 \
    SHOW_PREVIEW=false \
    WEB_ENABLED=true \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080 \
    YOLO_DEVICE=cpu \
    PLATFORM=auto \
    SNAPSHOT_DIR=/app/snapshots

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN useradd --create-home --uid 1000 --shell /bin/bash appuser \
    && mkdir -p /app/snapshots \
    && chown -R appuser:appuser /app

COPY requirements-base.txt requirements-container.txt ./

RUN pip install --upgrade pip wheel \
    && pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements-container.txt

COPY main.py ./
COPY src/ ./src/
COPY scripts/container-entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh

USER appuser

# Descarga YOLOv8n en build (evita red en el primer arranque)
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

VOLUME ["/app/snapshots"]

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "main.py"]
