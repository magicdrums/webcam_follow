from __future__ import annotations

import html
import logging
import smtplib
from abc import ABC, abstractmethod
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import cv2
import requests

from src.config import AppConfig, EmailConfig, TelegramConfig, WebhookConfig, WhatsAppConfig
from src.detector import DetectionEvent

logger = logging.getLogger(__name__)

TELEGRAM_CAPTION_LIMIT = 1024


def format_objects_line(object_counts: dict[str, int]) -> str:
    if not object_counts:
        return "ninguno"
    return ", ".join(f"{label}: {n}" for label, n in sorted(object_counts.items()))


class Notifier(ABC):
    @abstractmethod
    def send(self, event: DetectionEvent, snapshot_path: Path | None) -> None:
        pass


class EmailNotifier(Notifier):
    def __init__(self, config: EmailConfig) -> None:
        self.config = config

    def send(self, event: DetectionEvent, snapshot_path: Path | None) -> None:
        if not self.config.enabled:
            return

        missing = [
            name
            for name, value in [
                ("SMTP_USER", self.config.smtp_user),
                ("SMTP_PASSWORD", self.config.smtp_password),
                ("EMAIL_FROM", self.config.email_from),
                ("EMAIL_TO", self.config.email_to),
            ]
            if not value
        ]
        if missing:
            logger.warning("Email omitido: faltan variables %s", ", ".join(missing))
            return

        subject = f"[Webcam Alert] {event.event_type.value}"
        body = (
            f"Evento: {event.event_type.value}\n"
            f"Mensaje: {event.message}\n"
            f"Objetos: {format_objects_line(event.object_counts)}\n"
            f"Personas: {event.person_count}\n"
            f"Área de movimiento: {event.motion_area}px\n"
            f"Hora: {event.timestamp.isoformat()}\n"
        )

        msg = MIMEMultipart()
        msg["From"] = self.config.email_from
        msg["To"] = self.config.email_to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if snapshot_path and snapshot_path.exists():
            with snapshot_path.open("rb") as image_file:
                image = MIMEImage(image_file.read(), name=snapshot_path.name)
                msg.attach(image)

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
            server.starttls()
            server.login(self.config.smtp_user, self.config.smtp_password)
            server.sendmail(
                self.config.email_from,
                [self.config.email_to],
                msg.as_string(),
            )
        logger.info("Notificación enviada por email")


