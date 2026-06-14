from __future__ import annotations

import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator
from urllib.parse import urlparse

import cv2

from src.config import VideoSourceConfig

if TYPE_CHECKING:
    from src.admin.store import AdminStore

logger = logging.getLogger(__name__)


@dataclass
class LocalCameraSource:
    """Webcam local vía V4L2 o backend por defecto."""

    config: VideoSourceConfig

    def __post_init__(self) -> None:
        self._capture = self._open_local()
        if not self._capture.isOpened():
            raise RuntimeError(
                f"No se pudo abrir la cámara en el índice {self.config.camera_index}. "
                "Prueba otro CAMERA_INDEX (0, 1, 2…) o verifica /dev/video0"
            )
        if self.config.width > 0:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        if self.config.height > 0:
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        logger.info(
            "Cámara local abierta (índice %d, backend %s)",
            self.config.camera_index,
            self.config.camera_backend or "auto",
        )

    def _open_local(self) -> cv2.VideoCapture:
        backends: list[int] = []
        backend = self.config.camera_backend
        if backend == "v4l2" or (backend == "auto" and sys.platform == "linux"):
            backends.append(cv2.CAP_V4L2)
        backends.append(cv2.CAP_ANY)

        last_capture: cv2.VideoCapture | None = None
        for api in backends:
            capture = cv2.VideoCapture(self.config.camera_index, api)
            last_capture = capture
            if capture.isOpened():
                return capture
            capture.release()

        if last_capture is not None:
            return last_capture
        return cv2.VideoCapture(self.config.camera_index)

    @property
    def label(self) -> str:
        return f"cámara local (índice {self.config.camera_index})"

    @property
    def is_open(self) -> bool:
        return self._capture.isOpened()

    def read(self) -> tuple[bool, cv2.Mat | None]:
        return self._capture.read()

    def frames(self) -> Iterator[cv2.Mat]:
        while self.is_open:
            ok, frame = self.read()
            if not ok or frame is None:
                logger.warning("Frame no recibido de la cámara local")
                break
            yield frame

    def release(self) -> None:
        self._capture.release()


@dataclass
class StreamSource:
    """Stream de red: RTSP (v4l2rtspserver), HTTP/MJPEG, etc."""

    config: VideoSourceConfig

    def __post_init__(self) -> None:
        if not self.config.stream_url:
            raise RuntimeError("STREAM_URL es obligatorio para fuente stream")
        self._capture: cv2.VideoCapture | None = None
        self._connect()

    @property
    def label(self) -> str:
        parsed = urlparse(self.config.stream_url)
        return f"stream {parsed.scheme}://{parsed.netloc}{parsed.path}"

    def _connect(self) -> None:
        if self._capture is not None:
            self._capture.release()

        if (
            self.config.stream_url.lower().startswith("rtsp://")
            and self.config.rtsp_transport == "tcp"
        ):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        logger.info("Conectando a stream %s", self.config.stream_url)
        capture = cv2.VideoCapture(self.config.stream_url, cv2.CAP_FFMPEG)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self.config.stream_buffer_size)

        if self.config.width > 0:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        if self.config.height > 0:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)

        if not capture.isOpened():
            raise RuntimeError(
                f"No se pudo conectar al stream: {self.config.stream_url}"
            )

        self._capture = capture
        logger.info("Stream conectado")

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def read(self) -> tuple[bool, cv2.Mat | None]:
        if self._capture is None:
            return False, None
        return self._capture.read()

    def frames(self) -> Iterator[cv2.Mat]:
        failures = 0
        while True:
            if not self.is_open:
                self._reconnect()
                continue

            ok, frame = self.read()
            if ok and frame is not None:
                failures = 0
                yield frame
                continue

            failures += 1
            logger.warning(
                "Frame no recibido del stream (%d/%d)",
                failures,
                self.config.stream_max_failures,
            )
            if failures < self.config.stream_max_failures:
                time.sleep(0.1)
                continue

            self._reconnect()
            failures = 0

    def _reconnect(self) -> None:
        logger.warning(
            "Reconectando al stream en %ds...",
            self.config.stream_reconnect_sec,
        )
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        time.sleep(self.config.stream_reconnect_sec)
        self._connect()

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


@dataclass
class TuyaStreamSource:
    """Stream en vivo desde cámara Tuya (URL RTSP/HLS vía Cloud API)."""

    config: VideoSourceConfig
    store: AdminStore

    def __post_init__(self) -> None:
        self._capture: cv2.VideoCapture | None = None
        self._current_url = ""
        self._connect()

    @property
    def label(self) -> str:
        return f"Tuya · {self.config.tuya_device_id[:12]}…"

    def _connect(self) -> None:
        if self._capture is not None:
            self._capture.release()

        client = self.store.get_tuya_client()
        if not client.is_configured:
            raise RuntimeError(
                "Tuya no configurado. Ve a Admin → Tuya y guarda Access ID, Key y UID"
            )

        stream_type = self.config.tuya_stream_type or "rtsp"
        self._current_url = client.allocate_stream(
            self.config.tuya_device_id, stream_type
        )

        if self._current_url.lower().startswith("rtsp://") and self.config.rtsp_transport == "tcp":
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        logger.info("Conectando stream Tuya (%s)", stream_type)
        capture = cv2.VideoCapture(self._current_url, cv2.CAP_FFMPEG)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self.config.stream_buffer_size)

        if not capture.isOpened():
            raise RuntimeError(
                f"No se pudo abrir stream Tuya para {self.config.tuya_device_id}"
            )

        self._capture = capture
        logger.info("Stream Tuya conectado")

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def read(self) -> tuple[bool, cv2.Mat | None]:
        if self._capture is None:
            return False, None
        return self._capture.read()

    def frames(self) -> Iterator[cv2.Mat]:
        failures = 0
        while True:
            if not self.is_open:
                self._reconnect()
                continue

            ok, frame = self.read()
            if ok and frame is not None:
                failures = 0
                yield frame
                continue

            failures += 1
            if failures < self.config.stream_max_failures:
                time.sleep(0.1)
                continue
            self._reconnect()
            failures = 0

    def _reconnect(self) -> None:
        logger.warning(
            "Renovando stream Tuya en %ds (URLs expiran)…",
            self.config.stream_reconnect_sec,
        )
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self.store.invalidate_tuya_client()
        time.sleep(self.config.stream_reconnect_sec)
        self._connect()

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class VideoSource(ABC):
    label: str

    @abstractmethod
    def frames(self) -> Iterator[cv2.Mat]:
        pass

    @abstractmethod
    def release(self) -> None:
        pass


def open_video_source(
    config: VideoSourceConfig,
    store: AdminStore | None = None,
) -> VideoSource:
    if config.source_type == "local":
        return LocalCameraSource(config)

    if config.source_type == "tuya":
        if store is None:
            raise RuntimeError("Cámara Tuya requiere AdminStore")
        return TuyaStreamSource(config, store)

    try:
        return StreamSource(config)
    except RuntimeError as exc:
        if not config.fallback_to_local:
            raise
        logger.warning("%s", exc)
        logger.warning(
            "Fallback: usando cámara local (índice %d). "
            "Desactiva con STREAM_FALLBACK_LOCAL=false",
            config.camera_index,
        )
        return LocalCameraSource(config)
