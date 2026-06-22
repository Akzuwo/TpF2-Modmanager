const state = {
  config: {},
  mods: [],
  selectedPath: "",
  currentJob: null,
  currentJobCancellable: false,
  duplicateMatches: [],
  pathInfoTimer: null,
};

const $ = (id) => document.getElementById(id);
const shell = window.desktopShell || null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

function notify(message, type = "info", timeout = 4200) {
  const host = $("toastHost");
  if (!host) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <strong>${escapeHtml(type === "error" ? "Fehler" : type === "success" ? "Fertig" : type === "warn" ? "Hinweis" : "Info")}</strong>
    <span>${escapeHtml(message)}</span>
  `;
  host.appendChild(toast);
  window.setTimeout(() => {
    toast.classList.add("leaving");
    window.setTimeout(() => toast.remove(), 220);
  }, timeout);
}

function showError(error, fallback = "Aktion fehlgeschlagen") {
  notify(error?.message || String(error || fallback), "error", 6500);
}

function runAction(action) {
  return (...args) => {
    Promise.resolve(action(...args)).catch((error) => showError(error));
  };
}

function switchView(name) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  document.querySelectorAll(".rail-button").forEach((button) => button.classList.remove("active"));
  $(`${name}View`).classList.add("active");
  document.querySelector(`[data-view="${name}"]`).classList.add("active");
}

function applyTheme(theme) {
  const isDark = theme === "dark";
  document.documentElement.classList.toggle("dark", isDark);
  localStorage.setItem("tpf2-theme", isDark ? "dark" : "light");
  $("themeToggle").textContent = isDark ? "☀" : "◐";
}

function initTheme() {
  const saved = localStorage.getItem("tpf2-theme");
  const preferred = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  applyTheme(saved || preferred);
}

function openSettingsModal() {
  $("settingsModal").classList.remove("hidden");
  $("closeSettings").focus();
}

function closeSettingsModal() {
  $("settingsModal").classList.add("hidden");
}

function setConfigForm(config) {
  state.config = config;
  $("modsPath").value = config.mods_path || "";
  for (const key of [
    "app_language",
    "language",
    "fallback_language",
    "workshop_mods_path",
    "appworkshop_path",
    "deepl_api_key",
    "max_parallel_workers",
  ]) {
    if ($(key)) $(key).value = config[key] ?? "";
  }
  for (const key of ["parallel_install_enabled", "delete_download_archives_after_install", "debug_logging_enabled"]) {
    if ($(key)) $(key).checked = Boolean(config[key]);
  }
}

function collectConfig() {
  return {
    mods_path: $("modsPath").value.trim(),
    app_language: $("app_language").value,
    language: $("language").value,
    fallback_language: $("fallback_language").value,
    workshop_mods_path: $("workshop_mods_path").value.trim(),
    appworkshop_path: $("appworkshop_path").value.trim(),
    deepl_api_key: $("deepl_api_key").value,
    max_parallel_workers: Number($("max_parallel_workers").value || 2),
    parallel_install_enabled: $("parallel_install_enabled").checked,
    delete_download_archives_after_install: $("delete_download_archives_after_install").checked,
    debug_logging_enabled: $("debug_logging_enabled").checked,
  };
}

async function saveConfig(partial = null) {
  const payload = partial || collectConfig();
  const { config } = await api("/api/config", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  setConfigForm(config);
  await refreshPathInfo();
  notify("Einstellungen gespeichert.", "success");
  if (!partial) closeSettingsModal();
  return config;
}

function setPathStatus(info) {
  const status = $("pathStatus");
  if (!status) return;
  status.className = `path-status ${info.status || "warn"}`;
  const count = Number(info.mod_count || 0);
  const suffix = count ? ` Scan-Ziel: ${count} Mods.` : "";
  status.textContent = `${info.message || "Pfad ungeprueft."}${suffix}`;
}

async function refreshPathInfo(path = $("modsPath")?.value || "") {
  const { info } = await api(`/api/path-info?path=${encodeURIComponent(path.trim())}`);
  setPathStatus(info);
  return info;
}

function queuePathInfoRefresh() {
  window.clearTimeout(state.pathInfoTimer);
  state.pathInfoTimer = window.setTimeout(() => {
    refreshPathInfo().catch((error) => showError(error, "Pfad konnte nicht geprueft werden"));
  }, 350);
}

function renderMods() {
  const tbody = $("modsTable");
  tbody.textContent = "";
  $("modCount").textContent = state.mods.length;
  if (!state.mods.length) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td colspan="4">
        <div class="table-empty">
          <strong>Noch keine Mods geladen</strong>
          <span>Waehle oben dein Transport Fever 2 Mod-Verzeichnis aus. Danach startet der Scan automatisch oder du klickst auf Scannen.</span>
        </div>
      </td>
    `;
    tbody.appendChild(row);
    return;
  }
  for (const mod of state.mods) {
    const row = document.createElement("tr");
    row.className = mod.path === state.selectedPath ? "selected" : "";
    row.innerHTML = `
      <td>${escapeHtml(mod.name || "-")}</td>
      <td>${escapeHtml(mod.author || "-")}</td>
      <td>${escapeHtml(mod.version || "-")}</td>
      <td class="path">${escapeHtml(mod.path || "-")}</td>
    `;
    row.addEventListener("click", () => selectMod(mod.path));
    tbody.appendChild(row);
  }
}

