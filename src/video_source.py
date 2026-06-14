from __future__ import annotations

import logging
import os
import sys
import threading
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

_FFMPEG_ENV_LOCK = threading.Lock()
_CONNECT_ATTEMPTS = 3
_WARMUP_MAX_ATTEMPTS = 90


def _build_ffmpeg_capture_options(config: VideoSourceConfig, url: str) -> str | None:
    """Opciones FFmpeg para OpenCV (OPENCV_FFMPEG_CAPTURE_OPTIONS)."""
    if not url.lower().startswith("rtsp://"):
        extra = config.stream_ffmpeg_options.strip()
        return extra or None

    transport = (config.rtsp_transport or "tcp").lower()
    parts = [f"rtsp_transport;{transport}"]
    if transport == "tcp":
        parts.append("rtsp_flags;prefer_tcp")
    parts.extend(
        [
            "fflags;nobuffer",
            "flags;low_delay",
            "stimeout;10000000",
            "max_delay;500000",
            "reorder_queue_size;0",
        ]
    )
    extra = config.stream_ffmpeg_options.strip()
    if extra:
        parts.append(extra)
    return "|".join(parts)


def _open_ffmpeg_capture(config: VideoSourceConfig, url: str) -> cv2.VideoCapture:
    options = _build_ffmpeg_capture_options(config, url)
    with _FFMPEG_ENV_LOCK:
        if options:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options
        elif "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ:
            del os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

    capture.set(cv2.CAP_PROP_BUFFERSIZE, config.stream_buffer_size)
    if config.width > 0:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
    if config.height > 0:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
    return capture


def _valid_frame(frame: cv2.Mat | None) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _warmup_capture(capture: cv2.VideoCapture) -> bool:
    """Descarta frames hasta sincronizar con un keyframe H.264 válido."""
    for attempt in range(1, _WARMUP_MAX_ATTEMPTS + 1):
        try:
            ok, frame = capture.read()
        except cv2.error as exc:
            logger.debug("Warmup frame %d: %s", attempt, exc)
            ok, frame = False, None
        if ok and _valid_frame(frame):
            logger.debug("Stream sincronizado tras %d frame(s)", attempt)
            return True
        time.sleep(0.05)
    return False


def _safe_read(capture: cv2.VideoCapture) -> tuple[bool, cv2.Mat | None]:
    try:
        ok, frame = capture.read()
    except cv2.error as exc:
        logger.warning("Error leyendo frame del stream: %s", exc)
        return False, None
    return ok, frame


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
        if not self._connect(raise_on_failure=True):
            raise RuntimeError(
                f"No se pudo conectar al stream: {self.config.stream_url}"
            )

    @property
    def label(self) -> str:
        parsed = urlparse(self.config.stream_url)
        return f"stream {parsed.scheme}://{parsed.netloc}{parsed.path}"

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _connect(self, *, raise_on_failure: bool) -> bool:
        self._release_capture()
        url = self.config.stream_url
        logger.info("Conectando a stream %s", url)

        for attempt in range(1, _CONNECT_ATTEMPTS + 1):
            capture = _open_ffmpeg_capture(self.config, url)
            if not capture.isOpened():
                capture.release()
                logger.warning(
                    "Intento %d/%d: no se abrió el stream",
                    attempt,
                    _CONNECT_ATTEMPTS,
                )
                time.sleep(min(attempt, 2))
                continue

            if _warmup_capture(capture):
                self._capture = capture
                logger.info("Stream conectado")
                return True

            capture.release()
            logger.warning(
                "Intento %d/%d: stream abierto pero sin frames válidos (¿keyframe?)",
                attempt,
                _CONNECT_ATTEMPTS,
            )
            time.sleep(min(attempt, 2))

        if raise_on_failure:
            return False
        logger.error("No se pudo estabilizar el stream %s", url)
        return False

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def read(self) -> tuple[bool, cv2.Mat | None]:
        if self._capture is None:
            return False, None
        return _safe_read(self._capture)

    def frames(self) -> Iterator[cv2.Mat]:
        failures = 0
        while True:
            if not self.is_open:
                self._reconnect()
                continue

            ok, frame = self.read()
            if ok and _valid_frame(frame):
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
        self._release_capture()
        time.sleep(self.config.stream_reconnect_sec)
        while not self._connect(raise_on_failure=False):
            logger.warning(
                "Reintento de conexión en %ds...",
                self.config.stream_reconnect_sec,
            )
            time.sleep(self.config.stream_reconnect_sec)

    def release(self) -> None:
        self._release_capture()


@dataclass
class TuyaStreamSource:
    """Stream en vivo desde cámara Tuya (URL RTSP/HLS vía Cloud API)."""

    config: VideoSourceConfig
    store: AdminStore

    def __post_init__(self) -> None:
        self._capture: cv2.VideoCapture | None = None
        self._current_url = ""
        if not self._connect(raise_on_failure=True):
            raise RuntimeError(
                f"No se pudo abrir stream Tuya para {self.config.tuya_device_id}"
            )

    @property
    def label(self) -> str:
        return f"Tuya · {self.config.tuya_device_id[:12]}…"

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _connect(self, *, raise_on_failure: bool) -> bool:
        self._release_capture()

        client = self.store.get_tuya_client()
        if not client.is_configured:
            if raise_on_failure:
                raise RuntimeError(
                    "Tuya no configurado. Ve a Admin → Tuya y guarda Access ID, Key y UID"
                )
            return False

        stream_type = self.config.tuya_stream_type or "rtsp"
        self._current_url = client.allocate_stream(
            self.config.tuya_device_id, stream_type
        )
        logger.info("Conectando stream Tuya (%s)", stream_type)

        for attempt in range(1, _CONNECT_ATTEMPTS + 1):
            capture = _open_ffmpeg_capture(self.config, self._current_url)
            if not capture.isOpened():
                capture.release()
                time.sleep(min(attempt, 2))
                continue
            if _warmup_capture(capture):
                self._capture = capture
                logger.info("Stream Tuya conectado")
                return True
            capture.release()
            time.sleep(min(attempt, 2))

        if raise_on_failure:
            return False
        return False

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def read(self) -> tuple[bool, cv2.Mat | None]:
        if self._capture is None:
            return False, None
        return _safe_read(self._capture)

    def frames(self) -> Iterator[cv2.Mat]:
        failures = 0
        while True:
            if not self.is_open:
                self._reconnect()
                continue

            ok, frame = self.read()
            if ok and _valid_frame(frame):
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
        self._release_capture()
        self.store.invalidate_tuya_client()
        time.sleep(self.config.stream_reconnect_sec)
        while not self._connect(raise_on_failure=False):
            time.sleep(self.config.stream_reconnect_sec)

    def release(self) -> None:
        self._release_capture()


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
