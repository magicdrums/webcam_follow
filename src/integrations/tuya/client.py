from __future__ import annotations

import logging
from typing import Any

from src.admin.models import TuyaConfig

logger = logging.getLogger(__name__)

REGION_ENDPOINTS = {
    "cn": "https://openapi.tuyacn.com",
    "us": "https://openapi.tuyaus.com",
    "eu": "https://openapi.tuyaeu.com",
    "in": "https://openapi.tuyain.com",
}

IPC_CATEGORIES = {"sp", "ipc", "dj", "camera"}


class TuyaClientError(RuntimeError):
    pass


class TuyaClient:
    def __init__(self, config: TuyaConfig) -> None:
        self.config = config
        self._api = None

    @property
    def is_configured(self) -> bool:
        return bool(
            self.config.enabled
            and self.config.access_id
            and self.config.access_key
            and self.config.uid
        )

    def _endpoint(self) -> str:
        if self.config.api_endpoint.strip():
            return self.config.api_endpoint.rstrip("/")
        region = self.config.api_region.lower()
        if region not in REGION_ENDPOINTS:
            raise TuyaClientError(f"Región Tuya no válida: {region}")
        return REGION_ENDPOINTS[region]

    def _connect(self):
        if self._api is not None:
            return
        try:
            from tuya_connector import TuyaOpenAPI
        except ImportError as exc:
            raise TuyaClientError(
                "Instala tuya-connector-python: pip install tuya-connector-python"
            ) from exc

        api = TuyaOpenAPI(self._endpoint(), self.config.access_id, self.config.access_key)
        api.connect()
        self._api = api

    def _request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        self._connect()
        assert self._api is not None
        if method == "GET":
            response = self._api.get(path, body or {})
        elif method == "POST":
            response = self._api.post(path, body or {})
        else:
            raise TuyaClientError(f"Método no soportado: {method}")

        if not isinstance(response, dict):
            raise TuyaClientError(f"Respuesta Tuya inesperada: {response}")

        if not response.get("success", False):
            code = response.get("code", "?")
            msg = response.get("msg", response)
            raise TuyaClientError(f"Tuya API error {code}: {msg}")
        return response

    def test_connection(self) -> dict[str, Any]:
        devices = self.list_devices()
        return {"ok": True, "device_count": len(devices)}

    def list_devices(self) -> list[dict[str, Any]]:
        if not self.config.uid:
            raise TuyaClientError("UID de Tuya no configurado")

        response = self._request("GET", f"/v1.0/users/{self.config.uid}/devices")
        devices = response.get("result") or []
        if not isinstance(devices, list):
            return []

        ipc_devices = []
        for device in devices:
            category = str(device.get("category", "")).lower()
            product = str(device.get("product_name", "")).lower()
            name = device.get("name") or device.get("id", "Cámara")
            is_ipc = (
                category in IPC_CATEGORIES
                or "camera" in product
                or "ipc" in product
                or "cam" in product
            )
            ipc_devices.append(
                {
                    "id": device.get("id", ""),
                    "name": name,
                    "category": category,
                    "product_name": device.get("product_name", ""),
                    "online": bool(device.get("online", False)),
                    "is_ipc": is_ipc,
                }
            )
        ipc_devices.sort(key=lambda item: (not item["is_ipc"], not item["online"], item["name"]))
        return ipc_devices

    def allocate_stream(self, device_id: str, stream_type: str = "rtsp") -> str:
        if not device_id:
            raise TuyaClientError("device_id de Tuya vacío")

        body = {"type": stream_type}
        attempts = [
            f"/v1.0/devices/{device_id}/stream/actions/allocate",
            f"/v1.0/users/{self.config.uid}/devices/{device_id}/stream/actions/allocate",
        ]

        last_error: Exception | None = None
        for path in attempts:
            try:
                response = self._request("POST", path, body)
                result = response.get("result") or {}
                url = result.get("url") if isinstance(result, dict) else None
                if url:
                    logger.info("Stream Tuya obtenido (%s) para %s", stream_type, device_id)
                    return str(url)
            except TuyaClientError as exc:
                last_error = exc
                logger.debug("allocate_stream falló en %s: %s", path, exc)

        raise TuyaClientError(
            f"No se pudo obtener stream para {device_id}: {last_error}"
        )
