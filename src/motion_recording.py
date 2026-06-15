from __future__ import annotations

import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_H264_ENCODERS = ("libx264", "libopenh264", "h264_vaapi", "h264_nvenc")
_OPENCV_CODECS = ("avc1", "mp4v", "XVID")
_WORKING_ENCODER: str | None = None
_FAILED_ENCODERS: set[str] = set()


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _pick_h264_encoder() -> str | None:
    global _WORKING_ENCODER

    if _WORKING_ENCODER:
        return _WORKING_ENCODER
    if not _ffmpeg_available():
        return None

    for encoder in _H264_ENCODERS:
        if encoder in _FAILED_ENCODERS:
            continue
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:d=0.1",
            "-frames:v",
            "1",
            "-an",
            "-c:v",
            encoder,
            "-f",
            "null",
            "-",
        ]
        if encoder == "libx264":
            cmd[cmd.index("-f", cmd.index("-c:v")) : cmd.index("-f", cmd.index("-c:v"))] = [
                "-preset",
                "veryfast",
            ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            _FAILED_ENCODERS.add(encoder)
            continue

        if result.returncode == 0:
            _WORKING_ENCODER = encoder
            logger.info("Grabación de vídeo: encoder H.264 seleccionado (%s)", encoder)
            return encoder

        _FAILED_ENCODERS.add(encoder)

    return None


def _transcode_mp4_for_browser(path: Path) -> bool:
    """Convierte MP4 de OpenCV (mp4v) a H.264 reproducible en navegadores."""
    if not _ffmpeg_available() or not path.is_file():
        return False

    encoder = _pick_h264_encoder()
    if not encoder:
        return False

    tmp = path.with_suffix(".browser.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-an",
        "-c:v",
        encoder,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    if encoder == "libx264":
        insert_at = cmd.index("-movflags")
        cmd[insert_at:insert_at] = ["-preset", "veryfast", "-crf", "23"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        tmp.unlink(missing_ok=True)
        return False

    if result.returncode == 0 and tmp.is_file() and tmp.stat().st_size >= 1024:
        tmp.replace(path)
        return True

    tmp.unlink(missing_ok=True)
    logger.warning("No se pudo transcodificar %s para navegador", path.name)
    return False


class MotionRecorder:
    """Graba un clip MP4 (H.264) cuando hay movimiento durante un tiempo configurable."""

    def __init__(self, output_dir: Path, camera_name: str) -> None:
        self.output_dir = output_dir
        self.camera_name = camera_name
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._writer: cv2.VideoWriter | None = None
        self._recording_until = 0.0
        self._last_recording_end = 0.0
        self._output_path: Path | None = None
        self._fps = 15.0
        self._used_opencv = False

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

        if self._is_recording():
            self._write_frame(frame)
            if now >= self._recording_until:
                self._finish_recording()
            return

        if not motion_detected:
            return

        if cooldown_sec > 0 and now - self._last_recording_end < cooldown_sec:
            return

        self._start_recording(frame, duration_sec, now)

    def _is_recording(self) -> bool:
        return self._ffmpeg is not None or self._writer is not None

    def _write_frame(self, frame) -> None:
        if self._ffmpeg is not None:
            if self._ffmpeg.poll() is not None:
                logger.error(
                    "[%s] ffmpeg terminó antes de tiempo (código %s)",
                    self.camera_name,
                    self._ffmpeg.returncode,
                )
                self._abort_recording()
                return
            payload = frame if frame.flags["C_CONTIGUOUS"] else np.ascontiguousarray(frame)
            try:
                self._ffmpeg.stdin.write(payload.tobytes())
            except (BrokenPipeError, OSError) as exc:
                logger.error("[%s] Error escribiendo frame en ffmpeg: %s", self.camera_name, exc)
                self._abort_recording()
            return

        if self._writer is not None:
            self._writer.write(frame)

    def _start_recording(self, frame, duration_sec: float, now: float) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        height, width = frame.shape[:2]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"{timestamp}_movimiento.mp4"

        if self._start_ffmpeg_recording(frame, path, width, height):
            self._output_path = path
            self._recording_until = now + max(1.0, duration_sec)
            logger.info(
                "[%s] Grabación iniciada (H.264): %s (%.0f s)",
                self.camera_name,
                path.name,
                duration_sec,
            )
            return

        if self._start_opencv_recording(frame, path, width, height):
            self._used_opencv = True
            self._output_path = path
            self._recording_until = now + max(1.0, duration_sec)
            logger.info(
                "[%s] Grabación iniciada (OpenCV): %s (%.0f s)",
                self.camera_name,
                path.name,
                duration_sec,
            )
            return

        logger.error("[%s] No se pudo iniciar grabación de vídeo", self.camera_name)

    def _start_ffmpeg_recording(
        self, frame, path: Path, width: int, height: int
    ) -> bool:
        encoder = _pick_h264_encoder()
        if not encoder:
            return False

        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            f"{width}x{height}",
            "-pix_fmt",
            "bgr24",
            "-r",
            str(self._fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            encoder,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ]
        if encoder == "libx264":
            insert_at = cmd.index("-movflags")
            cmd[insert_at:insert_at] = ["-preset", "veryfast", "-crf", "23"]

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError:
            return False

        self._ffmpeg = proc
        self._write_frame(frame)
        if self._ffmpeg is None or self._ffmpeg.poll() is not None:
            stderr = ""
            if proc.stderr:
                stderr = proc.stderr.read().decode("utf-8", errors="replace").strip()
            if stderr:
                logger.debug("[%s] ffmpeg no pudo iniciar grabación: %s", self.camera_name, stderr)
            path.unlink(missing_ok=True)
            global _WORKING_ENCODER
            _WORKING_ENCODER = None
            _FAILED_ENCODERS.add(encoder)
            return False

        return True

    def _start_opencv_recording(
        self, frame, path: Path, width: int, height: int
    ) -> bool:
        writer: cv2.VideoWriter | None = None
        for codec in _OPENCV_CODECS:
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
            return False

        self._writer = writer
        self._writer.write(frame)
        return True

    def _abort_recording(self) -> None:
        path = self._output_path
        if self._ffmpeg is not None:
            proc = self._ffmpeg
            self._ffmpeg = None
            if proc.stdin:
                proc.stdin.close()
            proc.kill()
            proc.wait(timeout=5)
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        self._output_path = None
        self._used_opencv = False
        if path and path.exists():
            path.unlink(missing_ok=True)

    def _finish_recording(self) -> None:
        used_opencv = self._used_opencv

        if self._ffmpeg is not None:
            proc = self._ffmpeg
            self._ffmpeg = None
            if proc.stdin:
                proc.stdin.close()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            if proc.returncode != 0:
                stderr = (proc.stderr.read() if proc.stderr else b"").decode(
                    "utf-8", errors="replace"
                )
                logger.error(
                    "[%s] ffmpeg falló al cerrar grabación: %s",
                    self.camera_name,
                    stderr.strip(),
                )

        if self._writer is not None:
            self._writer.release()
            self._writer = None

        self._last_recording_end = time.monotonic()
        path = self._output_path
        self._output_path = None
        self._used_opencv = False

        if path is None:
            return

        if path.exists() and path.stat().st_size < 1024:
            path.unlink(missing_ok=True)
            logger.warning("[%s] Grabación vacía descartada", self.camera_name)
            return

        if not path.exists():
            return

        if used_opencv:
            _transcode_mp4_for_browser(path)

        if path.exists() and path.stat().st_size < 1024:
            path.unlink(missing_ok=True)
            logger.warning("[%s] Grabación vacía descartada tras transcodificar", self.camera_name)
            return

        logger.info("[%s] Grabación guardada: %s", self.camera_name, path.name)

    def close(self) -> None:
        if self._is_recording():
            self._finish_recording()
