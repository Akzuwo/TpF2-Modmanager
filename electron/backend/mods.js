const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { extractBalancedBlock, parseModLua } = require("./lua");

const PREVIEW_SUFFIXES = [".tga", ".dds", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"];
const TRACKED_SUFFIXES = new Set([".lua", ".mdl", ".msh", ".mtl", ".con", ".lua5", ".png", ".dds", ".tga"]);

function existsDirectory(target) {
  try { return fs.statSync(target).isDirectory(); } catch { return false; }
}

function walk(root) {
  if (!existsDirectory(root)) return [];
  const result = [];
  const pending = [root];
  while (pending.length) {
    const current = pending.pop();
    let entries = [];
    try { entries = fs.readdirSync(current, { withFileTypes: true }); } catch { continue; }
    for (const entry of entries) {
      const item = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(item);
      else if (entry.isFile()) result.push(item);
    }
  }
  return result;
}

function findBestModLua(root) {
  return walk(root)
    .filter((file) => path.basename(file).toLowerCase() === "mod.lua")
    .sort((left, right) => left.split(path.sep).length - right.split(path.sep).length)[0] || null;
}

function fallbackMod(folder, modLua = path.join(folder, "mod.lua")) {
  return {
    id: path.basename(folder), name: path.basename(folder), author: "Fehler beim Lesen", version: "-",
    path: folder, mod_lua: modLua, description: "", description_translated: "", deepl_error: "",
    raw_fields: {}, resolved_fields: {}, translation_available_languages: [],
    translation_effective_language: "", translation_notice: "", dependencies: [],
    dependency_links: [], required_by: []
  };
}

function resolveDependencies(mods) {
  const byId = new Map(mods.filter((mod) => mod.id).map((mod) => [mod.id, mod]));
  for (const mod of mods) {
    mod.required_by = [];
    mod.dependency_links = (mod.dependencies || []).map((raw) => {
      const id = String(raw).split(/\s+/)[0];
      return { raw, id, target: byId.get(id) || null };
    });
  }
  for (const mod of mods) {
    for (const dependency of mod.dependency_links) {
      if (dependency.target) dependency.target.required_by.push(mod);
    }
  }
  return mods;
}

async function scanMods(root, primaryLanguage, fallbackLanguage, onProgress = () => {}, isCancelled = () => false) {
  if (!existsDirectory(root)) return [];
  const folders = fs.readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(root, entry.name))
    .sort((left, right) => left.localeCompare(right));
  const mods = [];
  onProgress(0, folders.length, "Scanne Mod-Ordner...");
  for (let index = 0; index < folders.length; index += 1) {
    if (isCancelled()) throw new Error("__CANCELLED__");
    const folder = folders[index];
    const modLua = findBestModLua(folder);
    if (modLua) {
      try { mods.push(parseModLua(modLua, primaryLanguage, fallbackLanguage)); }
      catch { mods.push(fallbackMod(folder, modLua)); }
    }
    onProgress(index + 1, folders.length, `Scanne Mod-Ordner ${index + 1}/${folders.length}`);
    if (index % 20 === 0) await new Promise((resolve) => setImmediate(resolve));
  }
  resolveDependencies(mods);
  return mods.sort((left, right) => left.name.localeCompare(right.name));
}

function findPreview(modPath) {
  const files = walk(modPath).filter((file) => path.parse(file).name.toLowerCase() === "image_00");
  return files
    .filter((file) => PREVIEW_SUFFIXES.includes(path.extname(file).toLowerCase()))
    .sort((left, right) => {
      const depth = path.relative(modPath, left).split(path.sep).length - path.relative(modPath, right).split(path.sep).length;
      return depth || PREVIEW_SUFFIXES.indexOf(path.extname(left).toLowerCase()) - PREVIEW_SUFFIXES.indexOf(path.extname(right).toLowerCase());
    })[0] || null;
}

