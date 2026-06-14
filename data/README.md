# Directorio `data/`

Persistencia local de Webcam Follow. Los archivos JSON se crean en el **primer arranque** a partir de `.env` (ver `AdminStore.bootstrap_from_env`).

No se versionan en git: pueden contener tokens, contraseñas y datos de tus cámaras.

## Archivos generados

| Archivo | Contenido |
|---------|-----------|
| `cameras.json` | Cámaras monitorizadas (local, RTSP, Tuya) |
| `alert_rules.json` | Reglas de alerta y canales por evento |
| `alert_history.json` | Historial de detecciones y notificaciones |
| `notification_channels.json` | SMTP, Telegram, Twilio/WhatsApp |
| `tuya_config.json` | Access ID/Key, UID y región Tuya Cloud |
| `snapshot_settings.json` | Retención de capturas (días, máximo por cámara) |
| `yolo_settings.json` | YOLOv8, MOG2 y clases COCO detectadas |

## Ubicación

Por defecto: `./data` (variable `DATA_DIR` en `.env`).

En contenedor: volumen `./data:/app/data` (ver `compose.yaml`).
