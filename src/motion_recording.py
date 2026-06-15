from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2

logger = logging.getLogger(__name__)


class MotionRecorder:
    """Graba un clip MP4 cuando hay movimiento durante un tiempo configurable."""

    def __init__(self, output_dir: Path, camera_name: str) -> None:
        self.output_dir = output_dir
        self.camera_name = camera_name
        self._writer: cv2.VideoWriter | None = None
        self._recording_until = 0.0
        self._last_recording_end = 0.0
        self._output_path: Path | None = None
        self._fps = 15.0

    def process_frame(
        self,
        frame,
        *,
        motion_detected: bool,
        enabled: bool,
        duration_sec: float,
        cooldown_sec: float,
        fps: float,
    ) -> None:
        if not enabled:
            self.close()
            return

        if fps >= 1.0:
            self._fps = min(max(fps, 5.0), 30.0)

        now = time.monotonic()

        if self._writer is not None:
            self._writer.write(frame)
            if now >= self._recording_until:
                self._finish_recording()
            return

        if not motion_detected:
            return

        if cooldown_sec > 0 and now - self._last_recording_end < cooldown_sec:
            return

        self._start_recording(frame, duration_sec, now)

    def _start_recording(self, frame, duration_sec: float, now: float) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        height, width = frame.shape[:2]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"{timestamp}_movimiento.mp4"

        writer: cv2.VideoWriter | None = None
        for codec in ("mp4v", "avc1", "XVID"):
            candidate = cv2.VideoWriter(
                str(path),
                cv2.VideoWriter_fourcc(*codec),
                self._fps,
                (width, height),
            )
            if candidate.isOpened():
                writer = candidate
                break
            candidate.release()

        if writer is None:
            logger.error("[%s] No se pudo iniciar grabación de vídeo", self.camera_name)
            return

        self._writer = writer
        self._output_path = path
        self._recording_until = now + max(1.0, duration_sec)
        self._writer.write(frame)
        logger.info(
            "[%s] Grabación iniciada: %s (%.0f s)",
            self.camera_name,
            path.name,
            duration_sec,
        )

    def _finish_recording(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None

        self._last_recording_end = time.monotonic()
        path = self._output_path
        self._output_path = None

        if path is None:
            return

        if path.exists() and path.stat().st_size < 1024:
            path.unlink(missing_ok=True)
            logger.warning("[%s] Grabación vacía descartada", self.camera_name)
            return

        if path.exists():
            logger.info("[%s] Grabación guardada: %s", self.camera_name, path.name)

    def close(self) -> None:
        if self._writer is not None:
            self._finish_recording()
