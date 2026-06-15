from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_VIDEO_LIMIT_BYTES = 49 * 1024 * 1024


class TelegramPollingConflict(RuntimeError):
    """Otra instancia hace polling o hay un webhook activo con el mismo token."""


class TelegramClient:
    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token.strip()
        self._base = f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def configured(self) -> bool:
        return bool(self.bot_token)

    def _parse_error(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("description") or payload)
        except ValueError:
            pass
        return response.text[:200] or f"HTTP {response.status_code}"

    def api_get(self, method: str, **params: Any) -> dict:
        response = requests.get(
            f"{self._base}/{method}",
            params=params,
            timeout=35,
        )
        if response.status_code == 409:
            raise TelegramPollingConflict(self._parse_error(response))
        if not response.ok:
            raise requests.HTTPError(
                f"Telegram {method} failed ({response.status_code}): "
                f"{self._parse_error(response)}",
                response=response,
            )
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Telegram API error"))
        return data

    def api_post(self, method: str, **kwargs: Any) -> requests.Response:
        return requests.post(f"{self._base}/{method}", timeout=60, **kwargs)

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        self.api_get(
            "deleteWebhook",
            drop_pending_updates=drop_pending_updates,
        )
        logger.info("Webhook de Telegram eliminado (modo long polling)")

    def ensure_polling_mode(self) -> None:
        try:
            self.delete_webhook()
        except TelegramPollingConflict:
            logger.warning(
                "Conflicto al eliminar webhook; puede haber otra instancia del bot activa"
            )
            raise

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        data = self.api_get("getUpdates", **params)
        return list(data.get("result") or [])

    def send_message(self, chat_id: str, text: str) -> None:
        payload = {"chat_id": chat_id, "text": text[:4096]}
        response = self.api_post("sendMessage", json=payload)
        if not response.ok:
            logger.error("Telegram sendMessage: %s", response.text[:500])
            response.raise_for_status()

    def send_photo(
        self, chat_id: str, path: Path, caption: str | None = None
    ) -> None:
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:TELEGRAM_CAPTION_LIMIT]
        with path.open("rb") as handle:
            response = self.api_post(
                "sendPhoto",
                data=data,
                files={"photo": (path.name, handle, "image/jpeg")},
            )
        if not response.ok:
            logger.error("Telegram sendPhoto: %s", response.text[:500])
            response.raise_for_status()

    def send_video(
        self, chat_id: str, path: Path, caption: str | None = None
    ) -> None:
        if path.stat().st_size > TELEGRAM_VIDEO_LIMIT_BYTES:
            raise ValueError(
                f"El vídeo supera el límite de Telegram ({path.stat().st_size} bytes)"
            )
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:TELEGRAM_CAPTION_LIMIT]
        with path.open("rb") as handle:
            response = self.api_post(
                "sendVideo",
                data=data,
                files={"video": (path.name, handle, "video/mp4")},
            )
        if not response.ok:
            logger.error("Telegram sendVideo: %s", response.text[:500])
            response.raise_for_status()
