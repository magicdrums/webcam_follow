const $ = (id) => document.getElementById(id);

let activeCameraId = null;
let frameLoopActive = false;
let frameTimer = null;
let frameInFlight = false;
let hasLiveFrame = false;
let frameFailStreak = 0;
let canvasCtx = null;

/** ~4 FPS: fluido en móvil sin saturar red ni provocar parpadeos. */
const FRAME_INTERVAL_MS = 250;
const FRAME_INTERVAL_MAX_MS = 1200;

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

function getCanvasContext() {
  if (!canvasCtx) {
    const canvas = $("live-feed");
    canvasCtx = canvas.getContext("2d", { alpha: false });
  }
  return canvasCtx;
}

function showLiveFrame() {
  $("video-wrap").classList.add("is-live");
  hasLiveFrame = true;
}

function showPlaceholder() {
  $("video-wrap").classList.remove("is-live");
  hasLiveFrame = false;
}

function stopLiveFeed() {
  frameLoopActive = false;
  if (frameTimer) {
    clearTimeout(frameTimer);
    frameTimer = null;
  }
}

async function drawFrameBlob(blob) {
  const canvas = $("live-feed");
  const wrap = $("video-wrap");
  const ctx = getCanvasContext();
  let bitmap;
  try {
    bitmap = await createImageBitmap(blob);
  } catch (err) {
    console.warn("Frame decode error:", err);
    return false;
  }

  const cw = wrap.clientWidth || bitmap.width;
  const ch = wrap.clientHeight || bitmap.height;
  if (canvas.width !== cw || canvas.height !== ch) {
    canvas.width = cw;
    canvas.height = ch;
  }

  const scale = Math.min(cw / bitmap.width, ch / bitmap.height);
  const dw = bitmap.width * scale;
  const dh = bitmap.height * scale;
  const dx = (cw - dw) / 2;
  const dy = (ch - dh) / 2;

  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, cw, ch);
  ctx.drawImage(bitmap, dx, dy, dw, dh);
  bitmap.close();
  showLiveFrame();
  frameFailStreak = 0;
  return true;
}

function nextFrameDelay() {
  if (frameFailStreak === 0) {
    return FRAME_INTERVAL_MS;
  }
  const backoff = FRAME_INTERVAL_MS * Math.min(frameFailStreak, 4);
  return Math.min(backoff, FRAME_INTERVAL_MAX_MS);
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
      await drawFrameBlob(await res.blob());
    } else if (res.status === 404) {
      frameFailStreak += 1;
      if (!hasLiveFrame) {
        showPlaceholder();
      }
    }
  } catch (err) {
    frameFailStreak += 1;
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
    const delay = Math.max(50, nextFrameDelay() - elapsed);
    frameTimer = setTimeout(tick, delay);
  };
  tick();
}

function startLiveFeed() {
  if (frameLoopActive) return;
  if (!activeCameraId) return;
  frameLoopActive = true;
  frameFailStreak = 0;
  scheduleFramePoll();
}

