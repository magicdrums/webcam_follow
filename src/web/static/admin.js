const $ = (id) => document.getElementById(id);

const EVENT_LABELS = {
  movimiento: "Movimiento",
  objeto_detectado: "Objeto",
  cambio_objetos: "Cambio objetos",
  cambio_escena: "Cambio escena",
};

function toast(msg, isError = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " toast--error" : "");
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3000);
}

function parseAppDate(iso) {
  if (!iso) return null;
  const raw = String(iso).trim();
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(raw) && !/(Z|[+-]\d{2}:\d{2})$/i.test(raw)) {
    return new Date(`${raw}Z`);
  }
  return new Date(raw);
}

function formatTime(iso) {
  if (!iso) return "—";
  try {
    const date = parseAppDate(iso);
    if (!date || Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString("es", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.description || err.error || `Error ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// --- Tabs ---
document.querySelectorAll(".tabs__btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs__btn").forEach((b) => b.classList.remove("tabs__btn--active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("tab-panel--active"));
    btn.classList.add("tabs__btn--active");
    $(`tab-${btn.dataset.tab}`).classList.add("tab-panel--active");
  });
});

// --- Cámaras ---
let tuyaDevicesCache = [];

function sourceTypeLabel(type) {
  if (type === "stream") return "Stream";
  if (type === "tuya") return "Tuya";
  return "Local";
}

function sourceDetail(camera) {
  if (camera.source_type === "stream") return camera.stream_url;
  if (camera.source_type === "tuya") return camera.tuya_device_id || "—";
  return "índice " + camera.camera_index;
}

async function loadTuyaDeviceOptions(selectedId = "") {
  const sel = $("camera-tuya-device");
  if (!sel) return;
  try {
    tuyaDevicesCache = await api("GET", "/api/admin/tuya/devices");
  } catch {
    tuyaDevicesCache = [];
  }
  if (!tuyaDevicesCache.length) {
    sel.innerHTML = '<option value="">— Configura Tuya y busca dispositivos —</option>';
    if (selectedId) {
      sel.innerHTML += `<option value="${selectedId}" selected>${selectedId}</option>`;
    }
    return;
  }
  sel.innerHTML = tuyaDevicesCache
    .map(
      (d) =>
        `<option value="${d.id}" ${d.id === selectedId ? "selected" : ""}>${d.name}${d.online ? "" : " (offline)"}${d.is_ipc ? "" : " · otro"}</option>`
    )
    .join("");
}

function toggleCameraSourceFields() {
  const type = $("camera-source-type").value;
  $("field-camera-index").classList.toggle("hidden", type !== "local");
  $("field-stream-url").classList.toggle("hidden", type !== "stream");
  $("field-rtsp-transport").classList.toggle("hidden", type !== "stream");
  $("field-tuya-device").classList.toggle("hidden", type !== "tuya");
  $("field-tuya-stream-type").classList.toggle("hidden", type !== "tuya");
  if (type === "tuya") loadTuyaDeviceOptions($("camera-tuya-device").value);
}

$("camera-source-type").addEventListener("change", toggleCameraSourceFields);

function showCameraForm(camera = null) {
  $("camera-form-panel").classList.remove("hidden");
  $("camera-form-title").textContent = camera ? "Editar cámara" : "Nueva cámara";
  $("camera-id").value = camera?.id || "";
  $("camera-name").value = camera?.name || "";
  $("camera-source-type").value = camera?.source_type || "local";
  $("camera-index").value = camera?.camera_index ?? 0;
  $("camera-stream-url").value = camera?.stream_url || "";
  $("camera-rtsp-transport").value = camera?.rtsp_transport || "tcp";
  $("camera-tuya-stream-type").value = camera?.tuya_stream_type || "rtsp";
  $("camera-enabled").checked = camera?.enabled !== false;
  $("camera-heatmap-enabled").checked = camera?.heatmap_enabled !== false;
  toggleCameraSourceFields();
  if (camera?.source_type === "tuya") {
    loadTuyaDeviceOptions(camera.tuya_device_id || "");
  }
}

function hideCameraForm() {
  $("camera-form-panel").classList.add("hidden");
  $("camera-form").reset();
}

async function loadCamerasAdmin() {
  const cameras = await api("GET", "/api/admin/cameras");
  const wrap = $("cameras-table");
  if (!cameras.length) {
    wrap.innerHTML = '<p class="muted">No hay cámaras. Crea una nueva.</p>';
    return;
  }
  wrap.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Nombre</th><th>Tipo</th><th>Fuente</th><th>Calor</th><th>Estado</th><th></th>
        </tr>
      </thead>
      <tbody>
        ${cameras
          .map(
            (c) => `
          <tr>
            <td><strong>${c.name}</strong></td>
            <td>${sourceTypeLabel(c.source_type)}</td>
            <td class="cell-mono">${sourceDetail(c)}</td>
            <td>${c.heatmap_enabled !== false ? "Sí" : "No"}</td>
            <td><span class="badge ${c.enabled ? "badge--online" : ""}">${c.enabled ? "Activa" : "Inactiva"}</span></td>
            <td class="cell-actions">
              <button class="btn btn--sm" data-edit-camera="${c.id}">Editar</button>
              <button class="btn btn--sm btn--danger" data-del-camera="${c.id}">Eliminar</button>
            </td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>`;

  wrap.querySelectorAll("[data-edit-camera]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cam = cameras.find((c) => c.id === btn.dataset.editCamera);
      showCameraForm(cam);
    });
  });
  wrap.querySelectorAll("[data-del-camera]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta cámara?")) return;
      try {
        await api("DELETE", `/api/admin/cameras/${btn.dataset.delCamera}`);
        toast("Cámara eliminada");
        loadCamerasAdmin();
        populateRuleCameras();
      } catch (e) {
        toast(e.message, true);
      }
    });
  });
}

$("btn-new-camera").addEventListener("click", () => showCameraForm());
$("camera-form-cancel").addEventListener("click", hideCameraForm);

$("camera-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("camera-id").value;
  const payload = {
    name: $("camera-name").value.trim(),
    source_type: $("camera-source-type").value,
    camera_index: parseInt($("camera-index").value, 10),
    stream_url: $("camera-stream-url").value.trim(),
    rtsp_transport: $("camera-rtsp-transport").value,
    tuya_device_id: $("camera-tuya-device").value,
    tuya_stream_type: $("camera-tuya-stream-type").value,
    enabled: $("camera-enabled").checked,
    heatmap_enabled: $("camera-heatmap-enabled").checked,
  };
  try {
    if (id) {
      await api("PUT", `/api/admin/cameras/${id}`, payload);
      toast("Cámara actualizada");
    } else {
      await api("POST", "/api/admin/cameras", payload);
      toast("Cámara creada");
    }
    hideCameraForm();
    loadCamerasAdmin();
    populateRuleCameras();
  } catch (err) {
    toast(err.message, true);
  }
});

// --- Reglas ---
async function populateRuleCameras(selected = []) {
  const cameras = await api("GET", "/api/admin/cameras");
  const sel = $("rule-cameras");
  sel.innerHTML = cameras
    .map(
      (c) =>
        `<option value="${c.id}" ${selected.includes(c.id) ? "selected" : ""}>${c.name}</option>`
    )
    .join("");
}

function showRuleForm(rule = null) {
  $("rule-form-panel").classList.remove("hidden");
  $("rule-form-title").textContent = rule ? "Editar regla" : "Nueva regla";
  $("rule-id").value = rule?.id || "";
  $("rule-name").value = rule?.name || "";
  $("rule-min-persons").value = rule?.min_persons ?? 0;
  $("rule-cooldown").value = rule?.cooldown_sec ?? 60;
  $("rule-email").checked = rule?.notify_email ?? false;
  $("rule-telegram").checked = rule?.notify_telegram ?? false;
  $("rule-whatsapp").checked = rule?.notify_whatsapp ?? false;
  $("rule-enabled").checked = rule?.enabled !== false;
  document.querySelectorAll('input[name="event"]').forEach((cb) => {
    cb.checked = rule ? rule.event_types.includes(cb.value) : cb.checked;
  });
  populateRuleCameras(rule?.camera_ids || []);
}

function hideRuleForm() {
  $("rule-form-panel").classList.add("hidden");
}

async function loadRules() {
  const rules = await api("GET", "/api/admin/alert-rules");
  const cameras = await api("GET", "/api/admin/cameras");
  const camMap = Object.fromEntries(cameras.map((c) => [c.id, c.name]));
  const wrap = $("rules-table");

  if (!rules.length) {
    wrap.innerHTML = '<p class="muted">No hay reglas. Crea una para recibir notificaciones.</p>';
    return;
  }

  wrap.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Nombre</th><th>Cámaras</th><th>Eventos</th><th>Canales</th><th>Cooldown</th><th></th>
        </tr>
      </thead>
      <tbody>
        ${rules
          .map((r) => {
            const cams =
              r.camera_ids.length === 0
                ? "Todas"
                : r.camera_ids.map((id) => camMap[id] || id).join(", ");
            const channels = [
              r.notify_email && "Email",
              r.notify_telegram && "Telegram",
              r.notify_whatsapp && "WhatsApp",
            ]
              .filter(Boolean)
              .join(", ") || "—";
            const events = r.event_types.map((e) => EVENT_LABELS[e] || e).join(", ");
            return `
          <tr>
            <td><strong>${r.name}</strong> ${r.enabled ? "" : '<span class="muted">(inactiva)</span>'}</td>
            <td>${cams}</td>
            <td>${events}</td>
            <td>${channels}</td>
            <td>${r.cooldown_sec}s</td>
            <td class="cell-actions">
              <button class="btn btn--sm" data-edit-rule="${r.id}">Editar</button>
              <button class="btn btn--sm btn--danger" data-del-rule="${r.id}">Eliminar</button>
            </td>
          </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;

  wrap.querySelectorAll("[data-edit-rule]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rule = rules.find((r) => r.id === btn.dataset.editRule);
      showRuleForm(rule);
    });
  });
  wrap.querySelectorAll("[data-del-rule]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta regla?")) return;
      try {
        await api("DELETE", `/api/admin/alert-rules/${btn.dataset.delRule}`);
        toast("Regla eliminada");
        loadRules();
      } catch (e) {
        toast(e.message, true);
      }
    });
  });
}

