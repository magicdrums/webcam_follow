from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Camera:
    id: str
    name: str
    enabled: bool = True
    source_type: str = "local"
    stream_url: str = ""
    camera_index: int = 0
    rtsp_transport: str = "tcp"
    tuya_device_id: str = ""
    tuya_stream_type: str = "rtsp"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> Camera:
        return cls(id=str(uuid4()), name=name, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Camera:
        return cls(
            id=data["id"],
            name=data["name"],
            enabled=bool(data.get("enabled", True)),
            source_type=data.get("source_type", "local"),
            stream_url=data.get("stream_url", ""),
            camera_index=int(data.get("camera_index", 0)),
            rtsp_transport=data.get("rtsp_transport", "tcp"),
            tuya_device_id=data.get("tuya_device_id", ""),
            tuya_stream_type=data.get("tuya_stream_type", "rtsp"),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TuyaConfig:
    enabled: bool = False
    access_id: str = ""
    access_key: str = ""
    api_region: str = "eu"
    api_endpoint: str = ""
    uid: str = ""
    default_stream_type: str = "rtsp"
    updated_at: str = field(default_factory=_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TuyaConfig:
        return cls(
            enabled=bool(data.get("enabled", False)),
            access_id=data.get("access_id", ""),
            access_key=data.get("access_key", ""),
            api_region=data.get("api_region", "eu"),
            api_endpoint=data.get("api_endpoint", ""),
            uid=data.get("uid", ""),
            default_stream_type=data.get("default_stream_type", "rtsp"),
            updated_at=data.get("updated_at", _now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NotificationChannels:
    email_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    whatsapp_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    whatsapp_to: str = ""
    updated_at: str = field(default_factory=_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotificationChannels:
        return cls(
            email_enabled=bool(data.get("email_enabled", False)),
            smtp_host=data.get("smtp_host", "smtp.gmail.com"),
            smtp_port=int(data.get("smtp_port", 587)),
            smtp_user=data.get("smtp_user", ""),
            smtp_password=data.get("smtp_password", ""),
            email_from=data.get("email_from", ""),
            email_to=data.get("email_to", ""),
            telegram_enabled=bool(data.get("telegram_enabled", False)),
            telegram_bot_token=data.get("telegram_bot_token", ""),
            telegram_chat_id=data.get("telegram_chat_id", ""),
            whatsapp_enabled=bool(data.get("whatsapp_enabled", False)),
            twilio_account_sid=data.get("twilio_account_sid", ""),
            twilio_auth_token=data.get("twilio_auth_token", ""),
            twilio_whatsapp_from=data.get("twilio_whatsapp_from", ""),
            whatsapp_to=data.get("whatsapp_to", ""),
            updated_at=data.get("updated_at", _now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AlertRule:
    id: str
    name: str
    enabled: bool = True
    camera_ids: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=lambda: [
        "movimiento",
        "objeto_detectado",
        "cambio_objetos",
        "cambio_escena",
    ])
    notify_email: bool = False
    notify_telegram: bool = False
    notify_whatsapp: bool = False
    cooldown_sec: int = 60
    min_persons: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> AlertRule:
        return cls(id=str(uuid4()), name=name, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlertRule:
        return cls(
            id=data["id"],
            name=data["name"],
            enabled=bool(data.get("enabled", True)),
            camera_ids=list(data.get("camera_ids", [])),
            event_types=list(data.get("event_types", [])),
            notify_email=bool(data.get("notify_email", False)),
            notify_telegram=bool(data.get("notify_telegram", False)),
            notify_whatsapp=bool(data.get("notify_whatsapp", False)),
            cooldown_sec=int(data.get("cooldown_sec", 60)),
            min_persons=int(data.get("min_persons", 0)),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def matches_camera(self, camera_id: str) -> bool:
        return not self.camera_ids or camera_id in self.camera_ids

    def matches_event(self, event_type: str, person_count: int) -> bool:
        if not self.enabled:
            return False
        if event_type not in self.event_types:
            return False
        return person_count >= self.min_persons


@dataclass
class AlertHistoryEntry:
    id: str
    camera_id: str
    camera_name: str
    timestamp: str
    event_type: str
    message: str
    object_counts: dict[str, int]
    snapshot: str | None = None
    rule_id: str | None = None
    notified: bool = False

    @classmethod
    def create(
        cls,
        camera_id: str,
        camera_name: str,
        event_type: str,
        message: str,
        object_counts: dict[str, int],
        snapshot: str | None = None,
        rule_id: str | None = None,
        notified: bool = False,
    ) -> AlertHistoryEntry:
        return cls(
            id=str(uuid4()),
            camera_id=camera_id,
            camera_name=camera_name,
            timestamp=_now_iso(),
            event_type=event_type,
            message=message,
            object_counts=object_counts,
            snapshot=snapshot,
            rule_id=rule_id,
            notified=notified,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlertHistoryEntry:
        return cls(
            id=data["id"],
            camera_id=data["camera_id"],
            camera_name=data.get("camera_name", ""),
            timestamp=data["timestamp"],
            event_type=data["event_type"],
            message=data["message"],
            object_counts=dict(data.get("object_counts", {})),
            snapshot=data.get("snapshot"),
            rule_id=data.get("rule_id"),
            notified=bool(data.get("notified", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
