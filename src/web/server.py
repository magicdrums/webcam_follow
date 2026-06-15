from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory

from src.admin.channels import channels_to_public_dict, merge_channel_updates
from src.admin.tuya_config import merge_tuya_updates, tuya_to_public_dict
from src.admin.yolo_config import (
    COCO_CLASSES,
    DETECT_PRESETS,
    merge_yolo_updates,
    yolo_settings_to_public_dict,
)
from src.integrations.tuya.client import TuyaClientError
from src.admin.models import AlertRule, Camera, SnapshotSettings
from src.admin.notifications import StoreNotificationService
from src.admin.store import AdminStore
from src.config import AppConfig
from src.monitor_manager import MonitorManager

logger = logging.getLogger(__name__)


def create_app(manager: MonitorManager, config: AppConfig, store: AdminStore) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    snapshot_root = config.detection.snapshot_dir.resolve()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/admin")
    def admin():
        return render_template("admin.html")

    def _camera_id_from_request() -> str | None:
        return request.args.get("camera_id") or manager.get_active_camera_id()

    @app.get("/video_feed")
    def video_feed():
        """MJPEG clásico (Chrome/Firefox en escritorio). Móviles usan /api/frame."""
        camera_id = _camera_id_from_request()

        def generate():
            while True:
                frame = manager.get_jpeg_frame(camera_id)
                if frame:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    )
                time.sleep(0.05)

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/api/frame")
    def api_frame():
        """Frame JPEG único — compatible con Safari iOS y navegadores móviles."""
        camera_id = _camera_id_from_request()
        status = manager.get_status(camera_id)
        frame = manager.get_jpeg_frame(camera_id)
        if not frame:
            abort(404, description="Sin frame disponible")
        headers = {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        if status and not status.connected:
            headers["X-Frame-Stale"] = "1"
        return Response(
            frame,
            mimetype="image/jpeg",
            headers=headers,
        )

    @app.get("/api/cameras")
    def api_cameras():
        return jsonify(manager.list_cameras_summary())

    @app.post("/api/cameras/active")
    def api_set_active_camera():
        payload = request.get_json(silent=True) or {}
        camera_id = payload.get("camera_id")
        if not camera_id or not manager.set_active_camera(camera_id):
            abort(400, description="Cámara no válida")
        return jsonify({"ok": True, "camera_id": camera_id})

    @app.get("/api/status")
    def api_status():
        status = manager.get_status(_camera_id_from_request())
        if not status:
            return jsonify({"connected": False})
        return jsonify(asdict(status))

    @app.get("/api/motion/heatmap")
    def api_heatmap_image():
        camera_id = _camera_id_from_request()
        jpeg = manager.get_heatmap_jpeg(camera_id)
        if not jpeg:
            abort(404, description="Sin datos de mapa de calor")
        return Response(jpeg, mimetype="image/jpeg")

    @app.post("/api/motion/heatmap/reset")
    def api_heatmap_reset():
        camera_id = _camera_id_from_request()
        if not manager.reset_motion_analytics(camera_id):
            abort(404, description="Cámara no encontrada")
        return jsonify({"ok": True})

    @app.get("/api/alerts")
    def api_alerts():
        camera_id = request.args.get("camera_id")
        alerts = manager.get_alerts(config.web.alerts_limit, camera_id)
        return jsonify([asdict(alert) for alert in alerts])

    @app.get("/api/snapshots")
    def api_snapshots():
        camera_id = request.args.get("camera_id")
        return jsonify(manager.list_snapshots(config.web.snapshots_limit, camera_id))

    @app.get("/snapshots/<camera_id>/<path:filename>")
    def snapshot_file(camera_id: str, filename: str):
        safe = Path(filename).name
        directory = snapshot_root / camera_id
        target = directory / safe
        if not target.is_file():
            abort(404)
        return send_from_directory(directory, safe)

    # --- Admin API: cámaras ---
    @app.get("/api/admin/cameras")
    def admin_list_cameras():
        return jsonify([camera.to_dict() for camera in store.list_cameras()])

    @app.post("/api/admin/cameras")
    def admin_create_camera():
        payload = request.get_json(silent=True) or {}
        name = (payload.get("name") or "").strip()
        if not name:
            abort(400, description="Nombre obligatorio")
        source_type = payload.get("source_type", "local")
        if source_type == "tuya" and not (payload.get("tuya_device_id") or "").strip():
            abort(400, description="tuya_device_id obligatorio para cámaras Tuya")
        camera = Camera.create(
            name=name,
            enabled=bool(payload.get("enabled", True)),
            source_type=payload.get("source_type", "local"),
            stream_url=payload.get("stream_url", ""),
            camera_index=int(payload.get("camera_index", 0)),
            rtsp_transport=payload.get("rtsp_transport", "tcp"),
            tuya_device_id=payload.get("tuya_device_id", ""),
            tuya_stream_type=payload.get("tuya_stream_type", "rtsp"),
            heatmap_enabled=bool(payload.get("heatmap_enabled", True)),
        )
        store.add_camera(camera)
        manager.reload()
        return jsonify(camera.to_dict()), 201

    # --- Admin API: YOLO / detección ---
    @app.get("/api/admin/yolo/config")
    def admin_get_yolo_config():
        return jsonify(yolo_settings_to_public_dict(store.get_yolo_settings()))

    @app.get("/api/admin/yolo/classes")
    def admin_yolo_classes():
        return jsonify({"classes": COCO_CLASSES, "presets": DETECT_PRESETS})

    @app.put("/api/admin/yolo/config")
    def admin_update_yolo_config():
        payload = request.get_json(silent=True) or {}
        current = store.get_yolo_settings()
        updated = merge_yolo_updates(current, payload)
        if updated.yolo_confidence < 0.05 or updated.yolo_confidence > 1:
            abort(400, description="yolo_confidence debe estar entre 0.05 y 1")
        if updated.yolo_imgsz < 160 or updated.yolo_imgsz > 1280:
            abort(400, description="yolo_imgsz debe estar entre 160 y 1280")
        if updated.detection_interval_sec < 0.1 or updated.detection_interval_sec > 60:
            abort(400, description="detection_interval_sec debe estar entre 0.1 y 60")
        if updated.detect_classes_mode not in {"default", "all", "custom"}:
            abort(400, description="detect_classes_mode inválido")
        if updated.heatmap_opacity < 0.05 or updated.heatmap_opacity > 0.95:
            abort(400, description="heatmap_opacity debe estar entre 0.05 y 0.95")
        if updated.heatmap_decay < 0.8 or updated.heatmap_decay > 0.999:
            abort(400, description="heatmap_decay debe estar entre 0.8 y 0.999")
        if updated.snapshot_cooldown_sec < 0:
            abort(400, description="snapshot_cooldown_sec no puede ser negativo")
        if updated.snapshot_min_persons < 0:
            abort(400, description="snapshot_min_persons no puede ser negativo")
        if updated.save_snapshots and not updated.snapshot_event_types:
            abort(400, description="Selecciona al menos un tipo de evento para capturas")
        store.update_yolo_settings(updated)
        return jsonify(yolo_settings_to_public_dict(updated))

    # --- Admin API: capturas ---
    snapshot_service = manager.snapshot_service

    @app.get("/api/admin/snapshots/config")
    def admin_get_snapshot_config():
        return jsonify(store.get_snapshot_settings().to_dict())

    @app.put("/api/admin/snapshots/config")
    def admin_update_snapshot_config():
        payload = request.get_json(silent=True) or {}
        current = store.get_snapshot_settings()
        retention_days = int(payload.get("retention_days", current.retention_days))
        max_per_camera = int(payload.get("max_per_camera", current.max_per_camera))
        cleanup_interval_sec = int(
            payload.get("cleanup_interval_sec", current.cleanup_interval_sec)
        )
        settings = store.update_snapshot_settings(
            SnapshotSettings(
                retention_days=max(0, retention_days),
                max_per_camera=max(0, max_per_camera),
                cleanup_interval_sec=max(60, cleanup_interval_sec),
            )
        )
        return jsonify(settings.to_dict())

    @app.get("/api/admin/snapshots/stats")
    def admin_snapshot_stats():
        return jsonify(
            snapshot_service.stats(store.list_cameras())
        )

    @app.get("/api/admin/snapshots")
    def admin_list_snapshots():
        camera_id = request.args.get("camera_id") or None
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
        return jsonify(
            snapshot_service.list_snapshots(
                store.list_cameras(),
                camera_id=camera_id,
                limit=limit,
                offset=offset,
            )
        )

    @app.post("/api/admin/snapshots/cleanup")
    def admin_snapshot_cleanup():
        deleted = manager.run_snapshot_cleanup()
        return jsonify({"ok": True, "deleted": deleted})

    @app.delete("/api/admin/snapshots/<camera_id>/<filename>")
    def admin_delete_snapshot(camera_id: str, filename: str):
        if not snapshot_service.delete(camera_id, filename):
            abort(404)
        return jsonify({"ok": True})

    @app.delete("/api/admin/snapshots/<camera_id>")
    def admin_delete_camera_snapshots(camera_id: str):
        deleted = snapshot_service.delete_camera(camera_id)
        return jsonify({"ok": True, "deleted": deleted})

    @app.put("/api/admin/cameras/<camera_id>")
    def admin_update_camera(camera_id: str):
        payload = request.get_json(silent=True) or {}
        allowed = {
            "name", "enabled", "source_type", "stream_url",
            "camera_index", "rtsp_transport", "tuya_device_id", "tuya_stream_type",
            "heatmap_enabled",
        }
        updates = {key: payload[key] for key in allowed if key in payload}
        if updates.get("source_type") == "tuya":
            device_id = updates.get("tuya_device_id")
            if device_id is not None and not str(device_id).strip():
                abort(400, description="tuya_device_id obligatorio para cámaras Tuya")
        camera = store.update_camera(camera_id, updates)
        if not camera:
            abort(404)
        manager.reload()
        return jsonify(camera.to_dict())

    @app.delete("/api/admin/cameras/<camera_id>")
    def admin_delete_camera(camera_id: str):
        if not store.delete_camera(camera_id):
            abort(404)
        manager.reload()
        return jsonify({"ok": True})

    # --- Admin API: reglas de alerta ---
    @app.get("/api/admin/alert-rules")
    def admin_list_rules():
        return jsonify([rule.to_dict() for rule in store.list_alert_rules()])

    @app.post("/api/admin/alert-rules")
    def admin_create_rule():
        payload = request.get_json(silent=True) or {}
        name = (payload.get("name") or "").strip()
        if not name:
            abort(400, description="Nombre obligatorio")
        rule = AlertRule.create(
            name=name,
            enabled=bool(payload.get("enabled", True)),
            camera_ids=list(payload.get("camera_ids", [])),
            event_types=list(payload.get("event_types", [
                "movimiento", "objeto_detectado", "cambio_objetos", "cambio_escena",
            ])),
            notify_email=bool(payload.get("notify_email", False)),
            notify_telegram=bool(payload.get("notify_telegram", False)),
            notify_whatsapp=bool(payload.get("notify_whatsapp", False)),
            cooldown_sec=int(payload.get("cooldown_sec", 60)),
            min_persons=int(payload.get("min_persons", 0)),
        )
        store.add_alert_rule(rule)
        return jsonify(rule.to_dict()), 201

    @app.put("/api/admin/alert-rules/<rule_id>")
    def admin_update_rule(rule_id: str):
        payload = request.get_json(silent=True) or {}
        allowed = {
            "name", "enabled", "camera_ids", "event_types",
            "notify_email", "notify_telegram", "notify_whatsapp",
            "cooldown_sec", "min_persons",
        }
        updates = {key: payload[key] for key in allowed if key in payload}
        rule = store.update_alert_rule(rule_id, updates)
        if not rule:
            abort(404)
        return jsonify(rule.to_dict())

    @app.delete("/api/admin/alert-rules/<rule_id>")
    def admin_delete_rule(rule_id: str):
        if not store.delete_alert_rule(rule_id):
            abort(404)
        return jsonify({"ok": True})

    # --- Admin API: historial ---
    @app.get("/api/admin/alerts/history")
    def admin_alert_history():
        camera_id = request.args.get("camera_id")
        limit = int(request.args.get("limit", config.web.alerts_limit))
        entries = store.list_history(limit, camera_id)
        return jsonify([entry.to_dict() for entry in entries])

    @app.delete("/api/admin/alerts/history")
    def admin_clear_history():
        store.clear_history()
        return jsonify({"ok": True})

    @app.delete("/api/admin/alerts/history/<entry_id>")
    def admin_delete_history(entry_id: str):
        if not store.delete_history_entry(entry_id):
            abort(404)
        return jsonify({"ok": True})

    # --- Admin API: canales de notificación ---
    @app.get("/api/admin/channels")
    def admin_get_channels():
        channels = store.get_notification_channels()
        return jsonify(channels_to_public_dict(channels))

    @app.put("/api/admin/channels")
    def admin_update_channels():
        payload = request.get_json(silent=True) or {}
        current = store.get_notification_channels()
        updated = merge_channel_updates(current, payload)
        store.update_notification_channels(updated)
        return jsonify(channels_to_public_dict(updated))

    @app.post("/api/admin/channels/test")
    def admin_test_channel():
        payload = request.get_json(silent=True) or {}
        channel = (payload.get("channel") or "").strip().lower()
        if channel not in {"email", "telegram", "whatsapp"}:
            abort(400, description="Canal inválido")
        try:
            StoreNotificationService(store).test_channel(channel)
        except ValueError as exc:
            abort(400, description=str(exc))
        except Exception as exc:
            logger.exception("Error en prueba de canal %s", channel)
            abort(500, description=str(exc))
        return jsonify({"ok": True, "message": f"Prueba enviada por {channel}"})

    # --- Admin API: Tuya IoT ---
    @app.get("/api/admin/tuya/config")
    def admin_get_tuya_config():
        return jsonify(tuya_to_public_dict(store.get_tuya_config()))

    @app.put("/api/admin/tuya/config")
    def admin_update_tuya_config():
        payload = request.get_json(silent=True) or {}
        current = store.get_tuya_config()
        updated = merge_tuya_updates(current, payload)
        store.update_tuya_config(updated)
        return jsonify(tuya_to_public_dict(updated))

    @app.post("/api/admin/tuya/test")
    def admin_test_tuya():
        client = store.get_tuya_client()
        if not client.is_configured:
            abort(400, description="Tuya no configurado (Access ID, Key, UID y activar integración)")
        try:
            result = client.test_connection()
        except TuyaClientError as exc:
            abort(400, description=str(exc))
        except Exception as exc:
            logger.exception("Error probando Tuya")
            abort(500, description=str(exc))
        return jsonify(result)

    @app.get("/api/admin/tuya/devices")
    def admin_list_tuya_devices():
        client = store.get_tuya_client()
        if not client.is_configured:
            abort(400, description="Tuya no configurado (Access ID, Key, UID y activar integración)")
        try:
            devices = client.list_devices()
        except TuyaClientError as exc:
            abort(400, description=str(exc))
        return jsonify(devices)

    @app.post("/api/admin/tuya/cameras")
    def admin_add_tuya_camera():
        payload = request.get_json(silent=True) or {}
        device_id = (payload.get("device_id") or "").strip()
        name = (payload.get("name") or "").strip()
        if not device_id:
            abort(400, description="device_id obligatorio")
        if not name:
            abort(400, description="name obligatorio")

        for existing in store.list_cameras():
            if existing.tuya_device_id == device_id:
                abort(409, description="Esta cámara Tuya ya está registrada")

        tuya_cfg = store.get_tuya_config()
        camera = Camera.create(
            name=name,
            enabled=True,
            source_type="tuya",
            tuya_device_id=device_id,
            tuya_stream_type=payload.get(
                "stream_type", tuya_cfg.default_stream_type or "rtsp"
            ),
        )
        store.add_camera(camera)
        manager.reload()
        return jsonify(camera.to_dict()), 201

    return app


def run_server(manager: MonitorManager, config: AppConfig, store: AdminStore) -> None:
    app = create_app(manager, config, store)
    logger.info(
        "Interfaz web en http://%s:%d  |  Admin: /admin",
        config.web.host,
        config.web.port,
    )
    app.run(
        host=config.web.host,
        port=config.web.port,
        threaded=True,
        use_reloader=False,
    )
