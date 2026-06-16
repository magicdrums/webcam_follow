from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from src.admin.camera_config import camera_snapshot_dir, camera_to_video_config
from src.admin.snapshots import SnapshotRetentionWorker, SnapshotService
from src.admin.models import AlertHistoryEntry
from src.admin.store import AdminStore
from src.detector import DetectionEvent, EventType, VisionDetector
from src.admin.notifications import StoreNotificationService
from src.motion_analytics import MotionAnalytics
from src.motion_recording import MotionRecorder, TimedClipRecorder
from src.notifier import save_snapshot
from src.platform import log_platform_info
from src.video_source import open_video_source

if TYPE_CHECKING:
    from src.admin.models import Camera
    from src.config import AppConfig, DetectionConfig

logger = logging.getLogger(__name__)

PRIORITY = {
    EventType.HAND_GESTURE: 6,
    EventType.OBJECT_CHANGE: 5,
    EventType.SCENE_CHANGE: 4,
    EventType.OBJECT: 3,
    EventType.MOTION: 2,
}


def _pick_primary_event(events: list[DetectionEvent]) -> DetectionEvent:
    return max(events, key=lambda event: PRIORITY.get(event.event_type, 0))


def _pick_snapshot_event(
    events: list[DetectionEvent],
    allowed_types: tuple[str, ...],
    min_persons: int,
) -> DetectionEvent | None:
    allowed = set(allowed_types)
    qualifying = [
        event
        for event in events
        if event.event_type.value in allowed
        and (min_persons <= 0 or event.person_count >= min_persons)
    ]
    if not qualifying:
        return None
    return max(qualifying, key=lambda event: PRIORITY.get(event.event_type, 0))


@dataclass
class LiveStatus:
    camera_id: str = ""
    camera_name: str = ""
    motion_detected: bool = False
    motion_area: int = 0
    object_counts: dict[str, int] = field(default_factory=dict)
    person_count: int = 0
    total_objects: int = 0
    yolo_active: bool = False
    fps: float = 0.0
    video_label: str = ""
    platform_label: str = ""
    stream_url: str = ""
    connected: bool = False
    last_update: str = ""
    hot_zones: list[dict] = field(default_factory=list)
    motion_prediction: dict = field(default_factory=dict)
    heatmap_peak: float = 0.0
    heatmap_enabled: bool = True
    surveillance_armed: bool = True


@dataclass
class AlertRecord:
    camera_id: str
    camera_name: str
    timestamp: str
    event_type: str
    message: str
    object_counts: dict[str, int]
    snapshot: str | None = None


