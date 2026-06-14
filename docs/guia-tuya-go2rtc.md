# Guía paso a paso: cámara Tuya → go2rtc → Webcam Follow

Esta guía conecta una cámara **Smart Life / Tuya** con **Webcam Follow** usando **[go2rtc](https://github.com/AlexxIT/go2rtc)** como puente. go2rtc habla el protocolo propietario de Tuya (WebRTC) y expone un stream **RTSP** que OpenCV ya sabe leer.

> **Por qué este camino:** Tuya Developer Platform ya no permite vídeo en muchas cuentas personales. go2rtc usa la **Tuya Smart API** (email + contraseña de la app), sin proyecto cloud ni Access ID.

---

## Requisitos

| Requisito | Detalle |
|-----------|---------|
| Cámara Tuya | Emparejada en app oficial (no solo apps white-label*) |
| App móvil | **[Tuya Smart](https://play.google.com/store/apps/details?id=com.tuya.smart)** (recomendado por go2rtc) |
| PC / servidor | Linux x86_64 o ARM (misma máquina o LAN) |
| Red | Cámara online en Wi‑Fi; el PC debe salir a Internet |
| go2rtc | Versión **≥ 1.9.13** (soporte Tuya) |
| Webcam Follow | Ya instalado (`python main.py` o contenedor) |

\* Apps como LSC Smart Connect, Nedis, Kruidvat **no** sirven para APIs de terceros. Hay que desvincular la cámara ahí, resetearla y añadirla en **Tuya Smart** o **Smart Life** oficial (Volcano Technology Limited en la tienda).

---

## Paso 1 — Preparar la cuenta y la cámara

### 1.1 Crear cuenta Tuya Smart

1. Instala **Tuya Smart** (no confundir con clones de marca).
2. Regístrate con el **mismo país/región** donde compraste la cámara (p. ej. España → datacenter EU).

### 1.2 Reemparejar la cámara (si venía de Smart Life u otra app)

go2rtc **no admite cuentas Smart Life** para login directo. Si tus cámaras están solo en Smart Life:

1. En Smart Life: **Ajustes del dispositivo → Eliminar dispositivo**.
2. **Reset físico** de la cámara (botón RESET ~5–10 s; consulta el manual).
3. En **Tuya Smart**: **+ → Añadir dispositivo → Cámara** y completa el emparejamiento Wi‑Fi.
4. Comprueba que ves **vídeo en vivo** en Tuya Smart.

> Si prefieres seguir con Smart Life y no migrar, esta guía no aplica; prueba RTSP local (hack SD) u otra alternativa del README.

### 1.3 Anotar región

| Tu zona habitual | Host en go2rtc |
|------------------|----------------|
| Europa central (ES, DE, FR…) | `protect-eu.ismartlife.me` |
| Europa este | `protect-we.ismartlife.me` |
| EE.UU. oeste | `protect-us.ismartlife.me` |
| EE.UU. este | `protect-ue.ismartlife.me` |
| India | `protect-in.ismartlife.me` |
| China | `protect.ismartlife.me` |

Si no estás seguro, en el paso 4 go2rtc te deja elegir región al hacer login.

---

## Paso 2 — Instalar go2rtc

Elige **una** opción.

### Opción A — Binario (rápido en Linux)

```bash
# Descarga la última release (ajusta arquitectura: amd64 / arm64)
GO2RTC_VERSION=1.9.13
curl -L "https://github.com/AlexxIT/go2rtc/releases/download/v${GO2RTC_VERSION}/go2rtc_linux_amd64" -o go2rtc
chmod +x go2rtc
sudo mv go2rtc /usr/local/bin/
```

Comprueba:

```bash
go2rtc -version
```

### Opción B — Podman / Docker

```bash
mkdir -p ~/go2rtc && cd ~/go2rtc

cat > go2rtc.yaml << 'EOF'
api:
  listen: ":1984"
rtsp:
  listen: ":8554"
streams: {}
EOF

podman run -d --name go2rtc \
  --restart unless-stopped \
  -p 1984:1984 \
  -p 8554:8554 \
  -p 8555:8555/tcp \
  -p 8555:8555/udp \
  -v $(pwd)/go2rtc.yaml:/config/go2rtc.yaml \
  ghcr.io/alexxit/go2rtc:latest
```

> Puerto **1984** = interfaz web · **8554** = RTSP · **8555** = WebRTC interno de Tuya.

---

## Paso 3 — Arrancar go2rtc (solo binario)

```bash
mkdir -p ~/go2rtc && cd ~/go2rtc
touch go2rtc.yaml   # puede estar vacío al principio
go2rtc -config go2rtc.yaml
```

Deja el proceso en marcha (o crea un servicio systemd más adelante).

Abre en el navegador: **http://127.0.0.1:1984**

---

## Paso 4 — Descubrir la cámara en go2rtc

1. En **http://127.0.0.1:1984** → menú **Add** (Añadir).
2. Elige **Tuya**.
3. Selecciona **región** (p. ej. `eu-central` / Europa).
4. Introduce **email** y **contraseña** de **Tuya Smart**.
5. Pulsa **Login**.

Deberías ver tus cámaras (categoría IPC). Para cada una, go2rtc genera una URL tipo:

```text
tuya://protect-eu.ismartlife.me?device_id=bfxxxxxxxxxxxx&email=tu@email.com&password=***
```

6. **Copia** esa URL (o el nombre del stream que propone la UI).
7. Añádela a `go2rtc.yaml`:

```yaml
api:
  listen: ":1984"

rtsp:
  listen: ":8554"

streams:
  cam_salon:
    - tuya://protect-eu.ismartlife.me?device_id=bfxxxxxxxxxxxx&email=tu@email.com&password=TU_PASSWORD
```

8. **Reinicia go2rtc** (Ctrl+C y volver a ejecutar, o `podman restart go2rtc`).

### Variante manual (sin UI)

Si ya conoces el `device_id` (aparece en Tuya Smart → info del dispositivo, o en la URL tras el login):

```yaml
streams:
  cam_salon:
    - tuya://protect-eu.ismartlife.me?device_id=DEVICE_ID&email=EMAIL&password=PASSWORD&resolution=hd
```

Parámetros útiles:

| Parámetro | Valores | Notas |
|-----------|---------|-------|
| `resolution` | `hd` (default), `sd` | Si HD falla o va lento, prueba `sd` |
| host | `protect-eu.ismartlife.me` | Debe coincidir con tu región |

---

## Paso 5 — Probar el stream RTSP

Con go2rtc en marcha:

```bash
# ffplay (ffmpeg)
ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/cam_salon

# o VLC: Medio → Abrir URL de red
rtsp://127.0.0.1:8554/cam_salon
```

El nombre final del path RTSP es el **nombre del stream** en `go2rtc.yaml` (`cam_salon` en el ejemplo).

Si no hay imagen:

- Prueba `resolution=sd` en la URL `tuya://...`.
- Comprueba que la cámara está **online** en Tuya Smart.
- Revisa logs de go2rtc en la web (**Log** en :1984).
- Algunas cámaras “batería / timbre” tardan unos segundos en despertar (LowPower).

---

## Paso 6 — Añadir la cámara en Webcam Follow

### 6.1 Instalación nativa (Python en el mismo PC)

1. Abre **http://localhost:8080/admin**
2. Pestaña **Cámaras** → **Nueva cámara**
3. Configura:
   - **Nombre:** p. ej. `Salón Tuya`
   - **Tipo:** `Stream RTSP/HTTP`
   - **URL:** `rtsp://127.0.0.1:8554/cam_salon`
   - **Transporte RTSP:** `tcp` (recomendado)
4. Guarda.

En `.env` puedes dejar `VIDEO_SOURCE=local` si solo usas cámaras del admin; el monitor lee `data/cameras.json`.

### 6.2 Webcam Follow en contenedor + go2rtc en el host

Desde dentro del contenedor, `127.0.0.1` es el propio contenedor, **no** el host.

Usa la IP del host en LAN, por ejemplo:

```text
rtsp://192.168.1.50:8554/cam_salon
```

En Podman también suele funcionar:

```text
rtsp://host.containers.internal:8554/cam_salon
```

Asegúrate de que el puerto **8554** está publicado (`-p 8554:8554`).

### 6.3 Ambos en la misma red Docker/Podman (avanzado)

Puedes añadir go2rtc al `compose.yaml` del proyecto y usar:

```text
rtsp://go2rtc:8554/cam_salon
```

(servicio `go2rtc` en la misma red bridge).

---

## Paso 7 — Verificar detección en Webcam Follow

1. Panel en vivo: **http://localhost:8080**
2. Selector de cámara → elige la que creaste.
3. Deberías ver MJPEG con detecciones.

Si el stream se cae a los minutos:

- Es normal en Tuya; go2rtc renueva la sesión WebRTC.
- Webcam Follow reconecta solo (`STREAM_RECONNECT_SEC=5` por defecto).
- Mantén **go2rtc siempre en ejecución** como servicio.

---

## Paso 8 — Servicio systemd (opcional)

Para que go2rtc arranque al boot:

```bash
sudo tee /etc/systemd/system/go2rtc.service << EOF
[Unit]
Description=go2rtc RTSP bridge
After=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/go2rtc
ExecStart=/usr/local/bin/go2rtc -config $HOME/go2rtc/go2rtc.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now go2rtc
```

---

## Solución de problemas

| Síntoma | Qué probar |
|---------|------------|
| Login Tuya falla en go2rtc | Cuenta **Tuya Smart**, región correcta, cámara en esa cuenta |
| Lista vacía tras login | Cámara no es IPC; solo timbres/cámaras aparecen |
| RTSP sin vídeo | `resolution=sd`; cámara offline; esperar wake-up |
| Webcam Follow “no abre stream” | URL con IP del host si usas contenedor; `RTSP_TRANSPORT=tcp` |
| Muy lento en Raspberry Pi | Stream `sd`; sube `DETECTION_INTERVAL_SEC`; YOLO solo con movimiento |
| Error de contraseña en YAML | Caracteres especiales: pon la URL entre comillas en YAML |
| Smart Life obligatorio | go2rtc Smart API **no** soporta Smart Life; migra a Tuya Smart o usa hack RTSP local |

### Probar solo la red entre contenedor y go2rtc

```bash
podman exec -it webcam-follow ffprobe -rtsp_transport tcp \
  rtsp://host.containers.internal:8554/cam_salon
```

(Si `ffprobe` no está en la imagen, prueba desde el host.)

---

## Seguridad

- go2rtc expone **1984** y **8554** sin contraseña por defecto en toda la LAN.
- En producción, limita a localhost en `go2rtc.yaml`:

```yaml
api:
  listen: "127.0.0.1:1984"
rtsp:
  listen: "127.0.0.1:8554"
```

- No subas `go2rtc.yaml` con contraseñas a git.
- Webcam Follow no necesita tus credenciales Tuya; solo la URL RTSP local.

---

## Resumen del flujo

```text
[Cámara Tuya Wi‑Fi]
        ↕ WebRTC / MQTT (nube Tuya)
     [go2rtc]
        ↕ RTSP rtsp://HOST:8554/cam_salon
  [Webcam Follow]
        ↕ detección + alertas + web :8080
```

**Checklist rápido**

- [ ] Cámara en **Tuya Smart**, vídeo OK en la app
- [ ] go2rtc ≥ 1.9.13 en marcha
- [ ] Stream en `go2rtc.yaml` y RTSP OK con ffplay/VLC
- [ ] Cámara **Stream RTSP** en Webcam Follow con URL correcta (IP host si hay contenedor)
- [ ] Vista en vivo en http://localhost:8080

---

## Referencias

- [go2rtc — Tuya](https://github.com/AlexxIT/go2rtc/blob/master/internal/tuya/README.md)
- [Webcam Follow README](../README.md)
- Portal web Tuya (EU): https://protect-eu.ismartlife.me/login (útil para comprobar que la cuenta ve la cámara)
