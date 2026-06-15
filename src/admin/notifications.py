from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from src.admin.channels import (
    channels_to_email_config,
    channels_to_telegram_config,
    channels_to_webhook_config,
    channels_to_whatsapp_config,
)
from src.admin.store import AdminStore
from src.detector import DetectionEvent, EventType
from src.notifier import EmailNotifier, TelegramNotifier, WebhookNotifier, WhatsAppNotifier

logger = logging.getLogger(__name__)


class StoreNotificationService:
    """Envía notificaciones usando la configuración persistida en AdminStore."""

    def __init__(self, store: AdminStore) -> None:
        self._store = store

    def notify(
        self,
        event: DetectionEvent,
        snapshot_path: Path | None,
        *,
        camera_id: str = "",
        camera_name: str = "",
        use_email: bool = False,
        use_telegram: bool = False,
        use_whatsapp: bool = False,
        use_webhook: bool = False,
    ) -> None:
        channels = self._store.get_notification_channels()
        email = EmailNotifier(channels_to_email_config(channels))
        telegram = TelegramNotifier(channels_to_telegram_config(channels))
        whatsapp = WhatsAppNotifier(channels_to_whatsapp_config(channels))
        webhook = WebhookNotifier(channels_to_webhook_config(channels))

        for notifier, enabled, extra in [
            (email, use_email and channels.email_enabled, {}),
            (telegram, use_telegram and channels.telegram_enabled, {}),
            (whatsapp, use_whatsapp and channels.whatsapp_enabled, {}),
            (
                webhook,
                use_webhook and channels.webhook_enabled,
                {"camera_id": camera_id, "camera_name": camera_name},
            ),
        ]:
            if not enabled:
                continue
            try:
                if extra:
                    notifier.send(event, snapshot_path, **extra)
                else:
                    notifier.send(event, snapshot_path)
            except Exception:
                logger.exception(
                    "Error enviando notificación con %s", notifier.__class__.__name__
                )

    def test_channel(self, channel: str) -> None:
        channels = self._store.get_notification_channels()
        event = DetectionEvent(
            event_type=EventType.HAND_GESTURE,
            message="Gesto de prueba: pulgar arriba (webcam follow)",
            object_counts={"person": 1},
            motion_area=1000,
            timestamp=datetime.now(timezone.utc),
            gesture="pulgar_arriba",
            gesture_confidence=0.99,
        )

        if channel == "email":
            if not channels.email_enabled:
                raise ValueError("Email no está activado")
            EmailNotifier(channels_to_email_config(channels)).send(event, None)
        elif channel == "telegram":
            if not channels.telegram_enabled:
                raise ValueError("Telegram no está activado")
            TelegramNotifier(channels_to_telegram_config(channels)).send(event, None)
        elif channel == "whatsapp":
            if not channels.whatsapp_enabled:
                raise ValueError("WhatsApp no está activado")
            WhatsAppNotifier(channels_to_whatsapp_config(channels)).send(event, None)
        elif channel == "webhook":
            if not channels.webhook_enabled:
                raise ValueError("Webhook no está activado")
            WebhookNotifier(channels_to_webhook_config(channels)).send(
                event,
                None,
                camera_id="test",
                camera_name="Prueba",
            )
        else:
            raise ValueError(f"Canal desconocido: {channel}")
