from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.platform import PlatformProfile, get_platform_profile, has_display, is_container

load_dotenv()

logger = logging.getLogger(__name__)

# IDs COCO frecuentes en vigilancia (persona, vehículos, animales)
DEFAULT_DETECT_CLASSES = (
    "0,1,2,3,5,7,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,32,39,41,56,57,58,59,60,62,63,64,65,66,67,72,73"
)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _parse_detect_classes(raw: str) -> list[int] | None:
    """None = detectar todas las clases COCO."""
    value = raw.strip()
    if not value or value.lower() in {"all", "*"}:
        return None
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _resolve_source_type() -> str:
    explicit = os.getenv("VIDEO_SOURCE", "").strip().lower()
    stream_url = os.getenv("STREAM_URL", "").strip()
    if explicit in {"local", "camera", "webcam"}:
        return "local"
    if explicit in {"stream", "rtsp", "http"}:
        if not stream_url:
            logger.warning(
                "VIDEO_SOURCE=stream pero STREAM_URL vacío; usando cámara local"
            )
            return "local"
        return "stream"
    if stream_url:
        return "stream"
    return "local"


def _default_fallback_to_local() -> bool:
    if os.getenv("STREAM_FALLBACK_LOCAL") is not None:
        return _env_bool("STREAM_FALLBACK_LOCAL", True)
    return not is_container()


@dataclass(frozen=True)
class VideoSourceConfig:
    source_type: str
    stream_url: str
    camera_index: int
    width: int
    height: int
    camera_backend: str
    stream_reconnect_sec: float
    stream_buffer_size: int
    stream_max_failures: int
    rtsp_transport: str
    fallback_to_local: bool
    stream_read_timeout_ms: int = 5000
    stream_open_timeout_ms: int = 10000
    stream_ffmpeg_options: str = ""
    tuya_device_id: str = ""
    tuya_stream_type: str = "rtsp"


@dataclass(frozen=True)
class DetectionConfig:
    motion_threshold: int
    min_motion_area: int
    yolo_confidence: float
    detection_interval_sec: float
    notification_cooldown_sec: float
    save_snapshots: bool
    snapshot_event_types: tuple[str, ...]
    snapshot_cooldown_sec: float
    snapshot_min_persons: int
    snapshot_dir: Path
    show_preview: bool
    yolo_model: str
    yolo_device: str
    yolo_imgsz: int
    yolo_on_motion_only: bool
    detect_classes: list[int] | None
    platform_label: str


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class WhatsAppConfig:
    enabled: bool
    account_sid: str
    auth_token: str
    from_number: str
    to_number: str


@dataclass(frozen=True)
class WebConfig:
    enabled: bool
    host: str
    port: int
    alerts_limit: int
    snapshots_limit: int


@dataclass(frozen=True)
class AppConfig:
    video: VideoSourceConfig
    detection: DetectionConfig
    email: EmailConfig
    telegram: TelegramConfig
    whatsapp: WhatsAppConfig
    web: WebConfig
    platform: PlatformProfile
    data_dir: Path


def _default_show_preview(profile: PlatformProfile) -> bool:
    if os.getenv("SHOW_PREVIEW") is not None:
        return _env_bool("SHOW_PREVIEW", profile.show_preview)
    if not has_display():
        return False
    return profile.show_preview


def _resolve_yolo_confidence(profile: PlatformProfile) -> float:
    if os.getenv("YOLO_CONFIDENCE"):
        return _env_float("YOLO_CONFIDENCE", profile.person_confidence)
    if os.getenv("PERSON_CONFIDENCE"):
        return _env_float("PERSON_CONFIDENCE", profile.person_confidence)
    return profile.person_confidence


def _default_web_enabled() -> bool:
    if os.getenv("WEB_ENABLED") is not None:
        return _env_bool("WEB_ENABLED", False)
    return is_container()


