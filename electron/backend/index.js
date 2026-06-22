const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { shell } = require("electron");
const { installInputs } = require("./archives");
const { loadConfig, saveConfig } = require("./config");
const { translateDescriptions } = require("./deepl");
const {
  existsDirectory, findDuplicates, findPreview, removeWorkshopId,
  sanitizeMod, scanMods, scanWorkshopMods, walk
} = require("./mods");

function isWithin(candidate, root) {
  if (!root) return false;
  const resolvedCandidate = path.resolve(candidate);
  const resolvedRoot = path.resolve(root);
  return resolvedCandidate === resolvedRoot || resolvedCandidate.startsWith(`${resolvedRoot}${path.sep}`);
}

class Backend {
  constructor(dataDir, logger = console) {
    this.dataDir = dataDir;
    this.configPath = path.join(dataDir, "config.json");
    this.logger = logger;
    this.mods = [];
    this.jobs = new Map();
    this.nextJobId = 1;
    this.logs = [];
    this.previewFiles = new Map();
  }

  log(message) {
    const line = `[${new Date().toLocaleTimeString("de-CH")}] ${message}`;
    this.logs.push(line);
    this.logs = this.logs.slice(-300);
    this.logger.info?.(message);
  }

  config() { return loadConfig(this.configPath); }

  pathInfo(target) {
    if (!target) return { status: "warn", message: "Kein Mod-Verzeichnis gesetzt.", exists: false, is_dir: false, mod_count: 0 };
    if (!fs.existsSync(target)) return { status: "error", message: "Pfad wurde nicht gefunden.", exists: false, is_dir: false, mod_count: 0 };
    if (!existsDirectory(target)) return { status: "error", message: "Der Pfad ist kein Verzeichnis.", exists: true, is_dir: false, mod_count: 0 };
    const directMod = fs.existsSync(path.join(target, "mod.lua"));
    const folders = fs.readdirSync(target, { withFileTypes: true }).filter((entry) => entry.isDirectory());
    const modCount = folders.filter((folder) => walk(path.join(target, folder.name)).some((file) => path.basename(file).toLowerCase() === "mod.lua")).length;
    if (directMod) return { status: "single_mod", message: "Dieser Pfad scheint ein einzelner Mod-Ordner zu sein. Waehle dessen uebergeordneten Ordner.", exists: true, is_dir: true, mod_count: 1 };
    return { status: modCount ? "ok" : "warn", message: modCount ? "Mod-Verzeichnis erkannt." : "Keine Mods im Zielordner erkannt.", exists: true, is_dir: true, mod_count: modCount };
  }

  publicJob(job) {
    return {
      id: job.id, label: job.label, status: job.status, progress: { ...job.progress },
      result: job.result, error: job.error, cancellable: job.cancellable,
      cancel_requested: job.cancel_requested, started_at: job.started_at, finished_at: job.finished_at
    };
  }

  createJob(label, work, cancellable = false) {
    const id = String(this.nextJobId++);
    const job = {
      id, label, status: "running", progress: { current: 0, total: 1, message: label }, result: null,
      error: "", cancellable, cancel_requested: false, started_at: Date.now() / 1000, finished_at: null
    };
    this.jobs.set(id, job);
    const progress = (current, total, message) => { job.progress = { current, total: Math.max(1, total), message: message || label }; };
    setImmediate(async () => {
      try {
        job.result = await work(progress, () => job.cancel_requested);
        job.status = "done";
      } catch (error) {
        if (error?.message === "__CANCELLED__") { job.status = "cancelled"; job.error = "Vorgang abgebrochen."; }
        else { job.status = "error"; job.error = error?.message || String(error); this.log(`ERROR: ${job.error}`); }
      } finally { job.finished_at = Date.now() / 1000; }
    });
    return this.publicJob(job);
  }

  registerPreview(filePath) {
    if (!filePath) return "";
    const token = crypto.createHash("sha256").update(filePath).digest("hex");
    this.previewFiles.set(token, filePath);
    return token;
  }

  resolvePreview(token) { return this.previewFiles.get(token) || null; }

  sanitizedMods(query = "") {
    this.previewFiles.clear();
    const lower = query.trim().toLowerCase();
    return this.mods.map((mod) => {
      const sanitized = sanitizeMod(mod);
      sanitized.preview_token = this.registerPreview(sanitized.preview_path);
      delete sanitized.preview_path;
      return sanitized;
    }).filter((mod) => !lower || JSON.stringify(mod).toLowerCase().includes(lower));
  }

  safeDelete(target, roots) {
    if (!roots.some((root) => isWithin(target, root)) || roots.some((root) => path.resolve(target) === path.resolve(root))) {
      throw new Error("Loeschen ausserhalb eines konfigurierten Mod-Verzeichnisses wurde blockiert.");
    }
    if (!fs.existsSync(target)) return { ok: false, message: `Pfad nicht gefunden: ${target}` };
    fs.rmSync(target, { recursive: true, force: false });
    this.mods = this.mods.filter((mod) => path.resolve(mod.path) !== path.resolve(target));
    return { ok: true, message: `Ordner geloescht: ${path.basename(target)}` };
  }