$("btn-new-rule").addEventListener("click", () => showRuleForm());
$("rule-form-cancel").addEventListener("click", hideRuleForm);

$("rule-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("rule-id").value;
  const payload = {
    name: $("rule-name").value.trim(),
    camera_ids: Array.from($("rule-cameras").selectedOptions).map((o) => o.value),
    event_types: Array.from(document.querySelectorAll('input[name="event"]:checked')).map(
      (cb) => cb.value
    ),
    min_persons: parseInt($("rule-min-persons").value, 10),
    cooldown_sec: parseInt($("rule-cooldown").value, 10),
    notify_email: $("rule-email").checked,
    notify_telegram: $("rule-telegram").checked,
    notify_whatsapp: $("rule-whatsapp").checked,
    enabled: $("rule-enabled").checked,
  };
  try {
    if (id) {
      await api("PUT", `/api/admin/alert-rules/${id}`, payload);
      toast("Regla actualizada");
    } else {
      await api("POST", "/api/admin/alert-rules", payload);
      toast("Regla creada");
    }
    hideRuleForm();
    loadRules();
  } catch (err) {
    toast(err.message, true);
  }
});

// --- Historial ---
async function loadHistory() {
  const entries = await api("GET", "/api/admin/alerts/history?limit=100");
  const wrap = $("history-table");
  if (!entries.length) {
    wrap.innerHTML = '<p class="muted">Sin eventos registrados.</p>';
    return;
  }
  wrap.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Fecha</th><th>Cámara</th><th>Evento</th><th>Detalle</th><th>Notificado</th><th></th>
        </tr>
      </thead>
      <tbody>
        ${entries
          .map(
            (e) => `
          <tr>
            <td>${formatTime(e.timestamp)}</td>
            <td>${e.camera_name}</td>
            <td>${EVENT_LABELS[e.event_type] || e.event_type}</td>
            <td>${e.message}</td>
            <td>${e.notified ? "✓" : "—"}</td>
            <td>
              ${e.snapshot ? `<a href="/snapshots/${e.camera_id}/${e.snapshot}" target="_blank" class="btn btn--sm">Foto</a>` : ""}
              <button class="btn btn--sm btn--danger" data-del-history="${e.id}">×</button>
            </td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>`;

  wrap.querySelectorAll("[data-del-history]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("DELETE", `/api/admin/alerts/history/${btn.dataset.delHistory}`);
        loadHistory();
      } catch (err) {
        toast(err.message, true);
      }
    });
  });
}

