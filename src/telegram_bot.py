from __future__ import annotations

import logging
import re
import threading
import time
from typing import TYPE_CHECKING

from src.admin.models import NotificationChannels
from src.telegram_client import TelegramClient, TelegramPollingConflict

if TYPE_CHECKING:
    from src.admin.store import AdminStore
    from src.monitor_manager import MonitorManager

logger = logging.getLogger(__name__)

HELP_TEXT = """Comandos de Webcam Follow:

/foto [cámara] — Captura instantánea
/video [seg] [cámara] — Graba vídeo (segundos, default 10)
/movimiento [seg] [cámara] — Espera movimiento y graba
/ultimo [cámara] — Envía la última foto o vídeo guardado
/camaras — Lista cámaras disponibles
/estado [cámara] — Estado en vivo (movimiento, personas…)
/ayuda — Este mensaje

Ejemplos:
  /foto
  /video 15 Entrada
  /movimiento 20
"""


class TelegramBotWorker(threading.Thread):
    """Bot interactivo: foto/vídeo bajo demanda vía Telegram."""

    def __init__(self, manager: MonitorManager, store: AdminStore) -> None:
        super().__init__(name="telegram-bot", daemon=True)
        self._manager = manager
        self._store = store
        self._stop = threading.Event()
        self._offset: int | None = None
        self._polling_ready = False

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("Bot de Telegram iniciado (long polling)")
        while not self._stop.is_set():
            channels = self._store.get_notification_channels()
            if not self._bot_active(channels):
                self._polling_ready = False
                if self._stop.wait(3):
                    break
                continue

            client = TelegramClient(channels.telegram_bot_token)
            if not self._polling_ready:
                try:
                    client.ensure_polling_mode()
                    self._polling_ready = True
                except TelegramPollingConflict:
                    logger.error(
                        "Telegram 409: el mismo token ya está en uso (otra instancia "
                        "de la app, otro contenedor o webhook externo). "
                        "Detén duplicados o desactiva el bot interactivo en uno solo."
                    )
                    if self._stop.wait(15):
                        break
                    continue
                except Exception:
                    logger.exception("No se pudo preparar polling de Telegram")
                    if self._stop.wait(5):
                        break
                    continue

            try:
                updates = client.get_updates(self._offset, timeout=20)
            except TelegramPollingConflict:
                logger.warning(
                    "Telegram 409 en getUpdates; reintentando tras eliminar webhook"
                )
                self._polling_ready = False
                try:
                    client.delete_webhook()
                except Exception:
                    logger.debug("deleteWebhook ignorado tras 409", exc_info=True)
                if self._stop.wait(5):
                    break
                continue
            except Exception:
                logger.exception("Error leyendo updates de Telegram")
                if self._stop.wait(3):
                    break
                continue

            for update in updates:
                self._offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                chat = message.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                if chat_id != str(channels.telegram_chat_id).strip():
                    continue
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                threading.Thread(
                    target=self._safe_handle,
                    args=(chat_id, text, client, channels),
                    daemon=True,
                ).start()

    @staticmethod
    def _bot_active(channels: NotificationChannels) -> bool:
        return bool(
            channels.telegram_enabled
            and channels.telegram_bot_enabled
            and channels.telegram_bot_token.strip()
            and channels.telegram_chat_id.strip()
        )

    def _safe_handle(
        self,
        chat_id: str,
        text: str,
        client: TelegramClient,
        channels: NotificationChannels,
    ) -> None:
        try:
            self._handle_text(chat_id, text, client, channels)
        except Exception as exc:
            logger.exception("Error en comando Telegram: %s", text)
            try:
                client.send_message(chat_id, f"Error: {exc}")
            except Exception:
                logger.exception("No se pudo enviar error a Telegram")

    def _handle_text(
        self,
        chat_id: str,
        text: str,
        client: TelegramClient,
        channels: NotificationChannels,
    ) -> None:
        command, args = self._parse_command(text)
        if command in {"/start", "/help", "/ayuda"}:
            client.send_message(chat_id, HELP_TEXT)
            return

        if command == "/camaras":
            self._cmd_cameras(chat_id, client)
            return

        if command == "/estado":
            self._cmd_status(chat_id, client, args)
            return

        if command == "/foto":
            self._cmd_photo(chat_id, client, args)
            return

        if command == "/video":
            duration = channels.telegram_bot_video_sec
            cam_token = None
            if args:
                if re.fullmatch(r"\d+(?:\.\d+)?", args[0]):
                    duration = float(args[0])
                    cam_token = args[1] if len(args) > 1 else None
                else:
                    cam_token = args[0]
            self._cmd_video(chat_id, client, cam_token, duration)
            return

        if command == "/movimiento":
            duration = channels.telegram_bot_video_sec
            cam_token = None
            if args:
                if re.fullmatch(r"\d+(?:\.\d+)?", args[0]):
                    duration = float(args[0])
                    cam_token = args[1] if len(args) > 1 else None
                else:
                    cam_token = args[0]
            self._cmd_motion_record(
                chat_id,
                client,
                cam_token,
                duration,
                channels.telegram_motion_wait_sec,
            )
            return

        if command == "/ultimo":
            self._cmd_latest(chat_id, client, args[0] if args else None)
            return

        client.send_message(
            chat_id,
            "Comando no reconocido. Usa /ayuda para ver la lista.",
        )

    @staticmethod
    def _parse_command(text: str) -> tuple[str, list[str]]:
        raw = text.strip()
        if not raw:
            return "", []
        parts = raw.split()
        head = parts[0].lower()
        if head.startswith("/"):
            command = head.split("@", 1)[0]
            return command, parts[1:]
        aliases = {
            "foto": "/foto",
            "photo": "/foto",
            "video": "/video",
            "movimiento": "/movimiento",
            "motion": "/movimiento",
            "ultimo": "/ultimo",
            "last": "/ultimo",
            "camaras": "/camaras",
            "cameras": "/camaras",
            "estado": "/estado",
            "status": "/estado",
            "ayuda": "/ayuda",
            "help": "/help",
        }
        if head in aliases:
            return aliases[head], parts[1:]
        return head, parts[1:]

    def _resolve_camera(self, token: str | None) -> tuple[str | None, str | None]:
        camera_id = self._manager.resolve_camera_id(token)
        if not camera_id:
            return None, None
        worker = self._manager.get_worker(camera_id)
        if not worker:
            return None, None
        return camera_id, worker.camera.name

    def _cmd_cameras(self, chat_id: str, client: TelegramClient) -> None:
        lines = []
        for row in self._manager.list_cameras_summary():
            state = "activa" if row.get("active") else "—"
            conn = "online" if row.get("connected") else "offline"
            lines.append(f"• {row['name']} ({conn}) [{state}]")
        client.send_message(
            chat_id,
            "Cámaras:\n" + ("\n".join(lines) if lines else "No hay cámaras configuradas."),
        )

    def _cmd_status(self, chat_id: str, client: TelegramClient, args: list[str]) -> None:
        camera_id, name = self._resolve_camera(args[0] if args else None)
        if not camera_id:
            client.send_message(chat_id, "Cámara no encontrada.")
            return
        status = self._manager.get_status(camera_id)
        if not status:
            client.send_message(chat_id, "Sin datos de la cámara.")
            return
        motion = "SÍ" if status.motion_detected else "NO"
        client.send_message(
            chat_id,
            (
                f"Estado — {name}\n"
                f"Movimiento: {motion}\n"
                f"Personas: {status.person_count}\n"
                f"Objetos: {status.total_objects}\n"
                f"FPS: {status.fps}\n"
                f"Conectada: {'sí' if status.connected else 'no'}"
            ),
        )

    def _cmd_photo(
        self, chat_id: str, client: TelegramClient, args: list[str]
    ) -> None:
        camera_id, name = self._resolve_camera(args[0] if args else None)
        if not camera_id:
            client.send_message(chat_id, "Cámara no encontrada.")
            return
        client.send_message(chat_id, f"Capturando foto de {name}…")
        path = self._manager.capture_photo(camera_id)
        if not path or not path.is_file():
            client.send_message(chat_id, "No hay imagen disponible (¿cámara conectada?).")
            return
        client.send_photo(chat_id, path, caption=f"Foto — {name}")

    def _cmd_video(
        self,
        chat_id: str,
        client: TelegramClient,
        cam_token: str | None,
        duration_sec: float,
    ) -> None:
        camera_id, name = self._resolve_camera(cam_token)
        if not camera_id:
            client.send_message(chat_id, "Cámara no encontrada.")
            return
        duration_sec = max(3.0, min(duration_sec, 120.0))
        client.send_message(
            chat_id, f"Grabando {duration_sec:.0f}s en {name}… (espera un momento)"
        )
        path = self._manager.capture_video(camera_id, duration_sec)
        if not path or not path.is_file():
            client.send_message(chat_id, "No se pudo grabar el vídeo.")
            return
        client.send_video(
            chat_id, path, caption=f"Vídeo {duration_sec:.0f}s — {name}"
        )

    def _cmd_motion_record(
        self,
        chat_id: str,
        client: TelegramClient,
        cam_token: str | None,
        duration_sec: float,
        wait_sec: float,
    ) -> None:
        camera_id, name = self._resolve_camera(cam_token)
        if not camera_id:
            client.send_message(chat_id, "Cámara no encontrada.")
            return
        duration_sec = max(3.0, min(duration_sec, 120.0))
        wait_sec = max(5.0, min(wait_sec, 300.0))
        client.send_message(
            chat_id,
            f"Esperando movimiento en {name} (máx. {wait_sec:.0f}s)…",
        )
        if not self._manager.wait_for_motion(camera_id, wait_sec):
            client.send_message(chat_id, "No se detectó movimiento a tiempo.")
            return
        client.send_message(
            chat_id,
            f"Movimiento detectado. Grabando {duration_sec:.0f}s…",
        )
        path = self._manager.capture_video(camera_id, duration_sec)
        if not path or not path.is_file():
            client.send_message(chat_id, "No se pudo grabar el vídeo.")
            return
        client.send_video(
            chat_id,
            path,
            caption=f"Grabación por movimiento — {name}",
        )

    def _cmd_latest(
        self, chat_id: str, client: TelegramClient, cam_token: str | None
    ) -> None:
        camera_id, name = self._resolve_camera(cam_token)
        if not camera_id:
            client.send_message(chat_id, "Cámara no encontrada.")
            return
        path = self._manager.get_latest_media(camera_id)
        if not path or not path.is_file():
            client.send_message(chat_id, "No hay capturas guardadas para esa cámara.")
            return
        if path.suffix.lower() == ".mp4":
            client.send_video(chat_id, path, caption=f"Último archivo — {name}")
        else:
            client.send_photo(chat_id, path, caption=f"Último archivo — {name}")
