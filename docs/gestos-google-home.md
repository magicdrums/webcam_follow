# Gestos de mano y Google Home

Webcam Follow puede detectar gestos de mano con **MediaPipe Hands** y enviar un **webhook JSON** a Home Assistant (u otro automatizador) para controlar **Google Home**, luces, escenas, etc.

## Gestos soportados

| ID | Descripción | Uso típico en automatización |
|----|-------------|------------------------------|
| `mano_abierta` | Palma abierta | Encender luces / cancelar alarma |
| `punio` | Puño cerrado | Apagar luces |
| `pulgar_arriba` | Pulgar hacia arriba | Confirmar / subir temperatura |
| `pulgar_abajo` | Pulgar hacia abajo | Rechazar / bajar temperatura |
| `paz` | Índice + medio (victoria) | Escena «relax» |
| `saludo` | Mano moviéndose lateralmente | Anuncio TTS en Google Home |

## Configuración en Webcam Follow

1. **Admin → YOLO / Detección → Gestos de mano**
   - Activa la detección.
   - Elige qué gestos reconocer y el cooldown (evita repetir el mismo gesto cada frame).

2. **Admin → Canales → Webhook**
   - Activa el webhook.
   - Pega la URL de Home Assistant (ver abajo).

3. **Admin → Reglas**
   - Evento: **Gesto de mano**.
   - Opcional: filtra gestos concretos (p. ej. solo `pulgar_arriba`).
   - Canal: **Webhook (Google Home / HA)**.
   - Cooldown recomendado: 3–10 s.

## Home Assistant + Google Home

### 1. Crear webhook en HA

`configuration.yaml` (o automatización con trigger webhook):

```yaml
automation:
  - alias: "Webcam Follow - pulgar arriba"
    triggers:
      - trigger: webhook
        webhook_id: webcam_follow_gestos
        allowed_methods:
          - POST
        local_only: false
    conditions:
      - condition: template
        value_template: "{{ trigger.json.gesture == 'pulgar_arriba' }}"
    actions:
      - action: google_assistant_sdk.send_text_command
        data:
          command: "encender luces del salón"
```

La URL del webhook será:

```text
https://TU_HA:8123/api/webhook/webcam_follow_gestos
```

(Puedes añadir autenticación Bearer en Webcam Follow si lo configuras en el proxy inverso.)

### 2. Payload JSON enviado

```json
{
  "source": "webcam_follow",
  "event_type": "gesto_mano",
  "message": "Gesto detectado: Pulgar arriba (Right, 90%)",
  "camera_id": "...",
  "camera_name": "Salón",
  "timestamp": "2026-06-14T12:00:00+00:00",
  "person_count": 1,
  "object_counts": {"person": 1},
  "motion_area": 8000,
  "gesture": "pulgar_arriba",
  "gesture_confidence": 0.9,
  "snapshot_filename": "20260614_120000_gesto_mano.jpg",
  "automation_target": "google_home"
}
```

Usa `trigger.json.gesture` en plantillas de Home Assistant para ramificar acciones.

### 3. Anuncio por voz en Google Home

```yaml
actions:
  - action: tts.google_translate_say
    target:
      entity_id: media_player.salon
    data:
      message: "Gesto detectado en la cámara del salón"
```

## Consejos

- Coloca la cámara de forma que las manos se vean claras (frente a la lente, buena luz).
- Activa **Solo analizar gestos cuando hay movimiento** para reducir CPU.
- Google Home no expone webhooks directos; **Home Assistant** (o Node-RED / IFTTT) es el puente recomendado.

## Variables de entorno (opcional)

```env
HAND_GESTURE_ENABLED=true
HAND_GESTURE_MIN_CONFIDENCE=0.75
HAND_GESTURE_COOLDOWN_SEC=2
WEBHOOK_ENABLED=true
WEBHOOK_URL=https://homeassistant.local:8123/api/webhook/webcam_follow_gestos
```