function reloadVideoFeed() {
  stopLiveFeed();
  showPlaceholder();
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
  if (active && active.id !== activeCameraId) {
    activeCameraId = active.id;
    reloadVideoFeed();
  } else if (active) {
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

  if (activeCameraId && !frameLoopActive) {
    startLiveFeed();
  }

  renderHeatmap(data);
}

function renderHeatmap(data) {
  const panel = $("heatmap-panel");
  const heatmapOn = data.heatmap_enabled !== false;
  panel.classList.toggle("hidden", !heatmapOn);
  if (!heatmapOn) {
    return;
  }

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

let selectedSnapshotDate = null;
let calendarView = new Date();

const MONTH_NAMES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

function monthKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function formatSnapshotTime(item) {
  const raw = item.timestamp || item.mtime;
  if (!raw) return item.name;
  try {
    return new Date(raw).toLocaleString("es", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return item.name;
  }
}

function renderSnapshots(items) {
  const grid = $("snapshots-grid");
  const label = $("snap-filter-label");
  if (label) {
    if (selectedSnapshotDate) {
      const count = items.length;
      label.textContent = `${count} archivo(s) del ${selectedSnapshotDate} (fotos y grabaciones)`;
    } else {
      label.textContent = "Mostrando capturas recientes";
    }
  }
  if (!items.length) {
    grid.innerHTML = '<p class="muted snapshots__empty">No hay capturas para esta búsqueda</p>';
    return;
  }
  grid.innerHTML = items
    .map((s) => {
      const isVideo = s.kind === "video" || s.media_type === "mp4";
      const badge = isVideo ? "▶ Vídeo" : "Foto";
      return `
    <a class="snapshot" href="${s.url}" target="_blank" rel="noopener">
      <span class="snapshot__badge">${badge}</span>
      ${
        isVideo
          ? `<video src="${s.url}" muted playsinline preload="metadata"></video>`
          : `<img src="${s.url}" alt="${s.name || s.filename}" loading="lazy">`
      }
      <span>${formatSnapshotTime(s)}</span>
    </a>`;
    })
    .join("");
}

async function loadSnapshotDates() {
  const month = monthKey(calendarView);
  try {
    const res = await fetch(`${apiUrl("/api/snapshots/dates")}&month=${month}`);
    if (!res.ok) return {};
    const data = await res.json();
    const map = {};
    (data.days || []).forEach((day) => {
      map[day.date] = day;
    });
    return map;
  } catch (err) {
    console.warn("Calendar dates error:", err);
    return {};
  }
}

function renderSnapshotCalendar(daysMap) {
  const grid = $("snap-calendar-grid");
  const label = $("cal-month-label");
  if (!grid || !label) return;

  const year = calendarView.getFullYear();
  const month = calendarView.getMonth();
  label.textContent = `${MONTH_NAMES[month]} ${year}`;

  const firstDay = new Date(year, month, 1);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayKey = new Date().toISOString().slice(0, 10);

  grid.innerHTML = "";
  for (let i = 0; i < startOffset; i += 1) {
    const pad = document.createElement("button");
    pad.type = "button";
    pad.className = "snap-calendar__day snap-calendar__day--muted";
    pad.disabled = true;
    pad.textContent = "";
    grid.appendChild(pad);
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const stats = daysMap[dateStr];
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "snap-calendar__day";
    const dayNum = document.createElement("span");
    dayNum.textContent = String(day);
    btn.appendChild(dayNum);
    if (stats) {
      btn.classList.add("snap-calendar__day--has-media");
      btn.title = `${stats.count} archivo(s): ${stats.photos} foto(s), ${stats.videos} vídeo(s)`;
      const dot = document.createElement("span");
      dot.className = "snap-calendar__dot" + (stats.videos > 0 ? " snap-calendar__dot--video" : "");
      btn.appendChild(dot);
    }
    if (dateStr === todayKey) {
      btn.classList.add("snap-calendar__day--today");
    }
    if (dateStr === selectedSnapshotDate) {
      btn.classList.add("snap-calendar__day--selected");
    }
    btn.addEventListener("click", () => {
      selectedSnapshotDate = dateStr;
      refreshSnapshotsPanel();
    });
    grid.appendChild(btn);
  }
}

async function refreshSnapshotsPanel() {
  await Promise.all([loadSnapshotDates().then(renderSnapshotCalendar), loadSnapshots()]);
}

async function loadSnapshots() {
  try {
    let url = apiUrl("/api/snapshots");
    if (selectedSnapshotDate) {
      url += `&date=${encodeURIComponent(selectedSnapshotDate)}`;
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    renderSnapshots(data.items || []);
  } catch (err) {
    console.warn("Snapshots error:", err);
  }
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

$("refresh-snapshots").addEventListener("click", () => refreshSnapshotsPanel());

$("cal-prev").addEventListener("click", () => {
  calendarView = new Date(calendarView.getFullYear(), calendarView.getMonth() - 1, 1);
  refreshSnapshotsPanel();
});

$("cal-next").addEventListener("click", () => {
  calendarView = new Date(calendarView.getFullYear(), calendarView.getMonth() + 1, 1);
  refreshSnapshotsPanel();
});

$("cal-clear").addEventListener("click", () => {
  selectedSnapshotDate = null;
  refreshSnapshotsPanel();
});

function openSideMenu() {
  $("side-menu").classList.add("is-open");
  $("side-menu").setAttribute("aria-hidden", "false");
  $("menu-backdrop").classList.remove("hidden");
  $("menu-backdrop").setAttribute("aria-hidden", "false");
  $("menu-toggle").setAttribute("aria-expanded", "true");
  document.body.classList.add("menu-open");
  refreshSnapshotsPanel();
  poll();
}

function closeSideMenu() {
  $("side-menu").classList.remove("is-open");
  $("side-menu").setAttribute("aria-hidden", "true");
  $("menu-backdrop").classList.add("hidden");
  $("menu-backdrop").setAttribute("aria-hidden", "true");
  $("menu-toggle").setAttribute("aria-expanded", "false");
  document.body.classList.remove("menu-open");
}

function switchMenuPanel(panelId) {
  document.querySelectorAll(".side-menu__tab").forEach((tab) => {
    const active = tab.dataset.menuPanel === panelId;
    tab.classList.toggle("side-menu__tab--active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  $("menu-panel-snapshots").classList.toggle("hidden", panelId !== "snapshots");
  $("menu-panel-alerts").classList.toggle("hidden", panelId !== "alerts");
  if (panelId === "snapshots") {
    refreshSnapshotsPanel();
  } else {
    poll();
  }
}

$("menu-toggle").addEventListener("click", () => {
  if ($("side-menu").classList.contains("is-open")) {
    closeSideMenu();
  } else {
    openSideMenu();
  }
});

$("menu-close").addEventListener("click", closeSideMenu);
$("menu-backdrop").addEventListener("click", closeSideMenu);

document.querySelectorAll(".side-menu__tab").forEach((tab) => {
  tab.addEventListener("click", () => switchMenuPanel(tab.dataset.menuPanel));
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && $("side-menu").classList.contains("is-open")) {
    closeSideMenu();
  }
});

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
});
setInterval(poll, 2000);
setInterval(() => {
  if ($("side-menu").classList.contains("is-open") && !$("menu-panel-snapshots").classList.contains("hidden")) {
    refreshSnapshotsPanel();
  }
}, 15000);
setInterval(loadCameras, 10000);