  sanitizeMatches(matches) {
    return matches.map((match) => ({
      score: match.score, reason: match.reason, workshop_id: match.workshop_id,
      local_mod: sanitizeMod(match.local_mod), workshop_mod: sanitizeMod(match.workshop_mod)
    }));
  }

  async request(route, options = {}) {
    const url = new URL(route, "http://app.local");
    const method = String(options.method || "GET").toUpperCase();
    let payload = {};
    if (options.body) payload = typeof options.body === "string" ? JSON.parse(options.body) : options.body;
    const config = this.config();

    if (method === "GET" && url.pathname === "/api/config") return { config };
    if (method === "POST" && url.pathname === "/api/config") return { config: saveConfig(this.configPath, { ...config, ...payload }) };
    if (method === "GET" && url.pathname === "/api/path-info") return { info: this.pathInfo(url.searchParams.get("path") || "") };
    if (method === "GET" && url.pathname === "/api/mods") {
      const mods = this.sanitizedMods(url.searchParams.get("q") || "");
      return { mods, count: mods.length };
    }
    if (method === "GET" && url.pathname === "/api/logs") return { logs: [...this.logs] };
    if (method === "GET" && url.pathname.startsWith("/api/jobs/")) {
      const id = decodeURIComponent(url.pathname.split("/")[3] || "");
      const job = this.jobs.get(id);
      if (!job) throw new Error("Job nicht gefunden");
      return { job: this.publicJob(job) };
    }
    if (method === "POST" && url.pathname === "/api/scan") {
      return { job: this.createJob("Scan", async (progress, cancelled) => {
        if (!existsDirectory(config.mods_path)) throw new Error("Das Mod-Verzeichnis existiert nicht oder ist ungueltig.");
        this.log(`Scan gestartet: ${config.mods_path}`);
        this.mods = await scanMods(config.mods_path, config.language, config.fallback_language, progress, cancelled);
        await translateDescriptions(this.mods, config, progress);
        this.log(`Scan abgeschlossen: ${this.mods.length} Mods`);
        return { mods_count: this.mods.length };
      }) };
    }
    if (method === "POST" && url.pathname === "/api/install") {
      return { job: this.createJob("Installation", async (progress) => {
        const result = await installInputs(payload.paths || [], config.mods_path, config, progress, (line) => this.log(line));
        this.mods = await scanMods(config.mods_path, config.language, config.fallback_language);
        return result;
      }) };
    }
    if (method === "POST" && url.pathname === "/api/duplicates") {
      return { job: this.createJob("Duplikat-Scan", async (progress, cancelled) => {
        if (!existsDirectory(config.mods_path) || !existsDirectory(config.workshop_mods_path)) throw new Error("Lokales oder Workshop-Mod-Verzeichnis ist ungueltig.");
        const local = await scanMods(config.mods_path, config.language, config.fallback_language, progress, cancelled);
        const workshop = await scanWorkshopMods(config.workshop_mods_path, config.appworkshop_path, config.language, config.fallback_language, progress, cancelled);
        const matches = await findDuplicates(local, workshop, progress, cancelled);
        return { matches: this.sanitizeMatches(matches), matches_count: matches.length };
      }, true) };
    }
    if (method === "POST" && /^\/api\/jobs\/[^/]+\/cancel$/.test(url.pathname)) {
      const id = decodeURIComponent(url.pathname.split("/")[3]);
      const job = this.jobs.get(id);
      if (!job) throw new Error("Job nicht gefunden");
      if (job.cancellable && job.status === "running") job.cancel_requested = true;
      return { job: this.publicJob(job) };
    }
    if (method === "POST" && url.pathname === "/api/open") {
      const error = await shell.openPath(String(payload.path || ""));
      return { ok: !error, message: error || "Pfad geoeffnet" };
    }
    if (method === "POST" && url.pathname === "/api/delete") {
      return this.safeDelete(String(payload.path || ""), [config.mods_path]);
    }
    if (method === "POST" && url.pathname === "/api/duplicate-action") {
      const action = String(payload.action || "");
      const match = payload.match || {};
      if (action === "delete_local") return this.safeDelete(String(match.local_mod?.path || ""), [config.mods_path]);
      if (action === "delete_workshop") {
        const result = this.safeDelete(String(match.workshop_mod?.path || ""), [config.workshop_mods_path]);
        if (result.ok) removeWorkshopId(config.appworkshop_path, String(match.workshop_id || match.workshop_mod?.workshop_id || ""));
        return result;
      }
      throw new Error("Unbekannte Duplikat-Aktion");
    }
    throw new Error(`Unbekannter Backend-Aufruf: ${method} ${url.pathname}`);
  }
}

module.exports = { Backend, isWithin };
