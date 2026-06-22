const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { path7za } = require("7zip-bin");
const { walk } = require("./mods");

const ARCHIVE_EXTENSIONS = new Set([".zip", ".7z", ".rar"]);

function run7zip(archivePath, destination) {
  return new Promise((resolve, reject) => {
    const process = spawn(path7za, ["x", archivePath, `-o${destination}`, "-y", "-snld"], {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    });
    let output = "";
    process.stdout.on("data", (chunk) => { output += chunk; });
    process.stderr.on("data", (chunk) => { output += chunk; });
    process.once("error", reject);
    process.once("exit", (code) => code === 0 ? resolve() : reject(new Error(output.trim() || `7-Zip exit code ${code}`)));
  });
}

function validModRoots(root) {
  const result = [];
  for (const modLua of walk(root).filter((file) => path.basename(file).toLowerCase() === "mod.lua")) {
    const folder = path.dirname(modLua);
    if (fs.existsSync(path.join(folder, "res"))) result.push(folder);
  }
  return result.filter((candidate) => !result.some((other) => other !== candidate && candidate.startsWith(`${other}${path.sep}`)));
}

function safeName(value) {
  const cleaned = String(value || "mod").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/[. ]+$/, "");
  return cleaned || "mod";
}

function installFolder(source, modsRoot) {
  const target = path.join(modsRoot, safeName(path.basename(source)));
  const resolvedRoot = path.resolve(modsRoot);
  const resolvedTarget = path.resolve(target);
  if (!resolvedTarget.startsWith(`${resolvedRoot}${path.sep}`)) throw new Error("Unsicherer Installationspfad");
  fs.rmSync(resolvedTarget, { recursive: true, force: true });
  fs.cpSync(source, resolvedTarget, { recursive: true, errorOnExist: false });
  return resolvedTarget;
}

function isDownloadsFile(filePath) {
  const downloads = path.resolve(path.join(os.homedir(), "Downloads"));
  const candidate = path.resolve(filePath);
  return candidate.startsWith(`${downloads}${path.sep}`);
}

async function installInputs(inputs, modsRoot, config, onProgress = () => {}, log = () => {}) {
  if (!fs.existsSync(modsRoot) || !fs.statSync(modsRoot).isDirectory()) throw new Error("Das Mod-Verzeichnis ist ungueltig.");
  const supported = inputs.filter((input) => {
    try { return fs.statSync(input).isDirectory() || ARCHIVE_EXTENSIONS.has(path.extname(input).toLowerCase()); }
    catch { return false; }
  });
  if (!supported.length) throw new Error("Keine unterstuetzten Archive oder Ordner angegeben.");
  const installed = [];
  for (let index = 0; index < supported.length; index += 1) {
    const input = supported[index];
    onProgress(index, supported.length, `Installiere ${path.basename(input)}...`);
    let temporary = null;
    try {
      let roots;
      if (fs.statSync(input).isDirectory()) roots = validModRoots(input);
      else {
        temporary = fs.mkdtempSync(path.join(os.tmpdir(), "tpf2-mod-"));
        await run7zip(input, temporary);
        roots = validModRoots(temporary);
      }
      if (!roots.length) throw new Error(`Keine mod.lua mit res-Ordner gefunden: ${path.basename(input)}`);
      for (const root of roots) installed.push(installFolder(root, modsRoot));
      if (temporary && config.delete_download_archives_after_install && isDownloadsFile(input)) fs.rmSync(input, { force: true });
      log(`Installiert: ${path.basename(input)}`);
    } finally {
      if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
    }
    onProgress(index + 1, supported.length, `Installiert ${index + 1}/${supported.length}`);
  }
  return { installed_any: installed.length > 0, installed };
}

module.exports = { ARCHIVE_EXTENSIONS, installInputs, validModRoots };