$("btn-clear-history").addEventListener("click", async () => {
  if (!confirm("¿Vaciar todo el historial?")) return;
  try {
    await api("DELETE", "/api/admin/alerts/history");
    toast("Historial vaciado");
    loadHistory();
  } catch (e) {
    toast(e.message, true);
  }
});

$("btn-clear-history").addEventListener("click", async () => {
  if (!confirm("¿Vaciar todo el historial?")) return;
  try {
    await api("DELETE", "/api/admin/alerts/history");
    toast("Historial vaciado");
    loadHistory();
  } catch (e) {
    toast(e.message, true);
  }
});

// --- Canales de notificación ---
async function loadChannels() {
  const ch = await api("GET", "/api/admin/channels");
  $("ch-email-enabled").checked = ch.email_enabled;
  $("ch-smtp-host").value = ch.smtp_host || "";
  $("ch-smtp-port").value = ch.smtp_port || 587;
  $("ch-smtp-user").value = ch.smtp_user || "";
  $("ch-smtp-password").value = "";
  $("ch-smtp-password").placeholder = ch.smtp_password_set
    ? "Configurada — dejar vacío para mantener"
    : "Contraseña SMTP";
  $("ch-email-from").value = ch.email_from || "";
  $("ch-email-to").value = ch.email_to || "";

  $("ch-telegram-enabled").checked = ch.telegram_enabled;
  $("ch-telegram-token").value = "";
  $("ch-telegram-token").placeholder = ch.telegram_bot_token_set
    ? "Configurado — dejar vacío para mantener"
    : "Bot token";
  $("ch-telegram-chat-id").value = ch.telegram_chat_id || "";

  $("ch-whatsapp-enabled").checked = ch.whatsapp_enabled;
  $("ch-twilio-sid").value = ch.twilio_account_sid || "";
  $("ch-twilio-token").value = "";
  $("ch-twilio-token").placeholder = ch.twilio_auth_token_set
    ? "Configurado — dejar vacío para mantener"
    : "Auth token";
  $("ch-twilio-from").value = ch.twilio_whatsapp_from || "";
  $("ch-whatsapp-to").value = ch.whatsapp_to || "";
}