class CameraWorker:
    MAX_ALERTS = 100
    JPEG_QUALITY = 80

    def __init__(
        self,
        camera: Camera,
        app_config: AppConfig,
        store: AdminStore,
    ) -> None:
        self.camera = camera
        self.app_config = app_config
        self.store = store
        self.snapshot_dir = camera_snapshot_dir(app_config, camera.id)
        self.video_config = camera_to_video_config(camera, app_config)
        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._status = LiveStatus(camera_id=camera.id, camera_name=camera.name)
        self._alerts: list[AlertRecord] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._rule_cooldowns: dict[str, float] = {}
        self._last_snapshot_at = 0.0
        self._settings_version = ""
        self._motion_analytics = MotionAnalytics()
        self._motion_recorder = MotionRecorder(
            self.snapshot_dir, self.camera.name
        )
        self._timed_clip: TimedClipRecorder | None = None
        self._clip_lock = threading.Lock()
        self._last_frame_mono = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"camera-{self.camera.id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def get_jpeg_frame(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def get_status(self) -> LiveStatus:
        with self._lock:
            status = replace(self._status)
            if (
                status.connected
                and self._last_frame_mono > 0
                and time.monotonic() - self._last_frame_mono > 20.0
            ):
                status.connected = False
            return status

    def get_motion_analytics(self) -> MotionAnalytics:
        return self._motion_analytics

    def reset_motion_analytics(self) -> None:
        self._motion_analytics.reset()

    def get_heatmap_jpeg(self) -> bytes | None:
        image = self._motion_analytics.render_heatmap_image()
        if image is None:
            return None
        ok, encoded = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )
        return encoded.tobytes() if ok else None

    def get_alerts(self, limit: int = 50) -> list[AlertRecord]:
        with self._lock:
            return list(self._alerts[:limit])

    def list_snapshots(self, limit: int = 24) -> list[dict[str, str]]:
        if not self.snapshot_dir.exists():
            return []
        files = sorted(
            (
                *self.snapshot_dir.glob("*.jpg"),
                *self.snapshot_dir.glob("*.mp4"),
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [
            {
                "name": path.name,
                "url": f"/snapshots/{self.camera.id}/{path.name}",
                "time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "kind": "video" if path.suffix.lower() == ".mp4" else "image",
            }
            for path in files[:limit]
        ]

    def capture_photo_file(self) -> Path | None:
        jpeg = self.get_jpeg_frame()
        if not jpeg:
            return None
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return None
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = (
            self.snapshot_dir
            / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_telegram_foto.jpg"
        )
        if not cv2.imwrite(str(path), image):
            return None
        return path

    def record_timed_clip(
        self,
        duration_sec: float,
        *,
        suffix: str = "telegram",
        timeout_extra: float = 20.0,
    ) -> Path | None:
        with self._clip_lock:
            if self._timed_clip is not None and not self._timed_clip.done.is_set():
                return None
            clip = TimedClipRecorder(
                self.snapshot_dir,
                self.camera.name,
                duration_sec,
                suffix=suffix,
            )
            self._timed_clip = clip

        if not clip.done.wait(duration_sec + timeout_extra + 30):
            with self._clip_lock:
                if self._timed_clip is clip:
                    self._timed_clip = None
            return None

        with self._clip_lock:
            if self._timed_clip is clip:
                self._timed_clip = None
        return clip.result_path

    def get_latest_media_file(self) -> Path | None:
        items = self.list_snapshots(limit=1)
        if not items:
            return None
        path = self.snapshot_dir / items[0]["name"]
        return path if path.is_file() else None

    def _feed_timed_clip(self, frame, fps: float) -> None:
        with self._clip_lock:
            clip = self._timed_clip
        if clip is None or clip.done.is_set():
            return
        clip.write_frame(frame, fps)
        if clip.done.is_set():
            with self._clip_lock:
                if self._timed_clip is clip:
                    self._timed_clip = None

    def _should_notify_rule(self, rule_id: str, cooldown_sec: int) -> bool:
        elapsed = time.monotonic() - self._rule_cooldowns.get(rule_id, 0.0)
        return elapsed >= cooldown_sec

    def _snapshot_cooldown_ok(self, cooldown_sec: float) -> bool:
        return time.monotonic() - self._last_snapshot_at >= cooldown_sec

    def _show_heatmap(self, yolo_settings) -> bool:
        return bool(yolo_settings.heatmap_enabled and self.camera.heatmap_enabled)

    def _process_motion_recording(
        self, frame, motion_detected: bool, yolo_settings, fps: float
    ) -> None:
        if not self.store.get_security_state().armed:
            return
        self._motion_recorder.process_frame(
            frame,
            motion_detected=motion_detected,
            enabled=yolo_settings.motion_recording_enabled,
            duration_sec=yolo_settings.motion_recording_duration_sec,
            cooldown_sec=yolo_settings.motion_recording_cooldown_sec,
            fps=fps,
        )

    def _handle_events(
        self,
        events: list[DetectionEvent],
        frame,
        notifications: StoreNotificationService,
    ) -> None:
        if not events:
            return
        if not self.store.get_security_state().armed:
            return

        gesture_events = [
            event for event in events if event.event_type == EventType.HAND_GESTURE
        ]
        other_events = [
            event for event in events if event.event_type != EventType.HAND_GESTURE
        ]

        for event in gesture_events:
            self._dispatch_event(event, frame, notifications)

        if other_events:
            primary = _pick_primary_event(other_events)
            self._dispatch_event(primary, frame, notifications)

    def _dispatch_event(
        self,
        primary: DetectionEvent,
        frame,
        notifications: StoreNotificationService,
    ) -> None:
        snapshot_name = None
        snapshot_path = None
        detection = self.store.build_detection_config(self.app_config)

        rules = self.store.matching_rules(
            self.camera.id,
            primary.event_type.value,
            primary.person_count,
            gesture=primary.gesture,
        )
        pending_rules = [
            rule
            for rule in rules
            if self._should_notify_rule(rule.id, rule.cooldown_sec)
        ]

        if detection.save_snapshots:
            snapshot_event = _pick_snapshot_event(
                [primary],
                detection.snapshot_event_types,
                detection.snapshot_min_persons,
            )
            if snapshot_event and self._snapshot_cooldown_ok(
                detection.snapshot_cooldown_sec
            ):
                snapshot_path = save_snapshot(
                    frame, self.snapshot_dir, snapshot_event
                )
                snapshot_name = snapshot_path.name
                self._last_snapshot_at = time.monotonic()
            elif pending_rules and snapshot_path is None:
                snapshot_path = save_snapshot(
                    frame, self.snapshot_dir, primary
                )
                snapshot_name = snapshot_path.name
                self._last_snapshot_at = time.monotonic()

        notified = False
        if pending_rules:
            for rule in pending_rules:
                logger.info(
                    "Alerta [%s] regla '%s': %s",
                    self.camera.name,
                    rule.name,
                    primary.message,
                )
                notifications.notify(
                    primary,
                    snapshot_path,
                    camera_id=self.camera.id,
                    camera_name=self.camera.name,
                    use_email=rule.notify_email,
                    use_telegram=rule.notify_telegram,
                    use_whatsapp=rule.notify_whatsapp,
                    use_webhook=rule.notify_webhook,
                )
                self._rule_cooldowns[rule.id] = time.monotonic()
                notified = True
        elif rules:
            logger.info(
                "Alerta [%s]: %s (reglas en cooldown, no notificado)",
                self.camera.name,
                primary.message,
            )
        else:
            logger.info(
                "Alerta [%s]: %s (sin regla coincidente, no notificado)",
                self.camera.name,
                primary.message,
            )

        history = AlertHistoryEntry.create(
            camera_id=self.camera.id,
            camera_name=self.camera.name,
            event_type=primary.event_type.value,
            message=primary.message,
            object_counts=dict(primary.object_counts),
            snapshot=snapshot_name,
            notified=notified,
        )
        self.store.add_history(history)

        record = AlertRecord(
            camera_id=self.camera.id,
            camera_name=self.camera.name,
            timestamp=primary.timestamp.isoformat(),
            event_type=primary.event_type.value,
            message=primary.message,
            object_counts=dict(primary.object_counts),
            snapshot=snapshot_name,
        )
        with self._lock:
            self._alerts.insert(0, record)
            del self._alerts[self.MAX_ALERTS :]

    def _update_fps(self, frame_count: int, fps_timer: float) -> tuple[int, float, float]:
        frame_count += 1
        now = time.monotonic()
        elapsed = now - fps_timer
        fps = self._status.fps
        if elapsed >= 1.0:
            fps = round(frame_count / elapsed, 1)
            frame_count = 0
            fps_timer = now
        return frame_count, fps_timer, fps

    def _publish_frame(
        self,
        frame,
        motion_detected: bool,
        motion_area: int,
        object_counts: dict[str, int],
        yolo_active: bool,
        fps: float,
        motion_snapshot: dict | None = None,
    ) -> None:
        ok, encoded = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.JPEG_QUALITY]
        )
        if not ok:
            return

        status = LiveStatus(
            camera_id=self.camera.id,
            camera_name=self.camera.name,
            motion_detected=motion_detected,
            motion_area=motion_area,
            object_counts=object_counts,
            person_count=object_counts.get("person", 0),
            total_objects=sum(object_counts.values()),
            yolo_active=yolo_active,
            fps=fps,
            video_label=self._status.video_label,
            platform_label=self.app_config.detection.platform_label,
            stream_url=self._mask_stream_url(self.video_config.stream_url),
            connected=True,
            last_update=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            hot_zones=(motion_snapshot or {}).get("hot_zones", []),
            motion_prediction=(motion_snapshot or {}).get("prediction", {}),
            heatmap_peak=(motion_snapshot or {}).get("peak_intensity", 0.0),
            heatmap_enabled=self.camera.heatmap_enabled,
            surveillance_armed=self.store.get_security_state().armed,
        )
        with self._lock:
            self._latest_jpeg = encoded.tobytes()
            self._status = status
            self._last_frame_mono = time.monotonic()

    @staticmethod
    def _mask_stream_url(url: str) -> str:
        if not url:
            return ""
        if "@" in url:
            scheme, rest = url.split("://", 1)
            if "@" in rest:
                _, host_part = rest.rsplit("@", 1)
                return f"{scheme}://***@{host_part}"
        return url

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._run_capture_loop()
            except RuntimeError as exc:
                logger.error("[%s] %s", self.camera.name, exc)
                with self._lock:
                    self._status.connected = False
                if self._stop.is_set():
                    break
                time.sleep(5)

    def _sync_detector(
        self, detector: VisionDetector | None, detection: DetectionConfig
    ) -> VisionDetector:
        settings = self.store.get_yolo_settings()
        if detector is None or settings.updated_at != self._settings_version:
            if detector is None:
                detector = VisionDetector(detection)
            else:
                detector.update_config(detection)
            self._settings_version = settings.updated_at
        return detector

    def _run_capture_loop(self) -> None:
        video = open_video_source(self.video_config, self.store)
        detector: VisionDetector | None = None
        notifications = StoreNotificationService(self.store)

        with self._lock:
            self._status.video_label = video.label

        logger.info("[%s] Fuente activa: %s", self.camera.name, video.label)
        last_detection = 0.0
        last_motion = False
        last_motion_area = 0
        last_counts: dict[str, int] = {}
        last_yolo_active = False
        frame_count = 0
        fps_timer = time.monotonic()

        try:
            for frame in video.frames():
                if self._stop.is_set():
                    break

                try:
                    detection = self.store.build_detection_config(self.app_config)
                    detector = self._sync_detector(detector, detection)
                    yolo_settings = self.store.get_yolo_settings()
                    show_heatmap = self._show_heatmap(yolo_settings)

                    now = time.monotonic()
                    frame_count, fps_timer, fps = self._update_fps(
                        frame_count, fps_timer
                    )
                    with self._lock:
                        self._status.fps = fps

                    if now - last_detection < detection.detection_interval_sec:
                        display = frame
                        snap_dict = self._motion_analytics.snapshot.to_dict()
                        if show_heatmap or yolo_settings.motion_prediction_enabled:
                            self._motion_analytics.update(
                                None,
                                frame.shape,
                                decay=yolo_settings.heatmap_decay,
                                enable_prediction=False,
                                enable_heatmap=show_heatmap,
                            )
                            snap_dict = self._motion_analytics.snapshot.to_dict()
                            display = self._motion_analytics.render_overlay(
                                frame,
                                opacity=yolo_settings.heatmap_opacity,
                                show_heatmap=show_heatmap,
                                show_prediction=yolo_settings.motion_prediction_enabled,
                            )
                        self._publish_frame(
                            display,
                            last_motion,
                            last_motion_area,
                            last_counts,
                            last_yolo_active,
                            fps,
                            snap_dict,
                        )
                        self._feed_timed_clip(frame, fps)
                        self._process_motion_recording(
                            display, last_motion, yolo_settings, fps
                        )
                        continue

                    last_detection = now
                    events, annotated, motion_mask = detector.analyze(frame)

                    yolo_settings = self.store.get_yolo_settings()
                    show_heatmap = self._show_heatmap(yolo_settings)
                    analytics_snap = self._motion_analytics.update(
                        motion_mask,
                        frame.shape,
                        decay=yolo_settings.heatmap_decay,
                        enable_prediction=yolo_settings.motion_prediction_enabled,
                        enable_heatmap=show_heatmap,
                    )
                    if show_heatmap or yolo_settings.motion_prediction_enabled:
                        annotated = self._motion_analytics.render_overlay(
                            annotated,
                            opacity=yolo_settings.heatmap_opacity,
                            prediction=analytics_snap.prediction,
                            show_heatmap=show_heatmap,
                            show_prediction=yolo_settings.motion_prediction_enabled,
                        )

                    self._handle_events(events, annotated, notifications)

                    last_motion = any(
                        e.event_type == EventType.MOTION for e in events
                    )
                    for event in events:
                        if event.motion_area:
                            last_motion_area = event.motion_area
                    if events:
                        last_counts = dict(events[-1].object_counts)
                    if not detection.surveillance_armed:
                        last_counts = {}
                    last_yolo_active = detection.surveillance_armed and (
                        not detection.yolo_on_motion_only or last_motion
                    )

                    self._publish_frame(
                        annotated,
                        last_motion,
                        last_motion_area,
                        last_counts,
                        last_yolo_active,
                        fps,
                        analytics_snap.to_dict(),
                    )
                    self._feed_timed_clip(frame, fps)
                    self._process_motion_recording(
                        annotated, last_motion, yolo_settings, fps
                    )
                except Exception:
                    logger.exception(
                        "[%s] Error procesando frame; se continúa",
                        self.camera.name,
                    )
        finally:
            self._motion_recorder.close()
            video.release()
            with self._lock:
                self._status.connected = False
            if not self._stop.is_set() and self.video_config.source_type == "local":
                raise RuntimeError("Fuente de video interrumpida")


