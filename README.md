# Webcam Follow

Aplicación de vigilancia que detecta **movimiento**, **personas**, **objetos** y **cambios en la escena**, enviando alertas por **correo**, **Telegram** y **WhatsApp**.

Captura desde **webcam local**, **stream de red** (RTSP de v4l2rtspserver, HTTP/MJPEG) o **cámaras Tuya** (Smart Life vía Cloud API). Funciona en **PC x86_64** y **Raspberry Pi**.

## Cómo funciona la detección

| Tarea | Motor | Notas |
|-------|--------|-------|
| **Movimiento** | OpenCV MOG2 | Ligero, ideal para RPi |
| **Personas y objetos** | YOLOv8 nano | Clases COCO configurables |
| **Cambios de escena** | Hash de imagen | Complementa MOG2 |

En Raspberry Pi, YOLOv8 solo se ejecuta cuando MOG2 detecta movimiento (`YOLO_ON_MOTION_ONLY=true` por defecto).

## Fuente de video

### Stream RTSP (v4l2rtspserver)

Si ya tienes un transmisor RTSP funcionando, apunta la app al stream:

```env
VIDEO_SOURCE=stream
STREAM_URL=rtsp://192.168.1.100:8554/unicast
RTSP_TRANSPORT=tcp
```

También basta con definir `STREAM_URL` sin `VIDEO_SOURCE`; se detecta automáticamente.

La app reconecta sola si el stream se cae (`STREAM_RECONNECT_SEC=5`).

Si ves en logs `Received packet without a start chunk`, suele ser H.264 mal sincronizado (v4l2rtspserver, cámara barata o reconexiones frecuentes). La app ahora espera un keyframe válido al conectar y reintenta con TCP. Si persiste:

- Confirma **RTSP_TRANSPORT=tcp** (Admin → cámara o `.env`)
- Prueba el stream: `ffplay -rtsp_transport tcp rtsp://IP:8554/unicast`
- Usa **go2rtc** como proxy intermedio (estabiliza muchos streams Tuya/v4l2)
- Alternativa: URL **HTTP/MJPEG** de go2rtc (`http://IP:1984/api/stream.mjpeg?src=...`)

**Dependencia de sistema para RTSP:**

```bash
sudo apt install ffmpeg   # Debian / Ubuntu / RPi OS
```

### Webcam local

```env
VIDEO_SOURCE=local
CAMERA_INDEX=0
```

### Cámaras Tuya (Smart Life)

> **Aviso (2025–2026):** Tuya limita el acceso a vídeo en la Developer Platform. Para obtener stream hace falta suscribir el servicio **IoT Video Live Stream** y vincular la cuenta de la app; muchos usuarios ya no ven «Link Tuya App Account» o el stream deja de funcionar al caducar la prueba gratuita. La integración Cloud de esta app puede no ser viable en cuentas personales.

Conecta cámaras vinculadas a **Smart Life** / **Tuya Smart** mediante la **Tuya Cloud API** (si tu proyecto aún tiene acceso). No hace falta abrir puertos en el router: la app obtiene una URL RTSP/HLS temporal desde la nube.