$("channels-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    email_enabled: $("ch-email-enabled").checked,
    smtp_host: $("ch-smtp-host").value.trim(),
    smtp_port: parseInt($("ch-smtp-port").value, 10),
    smtp_user: $("ch-smtp-user").value.trim(),
    email_from: $("ch-email-from").value.trim(),
    email_to: $("ch-email-to").value.trim(),
    telegram_enabled: $("ch-telegram-enabled").checked,
    telegram_chat_id: $("ch-telegram-chat-id").value.trim(),
    whatsapp_enabled: $("ch-whatsapp-enabled").checked,
    twilio_account_sid: $("ch-twilio-sid").value.trim(),
    twilio_whatsapp_from: $("ch-twilio-from").value.trim(),
    whatsapp_to: $("ch-whatsapp-to").value.trim(),
  };
  const smtpPass = $("ch-smtp-password").value;
  if (smtpPass) payload.smtp_password = smtpPass;
  const tgToken = $("ch-telegram-token").value;
  if (tgToken) payload.telegram_bot_token = tgToken;
  const twToken = $("ch-twilio-token").value;
  if (twToken) payload.twilio_auth_token = twToken;

  try {
    await api("PUT", "/api/admin/channels", payload);
    toast("Canales guardados");
    loadChannels();
  } catch (err) {
    toast(err.message, true);
  }
});

