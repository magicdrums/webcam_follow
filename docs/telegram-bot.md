# Bot de Telegram — foto y vídeo bajo demanda

Con Telegram activado y el **bot interactivo** encendido, puedes pedir capturas desde el chat configurado en `TELEGRAM_CHAT_ID`.

## Requisitos

1. Crear un bot con [@BotFather](https://t.me/BotFather) y copiar el token.
2. Obtener tu **Chat ID** (escribe al bot y consulta `getUpdates`, o usa @userinfobot).
3. En **Admin → Canales**: activar Telegram, pegar token y chat ID, activar **Bot interactivo**.

Solo responde al chat ID configurado (seguridad básica).

**Importante:** un mismo token de bot solo puede hacer *long polling* en **una** instancia. No ejecutes la app dos veces (local + contenedor) con el mismo token. Si ves error 409, detén la otra copia o desactiva el bot interactivo en una de ellas.

## Comandos

| Comando | Descripción |
|---------|-------------|
| `/armar` | Activa YOLO, gestos y alertas |
| `/desarmar` | Solo vista en vivo (sin alertas) |
| `/seguridad` | Muestra si está armado o desarmado |
| `/foto [cámara]` | Foto instantánea del frame en vivo |
| `/video [seg] [cámara]` | Graba vídeo N segundos (default 10) |
| `/movimiento [seg] [cámara]` | Espera movimiento y graba |
| `/ultimo [cámara]` | Envía la última foto/vídeo guardada |
| `/camaras` | Lista cámaras |
| `/estado [cámara]` | Movimiento, personas, FPS |
| `/ayuda` | Ayuda |

También funcionan sin `/`: `foto`, `video 15`, `movimiento`.

**Cámara** opcional: nombre completo (puede llevar espacios), coincidencia parcial si es única, o inicio del ID. Sin argumento usa la cámara **activa y online**.

## Ejemplos

```
/foto
/video 20
/movimiento 15 Entrada
/ultimo
/estado Habitacion Victor
```

## Configuración

En **Admin → Canales → Telegram**:

- **Duración vídeo por defecto** — para `/video` sin segundos
- **Espera movimiento** — tiempo máximo para `/movimiento`

Variables de entorno opcionales: `TELEGRAM_BOT_VIDEO_SEC`, `TELEGRAM_MOTION_WAIT_SEC`.