1. Crea un proyecto en [Tuya Developer Platform](https://platform.tuya.com/).
2. En **Cloud → Service API → Authorize**, activa **IoT Video Live Stream** (prueba gratuita, se renueva manualmente cada ~6 meses).
3. En **Devices → Link Tuya App Account**, escanea el QR con Smart Life o Tuya Smart (misma región/datacenter que el proyecto).
4. Copia **Access ID**, **Access Key** y el **UID** del usuario vinculado.
5. En **http://localhost:8080/admin → Tuya IoT**, guarda las credenciales y pulsa **Buscar cámaras**.

También puedes precargar credenciales en `.env`:

```env
TUYA_ACCESS_ID=tu_access_id
TUYA_ACCESS_KEY=tu_access_key
TUYA_UID=ay156402688xxxxvoY5W
TUYA_API_REGION=eu
```

La configuración se guarda en `data/tuya_config.json`. Las URLs de stream expiran; la app las renueva al reconectar.

**Dependencia Python:** `tuya-connector-python` (incluida en `requirements-base.txt`).

#### Alternativas si Tuya Cloud no funciona

| Opción | Cuándo usarla | Cómo integrarla con Webcam Follow |
|--------|----------------|-----------------------------------|
| **[go2rtc](https://github.com/AlexxIT/go2rtc)** + Tuya Smart API | Cuenta **Tuya Smart** (no Smart Life); email/contraseña en go2rtc | go2rtc expone RTSP; añade cámara tipo **Stream** con esa URL |

**Guía completa paso a paso:** [docs/guia-tuya-go2rtc.md](docs/guia-tuya-go2rtc.md)
| **RTSP local (hack SD)** | Cámaras con firmware Anyka/RTS3903N u otros con proyectos tipo [lsc-tuya-toolkit](https://github.com/tasarren/lsc-tuya-toolkit) | `VIDEO_SOURCE=stream` → `rtsp://IP:554/...` |
| **ONVIF** | Tras habilitar ONVIF en la cámara (algunos hacks) | Stream ONVIF/RTSP como cámara **Stream** |
| **Seguir con Smart Life** | Sin migrar dispositivos | No hay API de vídeo fiable hoy; Tuya Smart API de go2rtc **no** admite cuentas Smart Life |

Ejemplo con go2rtc (cuenta Tuya Smart, cámaras reemparejadas en esa app):

```yaml
# go2rtc.yaml
streams:
  cam_tuya:
    - tuya://protect-eu.ismartlife.me?device_id=XXX&email=tu@email.com&password=XXX
```

Luego en Webcam Follow: **Admin → Cámaras → Stream RTSP/HTTP** → `rtsp://localhost:8554/cam_tuya` (o la URL que muestre go2rtc).

## Requisitos

- Python 3.10+
- ffmpeg (solo para streams RTSP/HTTP)
- **PC x86**: 2 GB RAM, GPU NVIDIA opcional
- **Raspberry Pi**: Pi 4/5 recomendado (2 GB+ RAM)

## Despliegue con Podman (x86 y ARM)

La forma recomendada para desplegar en **cualquier arquitectura** (PC x86_64, Raspberry Pi arm64, servidores ARM) es el contenedor. Por defecto el stack se divide en **dos servicios**:

| Servicio | Imagen | Rol |
|----------|--------|-----|
| **worker** | `Containerfile` | Cámaras, YOLO, MediaPipe, Telegram, alertas, snapshots |
| **web** | `Containerfile.web` | Panel `:8080`, administración `/admin` (imagen ligera, sin torch) |

Así puedes **reconstruir solo la web** tras cambios de UI o API de administración, sin volver a descargar YOLO ni PyTorch. El worker expone una API interna en el puerto **8090** (`WORKER_URL`); **web** y **worker** comparten la red bridge `webcam-follow` (DNS interno: el hostname `worker` resuelve solo dentro de esa red).

Para el despliegue clásico en un solo contenedor, usa el perfil `monolith`:

```bash
podman compose --profile monolith up -d --build
```

### Arranque rápido

```bash
cp .env.container.example .env
# Edita STREAM_URL y notificaciones en .env

chmod +x scripts/build-image-local.sh
./scripts/build-image-local.sh

# Fedora / rootless: activa el socket que usa `podman compose` (docker-compose plugin)
systemctl --user enable --now podman.socket
export DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock

podman compose up -d --build
podman compose logs -f
```

Reconstruir solo un servicio:

```bash
podman compose up -d --build web      # panel y admin
podman compose up -d --build worker     # detección y notificaciones
```

Variables útiles (ver `.env.example`):

- `SERVICE_MODE`: `monolith` | `web` | `worker`
- `WORKER_URL`: URL del worker desde el contenedor web (p. ej. `http://worker:8090`)
- `WORKER_TOKEN`: token opcional compartido (`X-Worker-Token`) entre web y worker

Abre **http://localhost:8080** para ver el panel web.  
**Administración:** http://localhost:8080/admin

#### Si `podman compose` falla con `podman.sock: no such file`

`podman compose` delega en el plugin **docker-compose**, que habla con Podman vía socket Unix. En Fedora rootless hay que activarlo una vez:

```bash
systemctl --user enable --now podman.socket
export DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock
podman compose up -d --build
```

Comprueba que el socket existe:

```bash
ls -l /run/user/$(id -u)/podman/podman.sock
systemctl --user status podman.socket
```

Alternativa sin docker-compose: `podman-compose up -d --build` (paquete `podman-compose`).

#### Si falla `Permission denied` en `/app/data`

Con **worker + web** en Fedora/Podman suele ser una combinación de:

1. **SELinux y `:Z` en volúmenes** — `:Z` marca los archivos como *privados* de un solo contenedor. Si `web` y `worker` montan `./data:Z`, uno puede bloquear al otro. En `compose.yaml` se usa **`:z`** (compartido entre contenedores del stack).
2. **Propietario `nobody`** — tras contenedores antiguos, los JSON quedan con UID 65534.

**No hace falta reconstruir imágenes**; corrige en el host y recrea contenedores:

```bash
chmod +x scripts/fix-volume-permissions.sh
./scripts/fix-volume-permissions.sh
podman compose down
podman compose up -d
```

O manualmente:

```bash
chown -R $(id -u):$(id -g) data snapshots
chmod -R u+rwX data snapshots
chcon -Rt container_file_t data snapshots   # solo si SELinux enforcing
podman compose down && podman compose up -d
```

Comprueba:

```bash
ls -la data/cameras.json
# Debe mostrar tu usuario, no nobody
```

#### Si falla `address already in use` en el puerto 8080

Queda un contenedor antiguo (`webcam-follow` monolito) ocupando el puerto. Deténlo antes del compose nuevo:

```bash
podman stop webcam-follow 2>/dev/null; podman rm webcam-follow 2>/dev/null
podman compose up -d
```

### Interfaz web

Con `WEB_ENABLED=true` (activo por defecto en contenedor) tienes un panel en el puerto **8080**:

| Sección | Contenido |
|---------|-----------|
| Vista en vivo | Stream MJPEG con detecciones dibujadas |
| Selector de cámara | Cambia entre cámaras monitorizadas |
| Estado | Movimiento, personas, objetos, FPS |
| Alertas | Historial de eventos recientes |
| Capturas | Galería de snapshots guardados |
| **/admin** | Gestor de cámaras, reglas e historial |

#### Administrador de cámaras (`/admin` → Cámaras)

- Añadir, editar y eliminar cámaras (webcam local, stream RTSP o **Tuya Cloud**)
- Activar/desactivar monitoreo por cámara
- Varias cámaras en paralelo, cada una en su propio hilo
- Configuración persistida en `data/cameras.json`

#### Tuya IoT (`/admin` → Tuya IoT)

- Credenciales Cloud (Access ID, Key, UID, región) — **solo si tu proyecto Tuya aún permite vídeo**
- Descubrir dispositivos e importar cámaras
- Persistencia en `data/tuya_config.json`
- Si el Developer Platform no vincula cámaras, usa **go2rtc** o RTSP local (ver README)

#### Administrador de alertas (`/admin` → Reglas / Historial)

- **Reglas:** qué eventos notificar, a qué cámaras, por email/Telegram/WhatsApp, cooldown
- **Historial:** todos los eventos registrados, con captura y estado de notificación
- Persistencia en `data/alert_rules.json` y `data/alert_history.json`

#### Canales de notificación (`/admin` → Canales)

- Configura **Email (SMTP)**, **Telegram**, **WhatsApp (Twilio)** y **Webhook** desde la web
- **Armado / desarmado**: botón en la web o `/armar` / `/desarmar` en Telegram — pausa YOLO y alertas sin apagar la cámara
- **Bot de Telegram interactivo**: `/foto`, `/video`, `/movimiento` — ver [docs/telegram-bot.md](docs/telegram-bot.md)
- Activa/desactiva cada canal sin editar `.env`
- El webhook envía JSON a Home Assistant para integrar **Google Home**
- Botón **Probar** por canal para verificar credenciales
- Persistencia en `data/notification_channels.json`
- Las reglas de alerta referencian estos canales (checkbox email/telegram/whatsapp)

#### Capturas (`/admin` → Capturas)

- Retención por **días** y **máximo por cámara** (0 = sin límite)
- Limpieza automática en segundo plano e **Ejecutar limpieza ahora**
- Explorador de archivos con miniatura, filtro por cámara y eliminación individual
- Persistencia en `data/snapshot_settings.json`

#### YOLO / Detección (`/admin` → YOLO / Detección)

- Confianza, intervalo, modelo (nano/small/medium), CPU/CUDA
- MOG2: umbral y área mínima de movimiento
- Clases COCO: presets o selección personalizada
- **YOLO solo con movimiento** y guardado de capturas
- Cambios en caliente sin reiniciar (`data/yolo_settings.json`)

#### Gestos de mano y Google Home

- Detección de gestos con **MediaPipe Hands** (mano abierta, puño, pulgar arriba/abajo, paz, saludo)
- **Webhook JSON** hacia Home Assistant para automatizar **Google Home**, luces y escenas
- Configuración: **YOLO / Detección → Gestos de mano**, **Canales → Webhook**, **Reglas → Gesto de mano**
- Guía completa: [docs/gestos-google-home.md](docs/gestos-google-home.md)

#### Mapa de calor y predicción

- Acumula movimiento MOG2 en una cuadrícula 48×27 (rojo = más actividad)
- Overlay en el vídeo en vivo y miniatura en el panel lateral
- **Predicción**: flecha amarilla con extrapolación ~0.8 s del centro de movimiento
- Configurable en **YOLO / Detección** (opacidad, decaimiento, activar/desactivar)
- Botón **Reiniciar** en el panel en vivo

Al primer arranque se importa la cámara, regla y canales desde tu `.env`.

```env
WEB_ENABLED=true
WEB_HOST=0.0.0.0
WEB_PORT=8080
```

En instalación nativa, activa `WEB_ENABLED=true` en `.env` y abre `http://localhost:8080`.

### Build multi-arquitectura (amd64 + arm64)

Para publicar una imagen que funcione en PC y RPi con el mismo tag:

```bash
chmod +x scripts/build-image.sh
./scripts/build-image.sh
```

En una RPi ejecuta el mismo comando: Podman construye solo `linux/arm64`. En un PC, `linux/amd64`. El script `build-image.sh` genera un **manifest** con ambas.

Publicar en un registro:

```bash
REGISTRY=ghcr.io/tu-usuario PUSH=true ./scripts/build-image.sh
podman push --all-tags ghcr.io/tu-usuario/webcam-follow
```

En otro host (cualquier arquitectura):

```bash
podman pull ghcr.io/tu-usuario/webcam-follow:latest
podman run -d --name webcam-follow \
  --env-file .env \
  -p 8080:8080 \
  -v ./snapshots:/app/snapshots \
  --restart unless-stopped \
  ghcr.io/tu-usuario/webcam-follow:latest
```

### Webcam USB dentro del contenedor

```bash
podman run --rm \
  --device /dev/video0:/dev/video0 \
  --env-file .env \
  -e VIDEO_SOURCE=local \
  -v ./snapshots:/app/snapshots \
  localhost/webcam-follow:latest
```

### Notas del contenedor

| Aspecto | Comportamiento |
|---------|----------------|
| Arquitectura | Misma imagen en `amd64` y `arm64` |
| Vista previa | Desactivada (`SHOW_PREVIEW=false`) |
| YOLO | CPU (`YOLO_DEVICE=cpu`) |
| Perfil | `PLATFORM=auto` detecta ARM → perfil optimizado |
| Capturas | Volumen `./snapshots` |
| RTSP | ffmpeg incluido; `RTSP_TRANSPORT=tcp` recomendado |
| Interfaz web | Puerto `8080`, panel en `/` |

## Instalación nativa (sin contenedor)

```bash
cd webcam_follow
chmod +x scripts/install.sh
./scripts/install.sh
cp .env.example .env
# Edita STREAM_URL con la IP de tu v4l2rtspserver
python main.py
```

## Ejemplo v4l2rtspserver + Webcam Follow

```
[Cámara USB] → v4l2rtspserver en RPi → rtsp://192.168.1.100:8554/unicast
                                              ↓
                              Webcam Follow (PC o otra RPi) analiza el stream
                                              ↓
                              Alertas email / Telegram / WhatsApp
```

## Detección de objetos

Por defecto detecta personas, vehículos y animales comunes (clases COCO predefinidas).

```env
# Solo personas y coches
DETECT_CLASSES=0,2

# Todas las clases COCO (80 objetos)
DETECT_CLASSES=all

# Confianza mínima YOLO
YOLO_CONFIDENCE=0.45
```

Referencia COCO: `0=person`, `2=car`, `3=motorcycle`, `5=bus`, `7=truck`, `16=dog`, `17=cat`, etc.

## Perfiles automáticos por plataforma

| Parámetro | PC x86 | Raspberry Pi |
|-----------|--------|--------------|
| Intervalo análisis | 0.5 s | 2.0 s |
| YOLO imgsz | 640 | 320 |
| YOLO device | auto (CUDA si hay GPU) | cpu |
| YOLO solo con movimiento | no | sí |
| Vista previa | sí | no (headless) |

## Configuración de notificaciones

Ver `.env.example` para email, Telegram y WhatsApp (Twilio).

## Variables principales

| Variable | Descripción |
|----------|-------------|
| `STREAM_URL` | URL RTSP/HTTP del transmisor |
| `RTSP_TRANSPORT` | `tcp` (recomendado) o `udp` |
| `VIDEO_SOURCE` | `local` o `stream` |
| `DETECT_CLASSES` | IDs COCO, `all`, o vacío (= default) |
| `YOLO_CONFIDENCE` | Confianza mínima (0–1) |
| `YOLO_ON_MOTION_ONLY` | YOLO solo si hay movimiento |
| `NOTIFICATION_COOLDOWN_SEC` | Segundos entre alertas |
| `WEB_ENABLED` | Activar interfaz web |
| `WEB_PORT` | Puerto del panel (default 8080) |

## Estructura

```
webcam_follow/
├── Containerfile          # Imagen Podman/Docker (multi-arch)
├── compose.yaml           # podman compose up
├── main.py
├── scripts/
│   ├── build-image.sh     # Manifest amd64 + arm64
│   ├── build-image-local.sh
│   └── install.sh         # Instalación nativa
└── src/
    ├── video_source.py    # Webcam local + RTSP/HTTP
    ├── detector.py        # MOG2 + YOLOv8 (personas/objetos)
    └── platform.py        # Perfiles x86 / RPi / contenedor
```

## Licencia

MIT
