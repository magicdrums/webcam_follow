const $ = (id) => document.getElementById(id);

let activeCameraId = null;

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

function reloadVideoFeed() {
  const feed = $("live-feed");
  feed.src = `/video_feed?camera_id=${encodeURIComponent(activeCameraId || "")}&t=${Date.now()}`;
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
  if (connected) {
    placeholder.style.display = "none";
    $("live-feed").style.display = "block";
  } else {
    placeholder.style.display = "flex";
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

$("camera-select").addEventListener("change", (e) => {
  switchCamera(e.target.value);
});

$("refresh-snapshots").addEventListener("click", loadSnapshots);

loadCameras().then(() => {
  reloadVideoFeed();
  poll();
  loadSnapshots();
});
setInterval(poll, 2000);
setInterval(loadSnapshots, 15000);
setInterval(loadCameras, 10000);