function selectMod(path) {
  state.selectedPath = path;
  const mod = state.mods.find((item) => item.path === path);
  renderMods();
  renderDetails(mod);
}

function renderDetails(mod) {
  const panel = $("detailPanel");
  if (!mod) {
    panel.innerHTML = `
      <div class="empty-state">
        <div class="empty-mark">▦</div>
        <h3>Keine Mod ausgewaehlt</h3>
        <p class="muted">Waehle eine Zeile aus, um Beschreibung, Abhaengigkeiten und Rohfelder zu sehen.</p>
      </div>`;
    return;
  }

  const deps = mod.dependency_links?.length
    ? mod.dependency_links
        .map((dep) => `${escapeHtml(dep.id)}${dep.missing ? " (fehlt)" : ` -> ${escapeHtml(dep.target_name)}`}`)
        .join("<br>")
    : "-";
  const requiredBy = mod.required_by?.length ? mod.required_by.map((item) => escapeHtml(item.name || item.id)).join("<br>") : "-";
  const fieldRows = Object.keys(mod.resolved_fields || {})
    .sort((left, right) => left.localeCompare(right))
    .map((key) => {
      const resolved = mod.resolved_fields?.[key] ?? "";
      const raw = mod.raw_fields?.[key] ?? "";
      return `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(resolved)}</td><td>${escapeHtml(raw)}</td></tr>`;
    })
    .join("");
  const preview = mod.has_preview ? `<img class="preview-image" src="/api/preview?path=${encodeURIComponent(mod.path)}" alt="">` : "";
  const link = mod.link ? `<button id="openLink" data-tooltip="Steam Workshop-Seite im Browser oeffnen">Workshop/Link oeffnen</button>` : "";
  const languages = mod.available_languages?.length ? mod.available_languages.join(", ") : "-";

  panel.innerHTML = `
    ${preview}
    <h3>${escapeHtml(mod.name || "-")}</h3>
    <div class="detail-actions">
      <button id="openSelected" data-tooltip="Mod-Ordner im Datei-Explorer oeffnen">Ordner oeffnen</button>
      ${link}
      <button id="deleteSelected" class="danger" data-tooltip="Diese Mod von der Festplatte loeschen">Loeschen</button>
    </div>
    <dl>
      <dt>Autor</dt><dd>${escapeHtml(mod.author || "-")}</dd>
      <dt>Version</dt><dd>${escapeHtml(mod.version || "-")}</dd>
      <dt>Pfad</dt><dd>${escapeHtml(mod.path || "-")}</dd>
      <dt>Beschreibung</dt><dd>${escapeHtml(mod.description || "-")}</dd>
      <dt>Uebersetzung</dt><dd>${escapeHtml(mod.translation_notice || mod.deepl_error || "-")}</dd>
      <dt>Sprachen</dt><dd>${escapeHtml(languages)} | aktiv: ${escapeHtml(mod.effective_language || "-")}</dd>
      <dt>Dependencies</dt><dd>${deps}</dd>
      <dt>Wird benoetigt von</dt><dd>${requiredBy}</dd>
    </dl>
    <div class="field-table">
      <table>
        <thead><tr><th>Feld</th><th>Wert</th><th>Rohwert</th></tr></thead>
        <tbody>${fieldRows || `<tr><td colspan="3">Keine Rohfelder verfuegbar</td></tr>`}</tbody>
      </table>
    </div>
  `;
  $("openSelected").addEventListener("click", () => openPath(mod.path));
  if ($("openLink")) $("openLink").addEventListener("click", () => openExternal(mod.link));
  $("deleteSelected").addEventListener("click", () => deleteMod(mod));
}

