const $ = (id) => document.getElementById(id);

let activeCameraId = null;
let frameObjectUrl = null;
let frameLoopActive = false;
let frameTimer = null;
let frameInFlight = false;

/** Intervalo entre frames (~8 FPS en móvil, equilibrio fluidez/ancho de banda). */
const FRAME_INTERVAL_MS = 120;

function formatTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("es");
  } catch {
    return iso;
  }
}

function apiUrl(path, cameraId) {
  const cid = cameraId || activeCameraId;
  return cid ? `${path}?camera_id=${encodeURIComponent(cid)}` : path;
}

function stopLiveFeed() {
  frameLoopActive = false;
  if (frameTimer) {
    clearTimeout(frameTimer);
    frameTimer = null;
  }
}

function setFrameBlob(blob) {
  const feed = $("live-feed");
  const url = URL.createObjectURL(blob);
  feed.src = url;
  if (frameObjectUrl) {
    URL.revokeObjectURL(frameObjectUrl);
  }
  frameObjectUrl = url;
}

async function pollFrameOnce() {
  if (!activeCameraId || frameInFlight) return;
  frameInFlight = true;
  try {
    const res = await fetch(apiUrl("/api/frame") + `&_=${Date.now()}`, {
      cache: "no-store",
      headers: { Accept: "image/jpeg" },
    });
    if (res.ok) {
      setFrameBlob(await res.blob());
      $("video-placeholder").style.display = "none";
      $("live-feed").style.display = "block";
    }
  } catch (err) {
    console.warn("Frame error:", err);
  } finally {
    frameInFlight = false;
  }
}

function scheduleFramePoll() {
  if (!frameLoopActive) return;
  const tick = async () => {
    if (!frameLoopActive) return;
    const t0 = performance.now();
    await pollFrameOnce();
    const elapsed = performance.now() - t0;
    const delay = Math.max(40, FRAME_INTERVAL_MS - elapsed);
    frameTimer = setTimeout(tick, delay);
  };
  tick();
}

function startLiveFeed() {
  stopLiveFeed();
  if (!activeCameraId) return;
  frameLoopActive = true;
  scheduleFramePoll();
}

function reloadVideoFeed() {
  startLiveFeed();
}

async function loadCameras() {
  const res = await fetch("/api/cameras");
  if (!res.ok) return;
  const cameras = await res.json();
  const select = $("camera-select");
  select.innerHTML = cameras
    .map(
      (c) =>
        `<option value="${c.id}" ${c.active ? "selected" : ""}>${c.name}${c.connected ? " ●" : ""}</option>`
    )
    .join("");

  const active = cameras.find((c) => c.active) || cameras[0];
  if (active) {
    activeCameraId = active.id;
  }
}

async function switchCamera(cameraId) {
  activeCameraId = cameraId;
  await fetch("/api/cameras/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ camera_id: cameraId }),
  });
  reloadVideoFeed();
}

function updateStatus(data) {
  const connected = data.connected;
  const badge = $("conn-badge");
  badge.textContent = connected ? "En línea" : "Desconectado";
  badge.className = "badge " + (connected ? "badge--online" : "badge--offline");

  $("fps-badge").textContent = `${data.fps || 0} FPS`;
  $("video-source").textContent = data.video_label || "—";
  $("meta-camera").textContent = data.camera_name || "—";

  const motion = $("stat-motion");
  motion.textContent = data.motion_detected ? "SÍ" : "NO";
  motion.className =
    "stat__value " + (data.motion_detected ? "stat__value--yes" : "stat__value--no");

  $("stat-persons").textContent = data.person_count ?? 0;
  $("stat-objects").textContent = data.total_objects ?? 0;
  $("stat-yolo").textContent = data.yolo_active ? "Activo" : "Reposo";

  $("meta-platform").textContent = data.platform_label || "—";
  $("meta-stream").textContent = data.stream_url || data.video_label || "—";
  $("meta-updated").textContent = formatTime(data.last_update);

  const tags = $("object-tags");
  tags.innerHTML = "";
  const counts = data.object_counts || {};
  Object.entries(counts).forEach(([label, count]) => {
    const span = document.createElement("span");
    span.className = "tag" + (label === "person" ? " tag--person" : "");
    span.textContent = `${label}: ${count}`;
    tags.appendChild(span);
  });

  const placeholder = $("video-placeholder");
  const feed = $("live-feed");
  if (connected) {
    if (!frameLoopActive) {
      startLiveFeed();
    }
    placeholder.style.display = feed.src ? "none" : "flex";
    feed.style.display = feed.src ? "block" : "none";
  } else {
    stopLiveFeed();
    placeholder.style.display = "flex";
    feed.style.display = "none";
    feed.removeAttribute("src");
    if (frameObjectUrl) {
      URL.revokeObjectURL(frameObjectUrl);
      frameObjectUrl = null;
    }
  }

  renderHeatmap(data);
}