document.querySelectorAll("[data-test-channel]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const channel = btn.dataset.testChannel;
    try {
      const res = await api("POST", "/api/admin/channels/test", { channel });
      toast(res.message || `Prueba ${channel} enviada`);
    } catch (err) {
      toast(err.message, true);
    }
  });
});

// --- Tuya IoT ---
async function loadTuyaConfig() {
  const cfg = await api("GET", "/api/admin/tuya/config");
  $("tuya-enabled").checked = cfg.enabled;
  $("tuya-access-id").value = cfg.access_id || "";
  $("tuya-access-key").value = "";
  $("tuya-access-key").placeholder = cfg.access_key_set
    ? "Configurada — dejar vacío para mantener"
    : "Access Key";
  $("tuya-uid").value = cfg.uid || "";
  $("tuya-region").value = cfg.api_region || "eu";
  $("tuya-default-stream").value = cfg.default_stream_type || "rtsp";
}

$("tuya-config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    enabled: $("tuya-enabled").checked,
    access_id: $("tuya-access-id").value.trim(),
    uid: $("tuya-uid").value.trim(),
    api_region: $("tuya-region").value,
    default_stream_type: $("tuya-default-stream").value,
  };
  const key = $("tuya-access-key").value;
  if (key) payload.access_key = key;
  try {
    await api("PUT", "/api/admin/tuya/config", payload);
    toast("Configuración Tuya guardada");
    loadTuyaConfig();
  } catch (err) {
    toast(err.message, true);
  }
});

$("btn-tuya-test").addEventListener("click", async () => {
  try {
    const res = await api("POST", "/api/admin/tuya/test");
    toast(`Conexión OK — ${res.device_count} dispositivo(s)`);
  } catch (err) {
    toast(err.message, true);
  }
});

async function loadTuyaDevices() {
  const wrap = $("tuya-devices-table");
  wrap.innerHTML = '<p class="muted">Buscando dispositivos…</p>';
  try {
    const devices = await api("GET", "/api/admin/tuya/devices");
    tuyaDevicesCache = devices;
    if (!devices.length) {
      wrap.innerHTML = '<p class="muted">No se encontraron dispositivos en tu cuenta Tuya.</p>';
      return;
    }
    wrap.innerHTML = `
      <table class="table">
        <thead>
          <tr>
            <th>Nombre</th><th>ID</th><th>Categoría</th><th>Estado</th><th></th>
          </tr>
        </thead>
        <tbody>
          ${devices
            .map(
              (d) => `
            <tr>
              <td><strong>${d.name}</strong>${d.is_ipc ? "" : ' <span class="muted">(no IPC)</span>'}</td>
              <td class="cell-mono">${d.id}</td>
              <td>${d.category || d.product_name || "—"}</td>
              <td><span class="badge ${d.online ? "badge--online" : ""}">${d.online ? "Online" : "Offline"}</span></td>
              <td class="cell-actions">
                <button class="btn btn--sm btn--primary" data-add-tuya="${d.id}" data-tuya-name="${d.name.replace(/"/g, "&quot;")}">Añadir</button>
              </td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;

    wrap.querySelectorAll("[data-add-tuya]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const deviceId = btn.dataset.addTuya;
        const name = btn.dataset.tuyaName || "Cámara Tuya";
        try {
          await api("POST", "/api/admin/tuya/cameras", {
            device_id: deviceId,
            name,
            stream_type: $("tuya-default-stream").value,
          });
          toast(`Cámara «${name}» añadida`);
          loadCamerasAdmin();
          populateRuleCameras();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
  } catch (err) {
    wrap.innerHTML = `<p class="muted">${err.message}</p>`;
  }
}