async function refreshMods() {
  const query = encodeURIComponent($("search").value.trim());
  const { mods } = await api(`/api/mods?q=${query}`);
  state.mods = mods;
  if (!state.mods.some((mod) => mod.path === state.selectedPath)) {
    state.selectedPath = "";
    renderDetails(null);
  }
  renderMods();
}

async function startJob(endpoint, body = {}) {
  const { job } = await api(endpoint, {
    method: "POST",
    body: JSON.stringify(body),
  });
  state.currentJob = job.id;
  state.currentJobCancellable = Boolean(job.cancellable);
  $("cancelJob").classList.toggle("hidden", !state.currentJobCancellable);
  $("jobPanel").classList.remove("hidden");
  notify(`${job.label} gestartet.`, "info", 2600);
  pollJob(job.id);
}

async function scanCurrentPath() {
  const info = await refreshPathInfo();
  if (!info.exists || !info.is_dir) {
    notify(info.message || "Bitte zuerst einen gueltigen Mod-Ordner setzen.", "warn");
    return;
  }
  if (info.status === "single_mod") {
    notify(info.message, "warn");
    return;
  }
  await saveConfig({ mods_path: $("modsPath").value.trim() });
  await startJob("/api/scan");
}

async function pollJob(jobId) {
  const { job } = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
  const progress = job.progress || { current: 0, total: 1, message: "" };
  $("jobLabel").textContent = job.label;
  $("jobMessage").textContent = progress.message || "";
  $("jobProgress").max = progress.total || 1;
  $("jobProgress").value = progress.current || 0;
  $("cancelJob").classList.toggle("hidden", !(job.cancellable && job.status === "running"));

  if (job.status === "running") {
    setTimeout(() => pollJob(jobId), 500);
    return;
  }

  state.currentJob = null;
  state.currentJobCancellable = false;
  if (job.status === "error") {
    notify(job.error || "Job fehlgeschlagen", "error", 7000);
  }
  if (job.status === "cancelled") {
    $("jobMessage").textContent = "Abgebrochen";
    notify(`${job.label} abgebrochen.`, "warn");
  }
  if (job.label === "Scan" || job.label === "Installation") {
    await refreshMods();
    await refreshPathInfo();
  }
  if (job.label === "Duplikat-Scan") {
    if (job.status !== "cancelled") showDuplicateResult(job.result?.matches || []);
  }
  if (job.status === "done") {
    if (job.label === "Scan") notify(`Scan abgeschlossen: ${state.mods.length} Mods geladen.`, "success");
    else if (job.label === "Installation") notify("Installation abgeschlossen.", "success");
    else if (job.label === "Duplikat-Scan") notify("Duplikat-Scan abgeschlossen.", "success");
  }
  setTimeout(() => $("jobPanel").classList.add("hidden"), 1200);
  refreshLogs();
}

