from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from src.admin.models import (
    AlertHistoryEntry,
    AlertRule,
    Camera,
    DEFAULT_SNAPSHOT_EVENT_TYPES,
    NotificationChannels,
    SnapshotSettings,
    TuyaConfig,
    YoloSettings,
)
from src.admin.yolo_config import build_detection_config
from src.admin.channels import channels_from_app_config
from src.integrations.tuya.client import TuyaClient

if TYPE_CHECKING:
    from src.config import AppConfig, DetectionConfig

logger = logging.getLogger(__name__)


class AdminStore:
    MAX_HISTORY = 500

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cameras_file = self.data_dir / "cameras.json"
        self._rules_file = self.data_dir / "alert_rules.json"
        self._history_file = self.data_dir / "alert_history.json"
        self._channels_file = self.data_dir / "notification_channels.json"
        self._tuya_file = self.data_dir / "tuya_config.json"
        self._snapshots_file = self.data_dir / "snapshot_settings.json"
        self._yolo_file = self.data_dir / "yolo_settings.json"
        self._lock = threading.Lock()
        self._tuya_client: TuyaClient | None = None

    def bootstrap_from_env(self, config: AppConfig) -> None:
        with self._lock:
            if not self._cameras_file.exists() or not self._load_list(self._cameras_file):
                camera = Camera.create(
                    name="Cámara principal",
                    enabled=True,
                    source_type=config.video.source_type,
                    stream_url=config.video.stream_url,
                    camera_index=config.video.camera_index,
                    rtsp_transport=config.video.rtsp_transport,
                )
                self._save_list(self._cameras_file, [camera.to_dict()])
                logger.info("Cámara inicial creada desde .env (%s)", camera.id)

            if not self._rules_file.exists() or not self._load_list(self._rules_file):
                rule = AlertRule.create(
                    name="Alerta general",
                    enabled=True,
                    notify_email=config.email.enabled,
                    notify_telegram=config.telegram.enabled,
                    notify_whatsapp=config.whatsapp.enabled,
                    cooldown_sec=int(config.detection.notification_cooldown_sec),
                )
                self._save_list(self._rules_file, [rule.to_dict()])
                logger.info("Regla de alerta inicial creada (%s)", rule.id)

            if not self._history_file.exists():
                self._save_list(self._history_file, [])

            if not self._channels_file.exists():
                channels = channels_from_app_config(config)
                self._save_object(self._channels_file, channels.to_dict())
                logger.info("Canales de notificación inicializados desde .env")

            if not self._tuya_file.exists():
                tuya = _tuya_from_app_config(config)
                self._save_object(self._tuya_file, tuya.to_dict())
                logger.info("Configuración Tuya inicializada")

            if not self._snapshots_file.exists():
                snap = _snapshot_settings_from_app_config(config)
                self._save_object(self._snapshots_file, snap.to_dict())
                logger.info("Configuración de capturas inicializada")

            if not self._yolo_file.exists():
                yolo = _yolo_settings_from_app_config(config)
                self._save_object(self._yolo_file, yolo.to_dict())
                logger.info("Configuración YOLO inicializada desde .env")

    def get_tuya_config(self) -> TuyaConfig:
        with self._lock:
            data = self._load_object(self._tuya_file)
            if not data:
                return TuyaConfig()
            return TuyaConfig.from_dict(data)

    def update_tuya_config(self, tuya: TuyaConfig) -> TuyaConfig:
        with self._lock:
            self._save_object(self._tuya_file, tuya.to_dict())
        self._tuya_client = None
        return tuya

    def get_tuya_client(self) -> TuyaClient:
        config = self.get_tuya_config()
        if self._tuya_client is None:
            self._tuya_client = TuyaClient(config)
        return self._tuya_client

    def invalidate_tuya_client(self) -> None:
        self._tuya_client = None

    @staticmethod
    def _load_object(path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _save_object(path: Path, data: dict) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    @staticmethod
    def _load_list(path: Path) -> list[dict]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []

    @staticmethod
    def _save_list(path: Path, items: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(items, handle, indent=2, ensure_ascii=False)

    def list_cameras(self, enabled_only: bool = False) -> list[Camera]:
        with self._lock:
            cameras = [Camera.from_dict(item) for item in self._load_list(self._cameras_file)]
        if enabled_only:
            cameras = [camera for camera in cameras if camera.enabled]
        return cameras

    def get_camera(self, camera_id: str) -> Camera | None:
        for camera in self.list_cameras():
            if camera.id == camera_id:
                return camera
        return None

    def add_camera(self, camera: Camera) -> Camera:
        with self._lock:
            items = self._load_list(self._cameras_file)
            items.append(camera.to_dict())
            self._save_list(self._cameras_file, items)
        return camera

    def update_camera(self, camera_id: str, updates: dict) -> Camera | None:
        with self._lock:
            items = self._load_list(self._cameras_file)
            for index, raw in enumerate(items):
                if raw["id"] != camera_id:
                    continue
                raw.update(updates)
                from src.admin.models import _now_iso

                raw["updated_at"] = _now_iso()
                items[index] = raw
                self._save_list(self._cameras_file, items)
                return Camera.from_dict(raw)
        return None

    def delete_camera(self, camera_id: str) -> bool:
        with self._lock:
            items = self._load_list(self._cameras_file)
            new_items = [item for item in items if item["id"] != camera_id]
            if len(new_items) == len(items):
                return False
            self._save_list(self._cameras_file, new_items)
        return True

    def list_alert_rules(self) -> list[AlertRule]:
        with self._lock:
            return [AlertRule.from_dict(item) for item in self._load_list(self._rules_file)]

    def get_alert_rule(self, rule_id: str) -> AlertRule | None:
        for rule in self.list_alert_rules():
            if rule.id == rule_id:
                return rule
        return None

    def add_alert_rule(self, rule: AlertRule) -> AlertRule:
        with self._lock:
            items = self._load_list(self._rules_file)
            items.append(rule.to_dict())
            self._save_list(self._rules_file, items)
        return rule

    def update_alert_rule(self, rule_id: str, updates: dict) -> AlertRule | None:
        with self._lock:
            items = self._load_list(self._rules_file)
            for index, raw in enumerate(items):
                if raw["id"] != rule_id:
                    continue
                raw.update(updates)
                from src.admin.models import _now_iso

                raw["updated_at"] = _now_iso()
                items[index] = raw
                self._save_list(self._rules_file, items)
                return AlertRule.from_dict(raw)
        return None

    def delete_alert_rule(self, rule_id: str) -> bool:
        with self._lock:
            items = self._load_list(self._rules_file)
            new_items = [item for item in items if item["id"] != rule_id]
            if len(new_items) == len(items):
                return False
            self._save_list(self._rules_file, new_items)
        return True

    def matching_rules(
        self, camera_id: str, event_type: str, person_count: int
    ) -> list[AlertRule]:
        return [
            rule
            for rule in self.list_alert_rules()
            if rule.matches_camera(camera_id)
            and rule.matches_event(event_type, person_count)
        ]

    def add_history(self, entry: AlertHistoryEntry) -> None:
        with self._lock:
            items = self._load_list(self._history_file)
            items.insert(0, entry.to_dict())
            del items[self.MAX_HISTORY :]
            self._save_list(self._history_file, items)

    def list_history(self, limit: int = 100, camera_id: str | None = None) -> list[AlertHistoryEntry]:
        with self._lock:
            items = self._load_list(self._history_file)
        entries = [AlertHistoryEntry.from_dict(item) for item in items]
        if camera_id:
            entries = [entry for entry in entries if entry.camera_id == camera_id]
        return entries[:limit]

    def clear_history(self) -> None:
        with self._lock:
            self._save_list(self._history_file, [])

    def delete_history_entry(self, entry_id: str) -> bool:
        with self._lock:
            items = self._load_list(self._history_file)
            new_items = [item for item in items if item["id"] != entry_id]
            if len(new_items) == len(items):
                return False
            self._save_list(self._history_file, new_items)
        return True

    def get_notification_channels(self) -> NotificationChannels:
        with self._lock:
            return NotificationChannels.from_dict(self._load_object(self._channels_file))

    def update_notification_channels(self, channels: NotificationChannels) -> NotificationChannels:
        with self._lock:
            self._save_object(self._channels_file, channels.to_dict())
        return channels

    def get_snapshot_settings(self) -> SnapshotSettings:
        with self._lock:
            data = self._load_object(self._snapshots_file)
            if not data:
                return SnapshotSettings()
            return SnapshotSettings.from_dict(data)

    def update_snapshot_settings(self, settings: SnapshotSettings) -> SnapshotSettings:
        from src.admin.models import _now_iso

        data = settings.to_dict()
        data["updated_at"] = _now_iso()
        updated = SnapshotSettings.from_dict(data)
        with self._lock:
            self._save_object(self._snapshots_file, updated.to_dict())
        return updated

    def get_yolo_settings(self) -> YoloSettings:
        with self._lock:
            data = self._load_object(self._yolo_file)
            if not data:
                return YoloSettings()
            return YoloSettings.from_dict(data)

    def update_yolo_settings(self, settings: YoloSettings) -> YoloSettings:
        from src.admin.models import _now_iso

        data = settings.to_dict()
        data["updated_at"] = _now_iso()
        updated = YoloSettings.from_dict(data)
        with self._lock:
            self._save_object(self._yolo_file, updated.to_dict())
        return updated

    def build_detection_config(self, config: AppConfig) -> DetectionConfig:
        return build_detection_config(config.detection, self.get_yolo_settings())


def _tuya_from_app_config(config: AppConfig) -> TuyaConfig:
    import os

    access_id = os.getenv("TUYA_ACCESS_ID", "")
    access_key = os.getenv("TUYA_ACCESS_KEY", "")
    uid = os.getenv("TUYA_UID", "")
    return TuyaConfig(
        enabled=bool(access_id and access_key and uid),
        access_id=access_id,
        access_key=access_key,
        uid=uid,
        api_region=os.getenv("TUYA_API_REGION", "eu"),
        api_endpoint=os.getenv("TUYA_API_ENDPOINT", ""),
        default_stream_type=os.getenv("TUYA_STREAM_TYPE", "rtsp"),
    )


def _snapshot_settings_from_app_config(config: AppConfig) -> SnapshotSettings:
    return SnapshotSettings(
        retention_days=_env_int("SNAPSHOT_RETENTION_DAYS", 30),
        max_per_camera=_env_int("SNAPSHOT_MAX_PER_CAMERA", 500),
        cleanup_interval_sec=_env_int("SNAPSHOT_CLEANUP_INTERVAL_SEC", 3600),
    )


def _yolo_settings_from_app_config(config: AppConfig) -> YoloSettings:
    import os

    det = config.detection
    raw = os.getenv("DETECT_CLASSES", "").strip()
    if raw.lower() in {"all", "*"}:
        mode, custom = "all", ""
    elif raw:
        mode, custom = "custom", raw
    else:
        mode, custom = "default", ""

    return YoloSettings(
        yolo_confidence=det.yolo_confidence,
        yolo_imgsz=det.yolo_imgsz,
        yolo_on_motion_only=det.yolo_on_motion_only,
        yolo_model=det.yolo_model,
        yolo_device=det.yolo_device,
        detect_classes_mode=mode,
        detect_classes_custom=custom,
        motion_threshold=det.motion_threshold,
        min_motion_area=det.min_motion_area,
        detection_interval_sec=det.detection_interval_sec,
        save_snapshots=det.save_snapshots,
        snapshot_event_types=list(DEFAULT_SNAPSHOT_EVENT_TYPES),
        snapshot_cooldown_sec=det.notification_cooldown_sec,
        snapshot_min_persons=0,
        heatmap_enabled=True,
        heatmap_opacity=0.45,
        heatmap_decay=0.96,
        motion_prediction_enabled=True,
    )


def _env_int(name: str, default: int) -> int:
    import os

    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
