"""Compatibilidad: usar src.video_source en código nuevo."""

from src.video_source import LocalCameraSource as CameraStream, open_video_source

__all__ = ["CameraStream", "open_video_source"]