async function cancelCurrentJob() {
  if (!state.currentJob || !state.currentJobCancellable) return;
  $("cancelJob").disabled = true;
  try {
    await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  } finally {
    $("cancelJob").disabled = false;
  }
}

function showDuplicateResult(matches) {
  const panel = $("detailPanel");
  state.duplicateMatches = matches;
  switchView("mods");
  if (!matches.length) {
    panel.innerHTML = `<h3>Keine Duplikate gefunden</h3><p class="muted">Der Vergleich hat keine passenden lokalen und Workshop-Mods gefunden.</p>`;
    return;
  }
  panel.innerHTML = `<h3>Duplikate</h3>${matches
    .map(
      (match) => `
      <div class="duplicate">
        <strong>${escapeHtml(match.local_mod.name)}</strong><br>
        <span class="muted">${escapeHtml(match.workshop_mod.name)} | ${match.score}%</span><br>
        <small>${escapeHtml(match.reason)}</small>
        <div class="duplicate-actions">
          <button data-duplicate-action="delete_local" data-index="${state.duplicateMatches.indexOf(match)}" data-tooltip="Die manuell installierte lokale Version loeschen">Lokale Mod loeschen</button>
          <button data-duplicate-action="delete_workshop" data-index="${state.duplicateMatches.indexOf(match)}" data-tooltip="Die Steam Workshop-Version deabonnieren und loeschen">Workshop-Mod loeschen</button>
          <button data-duplicate-action="skip" data-index="${state.duplicateMatches.indexOf(match)}" data-tooltip="Dieses Duplikat-Paar ignorieren">Ueberspringen</button>
        </div>
      </div>`
    )
    .join("")}`;
  panel.querySelectorAll("[data-duplicate-action]").forEach((button) => {
    button.addEventListener("click", () => applyDuplicateAction(Number(button.dataset.index), button.dataset.duplicateAction));
  });
}