$("btn-tuya-refresh").addEventListener("click", () => loadTuyaDevices());

// --- YOLO / Detección ---
let yoloCocoClasses = [];

function toggleYoloClassesPanel() {
  const isCustom = $("yolo-classes-mode").value === "custom";
  $("yolo-classes-custom-panel").classList.toggle("hidden", !isCustom);
}

function selectedYoloClassIds() {
  return Array.from(
    document.querySelectorAll('input[name="yolo-class"]:checked')
  ).map((cb) => parseInt(cb.value, 10));
}

function setYoloClassCheckboxes(ids) {
  const idSet = new Set(ids.map((id) => String(id)));
  document.querySelectorAll('input[name="yolo-class"]').forEach((cb) => {
    cb.checked = idSet.has(cb.value);
  });
}

function renderYoloClassGrid(classes) {
  const panel = $("yolo-classes-custom-panel");
  panel.innerHTML = classes
    .map(
      (c) => `
    <label class="yolo-class-chip">
      <input type="checkbox" name="yolo-class" value="${c.id}">
      <span>${c.label} (${c.id})</span>
    </label>`
    )
    .join("");
}

function setSnapshotEventCheckboxes(types) {
  const allowed = new Set(types || []);
  document.querySelectorAll('input[name="snapshot-event"]').forEach((el) => {
    el.checked = allowed.has(el.value);
  });
}

function selectedSnapshotEventTypes() {
  return Array.from(document.querySelectorAll('input[name="snapshot-event"]:checked')).map(
    (el) => el.value
  );
}

async function loadYoloAdmin() {
  const [{ classes }, cfg] = await Promise.all([
    api("GET", "/api/admin/yolo/classes"),
    api("GET", "/api/admin/yolo/config"),
  ]);
  yoloCocoClasses = classes;
  renderYoloClassGrid(classes);

  $("yolo-confidence").value = cfg.yolo_confidence;
  $("yolo-imgsz").value = cfg.yolo_imgsz;
  $("yolo-interval").value = cfg.detection_interval_sec;
  $("yolo-model").value = cfg.yolo_model || "yolov8n.pt";
  $("yolo-device").value = cfg.yolo_device || "auto";
  $("yolo-on-motion-only").checked = cfg.yolo_on_motion_only;
  $("yolo-save-snapshots").checked = cfg.save_snapshots !== false;
  setSnapshotEventCheckboxes(cfg.snapshot_event_types);
  $("yolo-snapshot-cooldown").value = cfg.snapshot_cooldown_sec ?? 60;
  $("yolo-snapshot-min-persons").value = cfg.snapshot_min_persons ?? 0;
  $("yolo-heatmap-enabled").checked = cfg.heatmap_enabled !== false;
  $("yolo-prediction-enabled").checked = cfg.motion_prediction_enabled !== false;
  $("yolo-heatmap-opacity").value = cfg.heatmap_opacity ?? 0.45;
  $("yolo-heatmap-decay").value = cfg.heatmap_decay ?? 0.96;
  $("yolo-motion-threshold").value = cfg.motion_threshold;
  $("yolo-min-motion-area").value = cfg.min_motion_area;
  $("yolo-motion-recording").checked = cfg.motion_recording_enabled === true;
  $("yolo-motion-recording-duration").value = cfg.motion_recording_duration_sec ?? 30;
  $("yolo-motion-recording-cooldown").value = cfg.motion_recording_cooldown_sec ?? 120;
  $("yolo-classes-mode").value = cfg.detect_classes_mode || "default";
  $("yolo-classes-custom").value = cfg.detect_classes_custom || "";
  if (cfg.detect_class_ids) {
    setYoloClassCheckboxes(cfg.detect_class_ids);
  }
  toggleYoloClassesPanel();
}