class MonitorManager:
    def __init__(self, app_config: AppConfig, store: AdminStore) -> None:
        self.app_config = app_config
        self.store = store
        self._workers: dict[str, CameraWorker] = {}
        self._active_camera_id: str | None = None
        self._lock = threading.Lock()
        self._started = False
        self._snapshot_service = SnapshotService(app_config.detection.snapshot_dir)
        self._retention_worker: SnapshotRetentionWorker | None = None
        self._telegram_bot: TelegramBotWorker | None = None

    def start(self) -> None:
        if self._started:
            self.reload()
            return
        log_platform_info(self.app_config.platform)
        self.store.bootstrap_from_env(self.app_config)
        self.reload()
        self._start_retention_worker()
        self._start_telegram_bot()
        self._started = True

    def stop(self) -> None:
        if self._telegram_bot:
            self._telegram_bot.stop()
            self._telegram_bot = None
        if self._retention_worker:
            self._retention_worker.stop()
            self._retention_worker = None
        for worker in list(self._workers.values()):
            worker.stop()
        self._workers.clear()
        self._started = False

    def reload(self) -> None:
        cameras = self.store.list_cameras(enabled_only=True)
        enabled_ids = {camera.id for camera in cameras}

        for camera_id in list(self._workers):
            if camera_id not in enabled_ids:
                self._workers[camera_id].stop()
                del self._workers[camera_id]

        for camera in cameras:
            if camera.id in self._workers:
                worker = self._workers[camera.id]
                worker.stop()
            worker = CameraWorker(camera, self.app_config, self.store)
            self._workers[camera.id] = worker
            worker.start()

        with self._lock:
            if not self._active_camera_id and cameras:
                self._active_camera_id = cameras[0].id
            elif self._active_camera_id and self._active_camera_id not in enabled_ids:
                self._active_camera_id = cameras[0].id if cameras else None

    def set_active_camera(self, camera_id: str) -> bool:
        if camera_id not in self._workers:
            return False
        with self._lock:
            self._active_camera_id = camera_id
        return True

    def get_active_camera_id(self) -> str | None:
        with self._lock:
            return self._active_camera_id

    def get_worker(self, camera_id: str | None = None) -> CameraWorker | None:
        cid = camera_id or self.get_active_camera_id()
        if not cid:
            return None
        return self._workers.get(cid)

    def _managed_cameras(self) -> list[Camera]:
        """Cámaras habilitadas con worker activo (misma lista que usa la web)."""
        return [
            camera
            for camera in self.store.list_cameras(enabled_only=True)
            if camera.id in self._workers
        ]

    def _camera_connected(self, camera_id: str) -> bool:
        worker = self._workers.get(camera_id)
        if not worker:
            return False
        status = worker.get_status()
        return bool(status and status.connected)

    def default_camera_id(self) -> str | None:
        """Cámara por defecto para comandos sin argumento (p. ej. /foto)."""
        managed = self._managed_cameras()
        if not managed:
            return None

        managed_ids = {camera.id for camera in managed}
        active = self.get_active_camera_id()

        if active and active in managed_ids and self._camera_connected(active):
            return active

        for camera in managed:
            if self._camera_connected(camera.id):
                self.set_active_camera(camera.id)
                return camera.id

        if active and active in managed_ids:
            return active

        default_id = managed[0].id
        self.set_active_camera(default_id)
        return default_id

    def list_cameras_summary(self) -> list[dict]:
        result = []
        for camera in self._managed_cameras():
            worker = self._workers[camera.id]
            status = worker.get_status()
            result.append(
                {
                    "id": camera.id,
                    "name": camera.name,
                    "enabled": camera.enabled,
                    "source_type": camera.source_type,
                    "stream_url": camera.stream_url,
                    "tuya_device_id": camera.tuya_device_id,
                    "camera_index": camera.camera_index,
                    "connected": status.connected if status else False,
                    "fps": status.fps if status else 0,
                    "active": camera.id == self.get_active_camera_id(),
                }
            )
        return result

    def get_jpeg_frame(self, camera_id: str | None = None) -> bytes | None:
        worker = self.get_worker(camera_id)
        return worker.get_jpeg_frame() if worker else None

    def get_status(self, camera_id: str | None = None) -> LiveStatus | None:
        worker = self.get_worker(camera_id)
        return worker.get_status() if worker else None

    def get_heatmap_jpeg(self, camera_id: str | None = None) -> bytes | None:
        worker = self.get_worker(camera_id)
        return worker.get_heatmap_jpeg() if worker else None

    def reset_motion_analytics(self, camera_id: str | None = None) -> bool:
        worker = self.get_worker(camera_id)
        if not worker:
            return False
        worker.reset_motion_analytics()
        return True

    def get_alerts(self, limit: int = 50, camera_id: str | None = None) -> list[AlertRecord]:
        if camera_id:
            worker = self.get_worker(camera_id)
            return worker.get_alerts(limit) if worker else []
        merged: list[AlertRecord] = []
        for worker in self._workers.values():
            merged.extend(worker.get_alerts(limit))
        merged.sort(key=lambda item: item.timestamp, reverse=True)
        return merged[:limit]

    def list_snapshots(self, limit: int = 24, camera_id: str | None = None) -> list[dict]:
        if camera_id:
            worker = self.get_worker(camera_id)
            return worker.list_snapshots(limit) if worker else []
        merged: list[dict] = []
        for worker in self._workers.values():
            merged.extend(worker.list_snapshots(limit))
        merged.sort(key=lambda item: item["time"], reverse=True)
        return merged[:limit]

    @property
    def snapshot_service(self) -> SnapshotService:
        return self._snapshot_service

    def run_snapshot_cleanup(self) -> int:
        settings = self.store.get_snapshot_settings()
        return self._snapshot_service.apply_retention(settings)

    def _start_retention_worker(self) -> None:
        if self._retention_worker and self._retention_worker.is_alive():
            return
        self._retention_worker = SnapshotRetentionWorker(
            self._snapshot_service,
            self.store.get_snapshot_settings,
        )
        self._retention_worker.start()
        deleted = self._retention_worker.run_once()
        if deleted:
            logger.info("Limpieza inicial de capturas: %d eliminada(s)", deleted)

    def _start_telegram_bot(self) -> None:
        if self._telegram_bot and self._telegram_bot.is_alive():
            return
        from src.telegram_bot import TelegramBotWorker

        self._telegram_bot = TelegramBotWorker(self, self.store)
        self._telegram_bot.start()

    def resolve_camera_id(self, token: str | None) -> str | None:
        managed = self._managed_cameras()
        if not managed:
            return None
        if not token or not token.strip():
            return self.default_camera_id()

        needle = token.strip().lower()

        for camera in managed:
            if camera.name.lower() == needle:
                return camera.id

        name_matches = [c for c in managed if needle in c.name.lower()]
        if len(name_matches) == 1:
            return name_matches[0].id

        id_matches = [c for c in managed if c.id.lower().startswith(needle)]
        if len(id_matches) == 1:
            return id_matches[0].id

        return None

    def capture_photo(self, camera_id: str | None = None) -> Path | None:
        worker = self.get_worker(camera_id)
        return worker.capture_photo_file() if worker else None

    def capture_video(
        self, camera_id: str | None = None, duration_sec: float = 10.0
    ) -> Path | None:
        worker = self.get_worker(camera_id)
        return worker.record_timed_clip(duration_sec) if worker else None

    def get_latest_media(self, camera_id: str | None = None) -> Path | None:
        worker = self.get_worker(camera_id)
        return worker.get_latest_media_file() if worker else None

    def wait_for_motion(
        self, camera_id: str | None = None, max_wait_sec: float = 60.0
    ) -> bool:
        deadline = time.monotonic() + max(1.0, max_wait_sec)
        while time.monotonic() < deadline:
            status = self.get_status(camera_id)
            if status and status.motion_detected:
                return True
            time.sleep(0.4)
        return False

    def get_security_state(self) -> dict:
        return self.store.get_security_state().to_dict()

    def set_surveillance_armed(self, armed: bool, *, source: str = "web") -> dict:
        state = self.store.set_security_state(armed=armed, source=source)
        label = "armado" if armed else "desarmado"
        logger.info("Sistema %s (origen: %s)", label, source)
        return state.to_dict()