async function openPath(path) {
  const result = await api("/api/open", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
  if (!result.ok) notify(result.message || "Ordner konnte nicht geoeffnet werden", "error");
}

async function openExternal(url) {
  if (!url) return;
  if (shell?.openExternal) {
    await shell.openExternal(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

async function applyDuplicateAction(index, action) {
  const match = state.duplicateMatches[index];
  if (!match || action === "skip") {
    state.duplicateMatches.splice(index, 1);
    showDuplicateResult(state.duplicateMatches);
    return;
  }
  const label = action === "delete_local" ? "lokale Mod loeschen" : "Workshop-Mod loeschen/deabonnieren";
  if (!confirm(`${label}?\n\n${match.local_mod.name}\n${match.workshop_mod.name}`)) return;
  const result = await api("/api/duplicate-action", {
    method: "POST",
    body: JSON.stringify({ match, action }),
  });
  if (!result.ok) {
    notify(result.message || "Aktion fehlgeschlagen", "error");
    return;
  }
  state.duplicateMatches.splice(index, 1);
  await refreshMods();
  showDuplicateResult(state.duplicateMatches);
}

async function deleteMod(mod) {
  const blockers = mod.required_by?.map((item) => item.name || item.id).filter(Boolean) || [];
  const extra = blockers.length ? `\n\nDiese Mod wird benoetigt von:\n${blockers.join(", ")}` : "";
  if (!confirm(`Mod wirklich loeschen?\n\n${mod.name}${extra}`)) return;
  const result = await api("/api/delete", {
    method: "POST",
    body: JSON.stringify({ path: mod.path }),
  });
  if (!result.ok) {
    notify(result.message || "Loeschen fehlgeschlagen", "error");
  }
  await refreshMods();
}

async function refreshLogs() {
  const { logs } = await api("/api/logs");
  $("logs").textContent = logs.join("\n");
}

async function pickFirst(picker) {
  if (!shell?.[picker]) return "";
  const paths = await shell[picker]();
  return paths?.[0] || "";
}

async function installPaths(paths) {
  if (!paths?.length) {
    notify("Keine Dateien oder Ordner erhalten.", "warn");
    return;
  }
  const info = await refreshPathInfo();
  if (!info.exists || !info.is_dir || info.status === "single_mod") {
    notify("Setze zuerst oben den Ziel-Mod-Ordner.", "warn");
    return;
  }
  await startJob("/api/install", { paths });
}

function bindDropZone(dropZone, onPaths) {
  if (!dropZone) return;
  for (const eventName of ["dragenter", "dragover"]) {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("drag-active");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove("drag-active"));
  }
  dropZone.addEventListener("drop", runAction(async (event) => {
    event.preventDefault();
    const files = [...event.dataTransfer.files];
    const paths = [];
    for (const file of files) {
      const path = shell?.getPathForFile ? shell.getPathForFile(file) : file.path;
      if (path) paths.push(path);
    }
    if (!paths.length) {
      notify("Drag and Drop hat keine lokalen Pfade geliefert. Bitte den Auswahl-Button nutzen.", "warn", 6500);
      return;
    }
    await onPaths(paths);
  }));
}

function initDropZones() {
  bindDropZone($("mainDropZone"), installPaths);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function init() {
  initTheme();
  document.querySelectorAll(".rail-button").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  $("themeToggle").addEventListener("click", () => {
    applyTheme(document.documentElement.classList.contains("dark") ? "light" : "dark");
  });
  $("openSettings").addEventListener("click", openSettingsModal);
  $("closeSettings").addEventListener("click", closeSettingsModal);
  $("cancelSettings").addEventListener("click", closeSettingsModal);
  $("settingsBackdrop").addEventListener("click", closeSettingsModal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSettingsModal();
  });
  $("browseModsPath").addEventListener("click", runAction(async () => {
    const path = await pickFirst("pickModsFolder");
    if (path) {
      $("modsPath").value = path;
      await scanCurrentPath();
    }
  }));
  $("browseWorkshopPath").addEventListener("click", runAction(async () => {
    const path = await pickFirst("pickWorkshopFolder");
    if (path) $("workshop_mods_path").value = path;
  }));
  $("browseAppWorkshopPath").addEventListener("click", runAction(async () => {
    const path = await pickFirst("pickAppWorkshopFile");
    if (path) $("appworkshop_path").value = path;
  }));
  $("browseMainInstallInputs").addEventListener("click", runAction(async () => {
    if (!shell?.pickInstallInputs) {
      notify("Dateiauswahl ist nur in der Desktop-App verfuegbar.", "warn");
      return;
    }
    await installPaths(await shell.pickInstallInputs());
  }));
  initDropZones();
  $("modsPath").addEventListener("input", queuePathInfoRefresh);
  $("savePath").addEventListener("click", runAction(async () => {
    await saveConfig({ mods_path: $("modsPath").value.trim() });
  }));
  $("scan").addEventListener("click", runAction(async () => {
    await scanCurrentPath();
  }));
  $("search").addEventListener("input", runAction(refreshMods));
  $("duplicates").addEventListener("click", runAction(() => startJob("/api/duplicates")));
  $("saveSettings").addEventListener("click", runAction(() => saveConfig()));
  $("cancelJob").addEventListener("click", runAction(cancelCurrentJob));
  $("refreshLogs").addEventListener("click", runAction(refreshLogs));

  const { config } = await api("/api/config");
  setConfigForm(config);
  await refreshPathInfo(config.mods_path || "");
  await refreshMods();
  await refreshLogs();
}

init().catch((error) => showError(error, "Start fehlgeschlagen"));