class TelegramNotifier(Notifier):
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config

    def _build_text(self, event: DetectionEvent) -> str:
        """Texto plano (sin parse_mode) — evita errores con _ en nombres de eventos."""
        return (
            f"🚨 Webcam Alert\n"
            f"Evento: {event.event_type.value}\n"
            f"Detalle: {event.message}\n"
            f"Objetos: {format_objects_line(event.object_counts)}\n"
            f"Hora: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )[:TELEGRAM_CAPTION_LIMIT]

    def _build_html(self, event: DetectionEvent) -> str:
        return (
            f"🚨 <b>Webcam Alert</b>\n"
            f"<b>Evento:</b> {html.escape(event.event_type.value)}\n"
            f"<b>Detalle:</b> {html.escape(event.message)}\n"
            f"<b>Objetos:</b> {html.escape(format_objects_line(event.object_counts))}\n"
            f"<b>Hora:</b> {html.escape(event.timestamp.strftime('%Y-%m-%d %H:%M:%S'))}"
        )[:TELEGRAM_CAPTION_LIMIT]

    def _api_post(self, method: str, **kwargs) -> requests.Response:
        url = f"https://api.telegram.org/bot{self.config.bot_token}/{method}"
        return requests.post(url, timeout=30, **kwargs)

    def _log_api_error(self, response: requests.Response) -> None:
        logger.error(
            "Telegram API %s: %s",
            response.status_code,
            response.text[:500],
        )

    def send(self, event: DetectionEvent, snapshot_path: Path | None) -> None:
        if not self.config.enabled:
            return

        if not self.config.bot_token or not self.config.chat_id:
            logger.warning("Telegram omitido: falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
            return

        chat_id = self.config.chat_id
        plain_text = self._build_text(event)
        html_text = self._build_html(event)

        if snapshot_path and snapshot_path.exists():
            photo_bytes = snapshot_path.read_bytes()
            if not photo_bytes:
                snapshot_path = None
            else:
                for caption, parse_mode in ((html_text, "HTML"), (plain_text, None)):
                    data = {"chat_id": chat_id, "caption": caption}
                    if parse_mode:
                        data["parse_mode"] = parse_mode
                    response = self._api_post(
                        "sendPhoto",
                        data=data,
                        files={"photo": ("alert.jpg", photo_bytes, "image/jpeg")},
                    )
                    if response.ok:
                        logger.info("Notificación enviada por Telegram (foto)")
                        return
                    self._log_api_error(response)

                logger.warning("sendPhoto falló; reintentando solo texto")
                snapshot_path = None

        for text, parse_mode in ((html_text, "HTML"), (plain_text, None)):
            payload = {"chat_id": chat_id, "text": text}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            response = self._api_post("sendMessage", json=payload)
            if response.ok:
                logger.info("Notificación enviada por Telegram")
                return
            self._log_api_error(response)

        response.raise_for_status()


class WhatsAppNotifier(Notifier):
    """WhatsApp via Twilio API (requiere cuenta Twilio con sandbox o número aprobado)."""

    def __init__(self, config: WhatsAppConfig) -> None:
        self.config = config

    def send(self, event: DetectionEvent, snapshot_path: Path | None) -> None:
        if not self.config.enabled:
            return

        missing = [
            name
            for name, value in [
                ("TWILIO_ACCOUNT_SID", self.config.account_sid),
                ("TWILIO_AUTH_TOKEN", self.config.auth_token),
                ("TWILIO_WHATSAPP_FROM", self.config.from_number),
                ("WHATSAPP_TO", self.config.to_number),
            ]
            if not value
        ]
        if missing:
            logger.warning("WhatsApp omitido: faltan variables %s", ", ".join(missing))
            return

        body = (
            f"Webcam Alert\n"
            f"Evento: {event.event_type.value}\n"
            f"{event.message}\n"
            f"Objetos: {format_objects_line(event.object_counts)}\n"
            f"Hora: {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if snapshot_path and snapshot_path.exists():
            body += f"\nCaptura guardada: {snapshot_path.name}"

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{self.config.account_sid}/Messages.json"
        )
        response = requests.post(
            url,
            auth=(self.config.account_sid, self.config.auth_token),
            data={
                "From": self.config.from_number,
                "To": self.config.to_number,
                "Body": body,
            },
            timeout=30,
        )
        response.raise_for_status()
        logger.info("Notificación enviada por WhatsApp (Twilio)")


class WebhookNotifier(Notifier):
    """Webhook HTTP JSON para Home Assistant, Google Home (vía HA), Node-RED, etc."""

    def __init__(self, config: WebhookConfig) -> None:
        self.config = config

    def send(
        self,
        event: DetectionEvent,
        snapshot_path: Path | None,
        *,
        camera_id: str = "",
        camera_name: str = "",
    ) -> None:
        if not self.config.enabled:
            return
        if not self.config.url.strip():
            logger.warning("Webhook omitido: URL vacía")
            return

        payload = {
            "source": "webcam_follow",
            "event_type": event.event_type.value,
            "message": event.message,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "timestamp": event.timestamp.isoformat(),
            "person_count": event.person_count,
            "object_counts": dict(event.object_counts),
            "motion_area": event.motion_area,
            "gesture": event.gesture,
            "gesture_confidence": event.gesture_confidence,
            "snapshot_filename": snapshot_path.name if snapshot_path else None,
            "automation_target": "google_home",
        }
        headers = {"Content-Type": "application/json", "User-Agent": "webcam-follow/1.0"}
        if self.config.secret.strip():
            headers["Authorization"] = f"Bearer {self.config.secret.strip()}"

        response = requests.post(
            self.config.url.strip(),
            json=payload,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        logger.info("Webhook enviado (%s)", event.event_type.value)


class NotificationService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._email = EmailNotifier(config.email)
        self._telegram = TelegramNotifier(config.telegram)
        self._whatsapp = WhatsAppNotifier(config.whatsapp)

    def notify(
        self,
        event: DetectionEvent,
        snapshot_path: Path | None,
        *,
        use_email: bool | None = None,
        use_telegram: bool | None = None,
        use_whatsapp: bool | None = None,
    ) -> None:
        channels = [
            (self._email, use_email if use_email is not None else self.config.email.enabled),
            (self._telegram, use_telegram if use_telegram is not None else self.config.telegram.enabled),
            (self._whatsapp, use_whatsapp if use_whatsapp is not None else self.config.whatsapp.enabled),
        ]
        for notifier, enabled in channels:
            if not enabled:
                continue
            try:
                notifier.send(event, snapshot_path)
            except Exception:
                logger.exception(
                    "Error enviando notificación con %s", notifier.__class__.__name__
                )


def save_snapshot(frame, directory: Path, event: DetectionEvent) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{event.timestamp.strftime('%Y%m%d_%H%M%S')}_{event.event_type.value}.jpg"
    )
    path = directory / filename
    cv2.imwrite(str(path), frame)
    return path
