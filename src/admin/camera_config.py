from __future__ import annotations

from pathlib import Path

from src.admin.models import Camera
from src.config import AppConfig, VideoSourceConfig


def camera_to_video_config(camera: Camera, app_config: AppConfig) -> VideoSourceConfig:
    base = app_config.video
    source_type = camera.source_type

    if source_type == "tuya":
        if not camera.tuya_device_id.strip():
            source_type = "local"
        else:
            return VideoSourceConfig(
                source_type="tuya",
                stream_url="",
                camera_index=camera.camera_index,
                width=0,
                height=0,
                camera_backend=base.camera_backend,
                stream_reconnect_sec=base.stream_reconnect_sec,
                stream_buffer_size=base.stream_buffer_size,
                stream_max_failures=base.stream_max_failures,
                rtsp_transport=camera.rtsp_transport or base.rtsp_transport,
                fallback_to_local=False,
                stream_read_timeout_ms=base.stream_read_timeout_ms,
                stream_open_timeout_ms=base.stream_open_timeout_ms,
                stream_ffmpeg_options=base.stream_ffmpeg_options,
                tuya_device_id=camera.tuya_device_id.strip(),
                tuya_stream_type=camera.tuya_stream_type or "rtsp",
            )

    if source_type == "stream" and not camera.stream_url.strip():
        source_type = "local"

    profile = app_config.platform
    default_width = 0 if source_type == "stream" else profile.camera_width
    default_height = 0 if source_type == "stream" else profile.camera_height

    return VideoSourceConfig(
        source_type=source_type,
        stream_url=camera.stream_url.strip(),
        camera_index=camera.camera_index,
        width=default_width,
        height=default_height,
        camera_backend=base.camera_backend,
        stream_reconnect_sec=base.stream_reconnect_sec,
        stream_buffer_size=base.stream_buffer_size,
        stream_max_failures=base.stream_max_failures,
        rtsp_transport=camera.rtsp_transport or base.rtsp_transport,
        fallback_to_local=base.fallback_to_local,
        stream_read_timeout_ms=base.stream_read_timeout_ms,
        stream_open_timeout_ms=base.stream_open_timeout_ms,
        stream_ffmpeg_options=base.stream_ffmpeg_options,
        tuya_device_id=camera.tuya_device_id,
        tuya_stream_type=camera.tuya_stream_type,
    )


def camera_snapshot_dir(app_config: AppConfig, camera_id: str) -> Path:
    return app_config.detection.snapshot_dir / camera_id