$("yolo-classes-mode").addEventListener("change", toggleYoloClassesPanel);

document.querySelectorAll("[data-yolo-preset]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.yoloPreset;
    const presets = {
      default: { mode: "default", ids: "" },
      people: { mode: "custom", ids: "0" },
      people_vehicles: { mode: "custom", ids: "0,1,2,3,5,7" },
      all: { mode: "all", ids: "" },
    };
    const p = presets[key];
    if (!p) return;
    $("yolo-classes-mode").value = p.mode;
    $("yolo-classes-custom").value = p.ids;
    if (p.ids) {
      setYoloClassCheckboxes(p.ids.split(",").map((x) => parseInt(x.trim(), 10)));
    }
    toggleYoloClassesPanel();
  });
});

$("yolo-config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if ($("yolo-save-snapshots").checked && !selectedSnapshotEventTypes().length) {
    toast("Selecciona al menos un evento para guardar capturas", true);
    return;
  }
  let customIds = $("yolo-classes-custom").value.trim();
  if ($("yolo-classes-mode").value === "custom" && !customIds) {
    customIds = selectedYoloClassIds().join(",");
  }
  const payload = {
    yolo_confidence: parseFloat($("yolo-confidence").value),
    yolo_imgsz: parseInt($("yolo-imgsz").value, 10),
    detection_interval_sec: parseFloat($("yolo-interval").value),
    yolo_model: $("yolo-model").value,
    yolo_device: $("yolo-device").value,
    yolo_on_motion_only: $("yolo-on-motion-only").checked,
    save_snapshots: $("yolo-save-snapshots").checked,
    snapshot_event_types: selectedSnapshotEventTypes(),
    snapshot_cooldown_sec: parseFloat($("yolo-snapshot-cooldown").value),
    snapshot_min_persons: parseInt($("yolo-snapshot-min-persons").value, 10),
    heatmap_enabled: $("yolo-heatmap-enabled").checked,
    heatmap_opacity: parseFloat($("yolo-heatmap-opacity").value),
    heatmap_decay: parseFloat($("yolo-heatmap-decay").value),
    motion_prediction_enabled: $("yolo-prediction-enabled").checked,
    motion_threshold: parseInt($("yolo-motion-threshold").value, 10),
    min_motion_area: parseInt($("yolo-min-motion-area").value, 10),
    motion_recording_enabled: $("yolo-motion-recording").checked,
    motion_recording_duration_sec: parseFloat(
      $("yolo-motion-recording-duration").value
    ),
    motion_recording_cooldown_sec: parseFloat(
      $("yolo-motion-recording-cooldown").value
    ),
    detect_classes_mode: $("yolo-classes-mode").value,
    detect_classes_custom: customIds,
  };
  try {
    await api("PUT", "/api/admin/yolo/config", payload);
    toast("Configuración YOLO guardada (aplicada en vivo)");
    loadYoloAdmin();
  } catch (err) {
    toast(err.message, true);
  }
});

// --- Capturas ---
async function populateSnapshotCameraFilter(selected = "") {
  const cameras = await api("GET", "/api/admin/cameras");
  const sel = $("snap-filter-camera");
  sel.innerHTML =
    '<option value="">Todas</option>' +
    cameras
      .map(
        (c) =>
          `<option value="${c.id}" ${c.id === selected ? "selected" : ""}>${c.name}</option>`
      )
      .join("");
}

