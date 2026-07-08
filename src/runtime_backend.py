from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from src.admin.snapshots import SnapshotService
    from src.config import AppConfig
    from src.monitor_manager import MonitorManager
    from src.monitor_types import LiveStatus

logger = logging.getLogger(__name__)


class MonitorBackend:
    """Abstracción del motor de vigilancia (local o remoto)."""

    def get_active_camera_id(self) -> str | None:
        raise NotImplementedError

    def get_jpeg_frame(self, camera_id: str | None = None) -> bytes | None:
        raise NotImplementedError

    def get_status(self, camera_id: str | None = None) -> LiveStatus | None:
        raise NotImplementedError

    def list_cameras_summary(self) -> list[dict]:
        raise NotImplementedError

    def set_active_camera(self, camera_id: str) -> bool:
        raise NotImplementedError

    def get_security_state(self) -> dict:
        raise NotImplementedError

    def set_surveillance_armed(self, armed: bool, *, source: str = "web") -> dict:
        raise NotImplementedError

    def get_heatmap_jpeg(self, camera_id: str | None = None) -> bytes | None:
        raise NotImplementedError

    def reset_motion_analytics(self, camera_id: str | None = None) -> bool:
        raise NotImplementedError

    def get_alerts(self, limit: int = 50, camera_id: str | None = None) -> list[Any]:
        raise NotImplementedError

    def reload(self) -> None:
        raise NotImplementedError

    def run_snapshot_cleanup(self) -> int:
        raise NotImplementedError

    @property
    def snapshot_service(self) -> SnapshotService:
        raise NotImplementedError


class InProcessBackend(MonitorBackend):
    def __init__(self, manager: MonitorManager) -> None:
        self._manager = manager

    def get_active_camera_id(self) -> str | None:
        return self._manager.get_active_camera_id()

    def get_jpeg_frame(self, camera_id: str | None = None) -> bytes | None:
        return self._manager.get_jpeg_frame(camera_id)

    def get_status(self, camera_id: str | None = None) -> LiveStatus | None:
        return self._manager.get_status(camera_id)

    def list_cameras_summary(self) -> list[dict]:
        return self._manager.list_cameras_summary()

    def set_active_camera(self, camera_id: str) -> bool:
        return self._manager.set_active_camera(camera_id)

    def get_security_state(self) -> dict:
        return self._manager.get_security_state()

    def set_surveillance_armed(self, armed: bool, *, source: str = "web") -> dict:
        return self._manager.set_surveillance_armed(armed, source=source)

    def get_heatmap_jpeg(self, camera_id: str | None = None) -> bytes | None:
        return self._manager.get_heatmap_jpeg(camera_id)

    def reset_motion_analytics(self, camera_id: str | None = None) -> bool:
        return self._manager.reset_motion_analytics(camera_id)

    def get_alerts(self, limit: int = 50, camera_id: str | None = None) -> list[Any]:
        return self._manager.get_alerts(limit, camera_id)

    def reload(self) -> None:
        self._manager.reload()

    def run_snapshot_cleanup(self) -> int:
        return self._manager.run_snapshot_cleanup()

    @property
    def snapshot_service(self) -> SnapshotService:
        return self._manager.snapshot_service


class RemoteWorkerBackend(MonitorBackend):
    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        snapshot_service: SnapshotService,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._snapshot_service = snapshot_service
        self._session = requests.Session()
        if token:
            self._session.headers["X-Worker-Token"] = token

    @property
    def snapshot_service(self) -> SnapshotService:
        return self._snapshot_service

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> requests.Response:
        url = f"{self._base_url}{path}"
        response = self._session.request(
            method,
            url,
            params=params,
            json=json,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response

    def get_active_camera_id(self) -> str | None:
        cameras = self.list_cameras_summary()
        for row in cameras:
            if row.get("active"):
                return row["id"]
        return cameras[0]["id"] if cameras else None

    def get_jpeg_frame(self, camera_id: str | None = None) -> bytes | None:
        params = {}
        if camera_id:
            params["camera_id"] = camera_id
        try:
            response = self._request("GET", "/api/frame", params=params)
            return response.content
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    def get_status(self, camera_id: str | None = None):
        from src.monitor_types import LiveStatus

        params = {}
        if camera_id:
            params["camera_id"] = camera_id
        data = self._request("GET", "/api/status", params=params).json()
        if not data.get("connected") and len(data) <= 1:
            return None
        return LiveStatus(**data)

    def list_cameras_summary(self) -> list[dict]:
        return self._request("GET", "/api/cameras").json()

    def set_active_camera(self, camera_id: str) -> bool:
        try:
            self._request(
                "POST",
                "/api/cameras/active",
                json={"camera_id": camera_id},
            )
            return True
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 400:
                return False
            raise

    def get_security_state(self) -> dict:
        return self._request("GET", "/api/security").json()

    def set_surveillance_armed(self, armed: bool, *, source: str = "web") -> dict:
        return self._request(
            "PUT",
            "/api/security",
            json={"armed": armed, "source": source},
        ).json()

    def get_heatmap_jpeg(self, camera_id: str | None = None) -> bytes | None:
        params = {}
        if camera_id:
            params["camera_id"] = camera_id
        try:
            return self._request("GET", "/api/motion/heatmap", params=params).content
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    def reset_motion_analytics(self, camera_id: str | None = None) -> bool:
        params = {}
        if camera_id:
            params["camera_id"] = camera_id
        try:
            self._request("POST", "/api/motion/heatmap/reset", params=params)
            return True
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return False
            raise

    def get_alerts(self, limit: int = 50, camera_id: str | None = None) -> list[Any]:
        from src.monitor_types import AlertRecord

        params: dict[str, Any] = {"limit": limit}
        if camera_id:
            params["camera_id"] = camera_id
        payload = self._request("GET", "/api/alerts", params=params).json()
        return [AlertRecord(**item) for item in payload]

    def reload(self) -> None:
        self._request("POST", "/internal/reload")

    def run_snapshot_cleanup(self) -> int:
        data = self._request("POST", "/internal/snapshots/cleanup").json()
        return int(data.get("deleted", 0))


def create_backend(
    config: AppConfig,
    manager: MonitorManager | None = None,
) -> MonitorBackend:
    import os

    from src.admin.snapshots import SnapshotService

    mode = os.getenv("SERVICE_MODE", "monolith").strip().lower()
    snapshot_service = SnapshotService(config.detection.snapshot_dir)

    if mode == "web":
        worker_url = os.getenv("WORKER_URL", "http://worker:8090").strip()
        token = os.getenv("WORKER_TOKEN", "").strip()
        logger.info("Modo web: conectando al worker en %s", worker_url)
        return RemoteWorkerBackend(
            worker_url,
            token=token,
            snapshot_service=snapshot_service,
        )

    if manager is None:
        raise RuntimeError("MonitorManager requerido en modo monolith/worker")
    return InProcessBackend(manager)