def load_config() -> AppConfig:
    profile = get_platform_profile()
    source_type = _resolve_source_type()
    stream_url = _env_str("STREAM_URL", "")

    width_raw = os.getenv("CAMERA_WIDTH", "").strip()
    height_raw = os.getenv("CAMERA_HEIGHT", "").strip()
    default_width = 0 if source_type == "stream" else profile.camera_width
    default_height = 0 if source_type == "stream" else profile.camera_height

    detect_raw = os.getenv("DETECT_CLASSES")
    if detect_raw is None or detect_raw.strip() == "":
        detect_raw = DEFAULT_DETECT_CLASSES

    return AppConfig(
        platform=profile,
        video=VideoSourceConfig(
            source_type=source_type,
            stream_url=stream_url,
            camera_index=_env_int("CAMERA_INDEX", 0),
            width=_env_int("CAMERA_WIDTH", default_width) if width_raw else default_width,
            height=_env_int("CAMERA_HEIGHT", default_height) if height_raw else default_height,
            camera_backend=_env_str("CAMERA_BACKEND", profile.camera_backend),
            stream_reconnect_sec=_env_float("STREAM_RECONNECT_SEC", 5),
            stream_buffer_size=_env_int("STREAM_BUFFER_SIZE", 1),
            stream_max_failures=_env_int("STREAM_MAX_FAILURES", 30),
            rtsp_transport=_env_str("RTSP_TRANSPORT", "tcp"),
            fallback_to_local=_default_fallback_to_local(),
            stream_read_timeout_ms=_env_int("STREAM_READ_TIMEOUT_MS", 5000),
            stream_open_timeout_ms=_env_int("STREAM_OPEN_TIMEOUT_MS", 10000),
            stream_ffmpeg_options=_env_str("STREAM_FFMPEG_OPTIONS", ""),
        ),
        detection=DetectionConfig(
            motion_threshold=_env_int("MOTION_THRESHOLD", 25),
            min_motion_area=_env_int("MIN_MOTION_AREA", profile.min_motion_area),
            yolo_confidence=_resolve_yolo_confidence(profile),
            detection_interval_sec=_env_float(
                "DETECTION_INTERVAL_SEC", profile.detection_interval_sec
            ),
            notification_cooldown_sec=_env_float("NOTIFICATION_COOLDOWN_SEC", 60),
            save_snapshots=_env_bool("SAVE_SNAPSHOTS", True),
            snapshot_event_types=(
                "objeto_detectado",
                "cambio_objetos",
                "cambio_escena",
            ),
            snapshot_cooldown_sec=_env_float("SNAPSHOT_COOLDOWN_SEC", 60),
            snapshot_min_persons=_env_int("SNAPSHOT_MIN_PERSONS", 0),
            snapshot_dir=Path(_env_str("SNAPSHOT_DIR", "snapshots")),
            show_preview=_default_show_preview(profile),
            yolo_model=_env_str("YOLO_MODEL", profile.yolo_model),
            yolo_device=_env_str("YOLO_DEVICE", profile.yolo_device),
            yolo_imgsz=_env_int("YOLO_IMGSZ", profile.yolo_imgsz),
            yolo_on_motion_only=_env_bool(
                "YOLO_ON_MOTION_ONLY", profile.yolo_on_motion_only
            ),
            detect_classes=_parse_detect_classes(detect_raw),
            platform_label=profile.label,
        ),
        email=EmailConfig(
            enabled=_env_bool("EMAIL_ENABLED", False),
            smtp_host=_env_str("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=_env_int("SMTP_PORT", 587),
            smtp_user=_env_str("SMTP_USER", ""),
            smtp_password=_env_str("SMTP_PASSWORD", ""),
            email_from=_env_str("EMAIL_FROM", ""),
            email_to=_env_str("EMAIL_TO", ""),
        ),
        telegram=TelegramConfig(
            enabled=_env_bool("TELEGRAM_ENABLED", False),
            bot_token=_env_str("TELEGRAM_BOT_TOKEN", ""),
            chat_id=_env_str("TELEGRAM_CHAT_ID", ""),
        ),
        whatsapp=WhatsAppConfig(
            enabled=_env_bool("WHATSAPP_ENABLED", False),
            account_sid=_env_str("TWILIO_ACCOUNT_SID", ""),
            auth_token=_env_str("TWILIO_AUTH_TOKEN", ""),
            from_number=_env_str("TWILIO_WHATSAPP_FROM", ""),
            to_number=_env_str("WHATSAPP_TO", ""),
        ),
        web=WebConfig(
            enabled=_default_web_enabled(),
            host=_env_str("WEB_HOST", "0.0.0.0"),
            port=_env_int("WEB_PORT", 8080),
            alerts_limit=_env_int("WEB_ALERTS_LIMIT", 50),
            snapshots_limit=_env_int("WEB_SNAPSHOTS_LIMIT", 24),
        ),
        data_dir=Path(_env_str("DATA_DIR", "data")),
    )