async function loadSnapshotConfig() {
  const cfg = await api("GET", "/api/admin/snapshots/config");
  $("snap-retention-days").value = cfg.retention_days ?? 30;
  $("snap-max-per-camera").value = cfg.max_per_camera ?? 500;
  $("snap-cleanup-interval").value = Math.round((cfg.cleanup_interval_sec ?? 3600) / 60);
}

$("snapshots-config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    retention_days: parseInt($("snap-retention-days").value, 10),
    max_per_camera: parseInt($("snap-max-per-camera").value, 10),
    cleanup_interval_sec: parseInt($("snap-cleanup-interval").value, 10) * 60,
  };
  try {
    await api("PUT", "/api/admin/snapshots/config", payload);
    toast("Retención de capturas guardada");
  } catch (err) {
    toast(err.message, true);
  }
});

$("btn-snap-cleanup").addEventListener("click", async () => {
  try {
    const res = await api("POST", "/api/admin/snapshots/cleanup");
    toast(`Limpieza: ${res.deleted} archivo(s) eliminado(s)`);
    loadSnapshotsAdmin();
  } catch (err) {
    toast(err.message, true);
  }
});

async function loadSnapshotsAdmin() {
  const cameraId = $("snap-filter-camera").value || undefined;
  const qs = cameraId ? `?camera_id=${encodeURIComponent(cameraId)}&limit=200` : "?limit=200";
  const wrap = $("snapshots-admin-table");
  try {
    const [stats, data] = await Promise.all([
      api("GET", "/api/admin/snapshots/stats"),
      api("GET", `/api/admin/snapshots${qs}`),
    ]);
    $("snap-stats").textContent = `${stats.total_files} archivo(s) · ${stats.total_size_label} total`;

    if (!data.items.length) {
      wrap.innerHTML = '<p class="muted">No hay capturas guardadas.</p>';
      return;
    }

    wrap.innerHTML = `
      <table class="table">
        <thead>
          <tr>
            <th>Vista</th><th>Cámara</th><th>Fecha</th><th>Evento</th><th>Tamaño</th><th></th>
          </tr>
        </thead>
        <tbody>
          ${data.items
            .map(
              (s) => `
            <tr>
              <td>
                <a href="${s.url}" target="_blank" rel="noopener">
                  ${
                    (s.media_type || "").toLowerCase() === "mp4"
                      ? `<video src="${s.url}" width="80" height="45" muted playsinline style="object-fit:cover;border-radius:4px"></video>`
                      : `<img src="${s.url}" alt="" width="80" height="45" style="object-fit:cover;border-radius:4px">`
                  }
                </a>
              </td>
              <td>${s.camera_name}</td>
              <td>${formatTime(s.timestamp || s.mtime)}</td>
              <td>${EVENT_LABELS[s.event_type] || s.event_type || "—"}</td>
              <td>${s.size_label}</td>
              <td class="cell-actions">
                <button class="btn btn--sm btn--danger" data-del-snap="${s.camera_id}" data-snap-name="${s.filename}">Eliminar</button>
              </td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
      <p class="muted">Mostrando ${data.items.length} de ${data.total}</p>`;

    wrap.querySelectorAll("[data-del-snap]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("¿Eliminar esta captura?")) return;
        try {
          await api(
            "DELETE",
            `/api/admin/snapshots/${btn.dataset.delSnap}/${encodeURIComponent(btn.dataset.snapName)}`
          );
          toast("Captura eliminada");
          loadSnapshotsAdmin();
        } catch (err) {
          toast(err.message, true);
        }
      });
    });
  } catch (err) {
    wrap.innerHTML = `<p class="muted">${err.message}</p>`;
  }
}

$("btn-snap-refresh").addEventListener("click", () => loadSnapshotsAdmin());
$("snap-filter-camera").addEventListener("change", () => loadSnapshotsAdmin());

loadCamerasAdmin();
loadRules();
loadHistory();
loadChannels();
loadTuyaConfig();
loadYoloAdmin();
populateSnapshotCameraFilter();
loadSnapshotConfig();
loadSnapshotsAdmin();