function renderHeatmap(data) {
  const zones = data.hot_zones || [];
  const list = $("hot-zones-list");
  if (!zones.length) {
    list.innerHTML = '<li class="muted">Sin actividad acumulada</li>';
  } else {
    list.innerHTML = zones
      .map(
        (z, i) =>
          `<li><strong>#${i + 1}</strong> ${z.x_pct}%, ${z.y_pct}% · intensidad ${Math.round(z.intensity * 100)}%</li>`
      )
      .join("");
  }

  const pred = data.motion_prediction || {};
  const predEl = $("motion-prediction");
  if (pred.active) {
    predEl.textContent = `Predicción: hacia ${pred.to_x}%, ${pred.to_y}% · ${pred.speed.toFixed(1)} %/s · ${pred.direction_deg}°`;
    predEl.classList.remove("muted");
  } else {
    predEl.textContent = "Predicción: sin movimiento suficiente";
    predEl.classList.add("muted");
  }

  const thumb = $("heatmap-thumb");
  if ((data.heatmap_peak || 0) > 0.05) {
    thumb.src = apiUrl("/api/motion/heatmap") + `&t=${Date.now()}`;
    thumb.classList.remove("hidden");
  } else {
    thumb.classList.add("hidden");
  }
}

function renderAlerts(alerts) {
  const list = $("alerts-list");
  if (!alerts.length) {
    list.innerHTML = '<li class="alerts__empty muted">Sin alertas aún</li>';
    return;
  }
  list.innerHTML = alerts
    .map(
      (a) => `
    <li>
      <div class="alert__type">${(a.camera_name || "Cámara")} · ${a.event_type.replace(/_/g, " ")}</div>
      <div>${a.message}</div>
      <div class="alert__time">${formatTime(a.timestamp)}</div>
    </li>`
    )
    .join("");
}

function renderSnapshots(items) {
  const grid = $("snapshots-grid");
  if (!items.length) {
    grid.innerHTML = '<p class="muted snapshots__empty">No hay capturas guardadas</p>';
    return;
  }
  grid.innerHTML = items
    .map(
      (s) => `
    <a class="snapshot" href="${s.url}" target="_blank" rel="noopener">
      <img src="${s.url}" alt="${s.name}" loading="lazy">
      <span>${s.name}</span>
    </a>`
    )
    .join("");
}

async function poll() {
  try {
    const [statusRes, alertsRes] = await Promise.all([
      fetch(apiUrl("/api/status")),
      fetch(apiUrl("/api/alerts")),
    ]);
    if (statusRes.ok) updateStatus(await statusRes.json());
    if (alertsRes.ok) renderAlerts(await alertsRes.json());
  } catch (err) {
    console.warn("Poll error:", err);
  }
}

async function loadSnapshots() {
  try {
    const res = await fetch(apiUrl("/api/snapshots"));
    if (res.ok) renderSnapshots(await res.json());
  } catch (err) {
    console.warn("Snapshots error:", err);
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopLiveFeed();
  } else if (activeCameraId) {
    startLiveFeed();
  }
});

$("camera-select").addEventListener("change", (e) => {
  switchCamera(e.target.value);
});

$("refresh-snapshots").addEventListener("click", loadSnapshots);

$("btn-reset-heatmap").addEventListener("click", async () => {
  try {
    await fetch(apiUrl("/api/motion/heatmap/reset"), { method: "POST" });
    poll();
  } catch (err) {
    console.warn("Heatmap reset:", err);
  }
});

loadCameras().then(() => {
  startLiveFeed();
  poll();
  loadSnapshots();
});
setInterval(poll, 2000);
setInterval(loadSnapshots, 15000);
setInterval(loadCameras, 10000);