function findModLink(fields = {}) {
  for (const key of ["url", "website", "web", "forum", "source", "steamUrl", "workshopUrl"]) {
    const value = String(fields[key] || "").trim();
    if (/^https?:\/\//.test(value)) return value;
  }
  if (/^\d+$/.test(String(fields.steamId || ""))) return `https://steamcommunity.com/sharedfiles/filedetails/?id=${fields.steamId}`;
  return Object.values(fields).map(String).join(" ").match(/https?:\/\/[^\s"']+/)?.[0] || "";
}

function sanitizeMod(mod) {
  return {
    id: mod.id || "", name: mod.name || "", author: mod.author || "", version: mod.version || "",
    path: mod.path || "", mod_lua: mod.mod_lua || "",
    description: mod.description_translated || mod.description || "", source_description: mod.description || "",
    translation_notice: mod.translation_notice || "", deepl_error: mod.deepl_error || "",
    available_languages: mod.translation_available_languages || [],
    effective_language: mod.translation_effective_language || "",
    link: findModLink(mod.resolved_fields || mod.raw_fields),
    has_preview: Boolean(findPreview(mod.path)),
    preview_path: findPreview(mod.path) || "",
    dependencies: mod.dependencies || [],
    dependency_links: (mod.dependency_links || []).map((dependency) => ({
      raw: dependency.raw || "", id: dependency.id || "",
      target_name: dependency.target?.name || "", target_path: dependency.target?.path || "",
      missing: !dependency.target
    })),
    required_by: (mod.required_by || []).map((item) => ({ name: item.name || "", id: item.id || "", path: item.path || "" })),
    resolved_fields: mod.resolved_fields || {}, raw_fields: mod.raw_fields || {},
    workshop_id: mod.workshop_id || "", source: mod.source || "local"
  };
}

function parseWorkshopIds(acfPath) {
  if (!acfPath || !fs.existsSync(acfPath)) return [];
  const matches = [...fs.readFileSync(acfPath, "utf8").matchAll(/"(\d{6,})"\s*\{/g)].map((match) => match[1]);
  return [...new Set(matches)].sort();
}

async function scanWorkshopMods(root, acfPath, primary, fallback, onProgress, isCancelled) {
  if (!existsDirectory(root)) return [];
  let ids = parseWorkshopIds(acfPath);
  if (!ids.length) ids = fs.readdirSync(root, { withFileTypes: true }).filter((entry) => entry.isDirectory() && /^\d+$/.test(entry.name)).map((entry) => entry.name);
  const mods = [];
  for (let index = 0; index < ids.length; index += 1) {
    if (isCancelled()) throw new Error("__CANCELLED__");
    const id = ids[index];
    const direct = path.join(root, id);
    const folder = existsDirectory(direct) ? direct : path.join(root, `content_${id}`);
    if (!existsDirectory(folder)) continue;
    const modLua = findBestModLua(folder);
    let mod;
    try { mod = modLua ? parseModLua(modLua, primary, fallback) : fallbackMod(folder); }
    catch { mod = fallbackMod(folder, modLua || undefined); }
    mod.workshop_id = id;
    mod.source = "workshop";
    mods.push(mod);
    onProgress(index + 1, ids.length, `Scanne Workshop-Mods ${index + 1}/${ids.length}`);
    if (index % 20 === 0) await new Promise((resolve) => setImmediate(resolve));
  }
  return resolveDependencies(mods);
}

function normalized(value) { return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); }
function tokens(value) { return new Set(normalized(value).split(" ").filter((token) => token.length >= 3)); }
function intersection(left, right) { return [...left].filter((item) => right.has(item)).length; }
function overlap(left, right) { return left.size && right.size ? intersection(left, right) / Math.min(left.size, right.size) : 0; }
function jaccard(left, right) { const union = new Set([...left, ...right]); return union.size ? intersection(left, right) / union.size : 0; }

function levenshtein(left, right) {
  if (left === right) return 1;
  if (!left || !right) return 0;
  const row = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let i = 1; i <= left.length; i += 1) {
    let previous = row[0]; row[0] = i;
    for (let j = 1; j <= right.length; j += 1) {
      const old = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, previous + (left[i - 1] === right[j - 1] ? 0 : 1));
      previous = old;
    }
  }
  return 1 - row[right.length] / Math.max(left.length, right.length);
}

function signature(mod) {
  if (mod._signature) return mod._signature;
  const relative = new Set(walk(mod.path).map((file) => path.relative(mod.path, file).replaceAll("\\", "/").toLowerCase()));
  const tracked = new Set([...relative].filter((file) => TRACKED_SUFFIXES.has(path.extname(file))));
  const names = new Set([...tracked].map((file) => path.basename(file)));
  const directories = new Set([...relative].map((file) => path.dirname(file)).filter((folder) => folder !== "."));
  const seed = [...relative].sort().join("\n");
  mod._signature = {
    folder: normalized(path.basename(mod.path)), name: normalized(mod.name), author: normalized(mod.author),
    folderTokens: tokens(path.basename(mod.path)), nameTokens: tokens(mod.name), tracked, names, directories,
    hash: seed ? crypto.createHash("sha1").update(seed).digest("hex") : ""
  };
  return mod._signature;
}

function scoreMatch(localMod, workshopMod) {
  const left = signature(localMod); const right = signature(workshopMod);
  const folder = levenshtein(left.folder, right.folder);
  const name = levenshtein(left.name, right.name);
  const author = levenshtein(left.author, right.author);
  const paths = overlap(left.tracked, right.tracked);
  const assets = overlap(left.names, right.names);
  const structure = Math.max(jaccard(left.directories, right.directories), left.hash && left.hash === right.hash ? 1 : 0);
  const score = folder * 12 + name * 22 + author * 8 + structure * 18 + paths * 28 + assets * 12;
  const reasons = [];
  if (paths >= 0.6) reasons.push(`${Math.round(paths * 100)}% gleiche Asset-/Dateipfade`);
  if (assets >= 0.6) reasons.push(`${Math.round(assets * 100)}% gleiche markante Dateien`);
  if (name >= 0.8) reasons.push("Modname sehr aehnlich");
  if (folder >= 0.8) reasons.push("Ordnername sehr aehnlich");
  if (author >= 0.8 && left.author) reasons.push("Autor stimmt weitgehend ueberein");
  return { local_mod: localMod, workshop_mod: workshopMod, workshop_id: workshopMod.workshop_id || "", score: Math.round(score * 10) / 10, reason: reasons.slice(0, 3).join("; ") || "Mehrere Metadaten- und Dateimerkmale stimmen ueberein" };
}

async function findDuplicates(localMods, workshopMods, onProgress, isCancelled) {
  const best = new Map();
  const total = localMods.length * workshopMods.length;
  let current = 0;
  for (const localMod of localMods) {
    for (const workshopMod of workshopMods) {
      if (isCancelled()) throw new Error("__CANCELLED__");
      const result = scoreMatch(localMod, workshopMod);
      if (result.score >= 45 && (!best.has(localMod.path) || best.get(localMod.path).score < result.score)) best.set(localMod.path, result);
      current += 1;
      onProgress(current, total, `Vergleiche Mods ${current}/${total}`);
      if (current % 50 === 0) await new Promise((resolve) => setImmediate(resolve));
    }
  }
  return [...best.values()].sort((left, right) => right.score - left.score);
}

function removeWorkshopId(acfPath, workshopId) {
  if (!acfPath || !fs.existsSync(acfPath) || !workshopId) return false;
  let text = fs.readFileSync(acfPath, "utf8");
  const pattern = new RegExp(`\\s*"${workshopId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"\\s*\\{`);
  let changed = false;
  let match;
  while ((match = pattern.exec(text))) {
    const open = text.indexOf("{", match.index);
    const block = extractBalancedBlock(text, open);
    text = text.slice(0, match.index) + text.slice(open + block.length);
    changed = true;
  }
  if (changed) fs.writeFileSync(acfPath, text, "utf8");
  return changed;
}

module.exports = {
  existsDirectory, findDuplicates, findPreview, removeWorkshopId, resolveDependencies,
  sanitizeMod, scanMods, scanWorkshopMods, walk
};
