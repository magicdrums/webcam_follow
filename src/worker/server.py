from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request

from src.admin.store import AdminStore
from src.config import AppConfig
from src.monitor_manager import MonitorManager

logger = logging.getLogger(__name__)


def _check_worker_token() -> None:
    expected = os.getenv("WORKER_TOKEN", "").strip()
    if not expected:
        return
    provided = request.headers.get("X-Worker-Token", "").strip()
    if provided != expected:
        abort(403, description="Token de worker inválido")


def create_worker_app(
    manager: MonitorManager, config: AppConfig, store: AdminStore
) -> Flask:
    app = Flask(__name__)

    @app.before_request
    def _auth_worker():
        if request.endpoint == "health":
            return
        _check_worker_token()

    def _camera_id_from_request() -> str | None:
        return request.args.get("camera_id") or manager.get_active_camera_id()

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "service": "worker"})

    @app.get("/video_feed")
    def video_feed():
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
        return Response(frame, mimetype="image/jpeg", headers=headers)

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

    @app.get("/api/security")
    def api_security():
        return jsonify(manager.get_security_state())

    @app.put("/api/security")
    def api_set_security():
        payload = request.get_json(silent=True) or {}
        if "armed" not in payload:
            abort(400, description="Campo armed obligatorio (true/false)")
        source = str(payload.get("source", "web")).strip() or "web"
        return jsonify(
            manager.set_surveillance_armed(bool(payload["armed"]), source=source)
        )

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
        limit = int(request.args.get("limit", config.web.alerts_limit))
        alerts = manager.get_alerts(limit, camera_id)
        return jsonify([asdict(alert) for alert in alerts])

    @app.post("/internal/reload")
    def internal_reload():
        manager.reload()
        logger.info("Worker recargado tras cambio de configuración")
        return jsonify({"ok": True})

    @app.post("/internal/snapshots/cleanup")
    def internal_snapshot_cleanup():
        deleted = manager.run_snapshot_cleanup()
        return jsonify({"ok": True, "deleted": deleted})

    return app


def run_worker_server(
    manager: MonitorManager, config: AppConfig, store: AdminStore
) -> None:
    host = os.getenv("WORKER_HOST", "0.0.0.0")
    port = int(os.getenv("WORKER_PORT", "8090"))
    app = create_worker_app(manager, config, store)
    logger.info("Worker API en http://%s:%d", host, port)
    app.run(host=host, port=port, threaded=True, use_reloader=False)
