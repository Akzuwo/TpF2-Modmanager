const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const test = require("node:test");
const { path7za } = require("7zip-bin");

const { Backend } = require("../electron/backend");
const { installInputs } = require("../electron/backend/archives");
const { loadConfig, saveConfig } = require("../electron/backend/config");
const { endpointForKey, translateText } = require("../electron/backend/deepl");
const { decodeDds, decodeTga, encodePng, previewBytes } = require("../electron/backend/image");
const { parseModLua, parseStringsLua } = require("../electron/backend/lua");
const { findPreview, sanitizeMod, scanMods } = require("../electron/backend/mods");

function temporaryDirectory(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "tpf2-js-test-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return directory;
}

function createMod(root, folder, body, strings = "") {
  const directory = path.join(root, folder);
  fs.mkdirSync(path.join(directory, "res"), { recursive: true });
  fs.writeFileSync(path.join(directory, "mod.lua"), body, "utf8");
  if (strings) fs.writeFileSync(path.join(directory, "strings.lua"), strings, "utf8");
  return directory;
}

test("config keeps defaults and known values", (t) => {
  const file = path.join(temporaryDirectory(t), "config.json");
  saveConfig(file, { mods_path: "C:/mods", unknown: true, max_parallel_workers: 99 });
  const config = loadConfig(file);
  assert.equal(config.mods_path, "C:/mods");
  assert.equal(config.language, "de");
  assert.equal(config.max_parallel_workers, 16);
  assert.equal(Object.hasOwn(config, "unknown"), false);
});

test("Lua parser resolves translations, author, version and dependencies", (t) => {
  const root = temporaryDirectory(t);
  const directory = createMod(root, "sample_1", `
    function data()
      return { info = {
        name = _("mod_name"),
        description = _("mod_desc"),
        authors = { { name = "Ada" } },
        majorVersion = 2,
        minorVersion = 5,
        dependencies = { "base_mod_1", "track_mod_2 >= 1" },
        steamId = "123456789"
      } }
    end
  `, `
    local title = "Beispiel"
    return {
      de = { mod_name = title, mod_desc = "Beschreibung" },
      en = { mod_name = "Example", mod_desc = "Description" }
    }
  `);
  const parsedStrings = parseStringsLua(path.join(directory, "strings.lua"));
  assert.equal(parsedStrings.languages.de.mod_name, "Beispiel");
  const mod = parseModLua(path.join(directory, "mod.lua"), "de", "en");
  assert.equal(mod.name, "Beispiel");
  assert.equal(mod.description, "Beschreibung");
  assert.equal(mod.author, "Ada");
  assert.equal(mod.version, "2.5");
  assert.deepEqual(mod.dependencies, ["base_mod_1", "track_mod_2 >= 1"]);
});

test("strings.lua parser handles key-first, named tables and extended Lua strings", (t) => {
  const root = temporaryDirectory(t);
  const file = path.join(root, "strings.lua");
  fs.writeFileSync(file, `
    --[=[ a block comment containing { braces } ]=]
    local english = {
      mod_name = "Stormy morning",
      mod_desc = [=[Line one,
Line two]=],
    }
    local payload = {
      en = english,
      mod_name = { de = "St\\195\\188rmischer Morgen", fr = "Matin orageux" },
      mod_desc = { de = [==[Zeile eins,
Zeile zwei]==] },
    }
    return payload
  `, "utf8");
  const parsed = parseStringsLua(file);
  assert.equal(parsed.languages.en.mod_name, "Stormy morning");
  assert.equal(parsed.languages.en.mod_desc, "Line one,\nLine two");
  assert.equal(parsed.languages.de.mod_name, "Stürmischer Morgen");
  assert.equal(parsed.languages.de.mod_desc, "Zeile eins,\nZeile zwei");
  assert.equal(parsed.languages.fr.mod_name, "Matin orageux");
});

test("scanner resolves dependency links and preview", async (t) => {
  const root = temporaryDirectory(t);
  const base = createMod(root, "base_mod_1", `return { info = { name = "Base", minorVersion = 1 } }`);
  createMod(root, "child_mod_1", `return { info = { name = "Child", dependencies = { "base_mod_1" } } }`);
  fs.writeFileSync(path.join(base, "image_00.png"), Buffer.from("not-an-image"));
  const mods = await scanMods(root, "de", "en");
  const child = mods.find((mod) => mod.id === "child_mod_1");
  const parent = mods.find((mod) => mod.id === "base_mod_1");
  assert.equal(child.dependency_links[0].target.id, "base_mod_1");
  assert.equal(parent.required_by[0].id, "child_mod_1");
  assert.equal(findPreview(base), path.join(base, "image_00.png"));
  assert.equal(sanitizeMod(parent).has_preview, true);
});

test("installer extracts a 7z archive with the bundled binary", async (t) => {
  const root = temporaryDirectory(t);
  const source = path.join(root, "source");
  const mods = path.join(root, "mods");
  const archive = path.join(root, "sample.7z");
  fs.mkdirSync(mods);
  createMod(source, "archived_mod_1", `return { info = { name = "Archived" } }`);
  execFileSync(path7za, ["a", archive, "."], { cwd: source, stdio: "ignore" });
  const result = await installInputs([archive], mods, { delete_download_archives_after_install: false });
  assert.equal(result.installed_any, true);
  assert.equal(fs.existsSync(path.join(mods, "archived_mod_1", "mod.lua")), true);
});

test("TGA previews are converted to PNG without Python", (t) => {
  const root = temporaryDirectory(t);
  const file = path.join(root, "image_00.tga");
  const tga = Buffer.alloc(18 + 6);
  tga[2] = 2;
  tga.writeUInt16LE(2, 12); tga.writeUInt16LE(1, 14); tga[16] = 24; tga[17] = 0x20;
  tga.set([0, 0, 255, 0, 255, 0], 18);
  fs.writeFileSync(file, tga);
  const decoded = decodeTga(tga);
  assert.deepEqual([...decoded.pixels.subarray(0, 8)], [255, 0, 0, 255, 0, 255, 0, 255]);
  const png = previewBytes(file).body;
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(encodePng(2, 1, decoded.pixels).length > 40);
});

test("DXT1 DDS previews are decoded", () => {
  const dds = Buffer.alloc(136);
  dds.write("DDS ", 0, "ascii");
  dds.writeUInt32LE(124, 4); dds.writeUInt32LE(4, 12); dds.writeUInt32LE(4, 16);
  dds.write("DXT1", 84, "ascii");
  dds.writeUInt16LE(0xf800, 128); dds.writeUInt16LE(0x07e0, 130);
  dds.writeUInt32LE(0, 132);
  const decoded = decodeDds(dds);
  assert.equal(decoded.width, 4);
  assert.deepEqual([...decoded.pixels.subarray(0, 4)], [255, 0, 0, 255]);
});

test("DeepL uses the correct endpoint and parses a translation", async () => {
  assert.match(endpointForKey("secret:fx"), /api-free/);
  const result = await translateText("Hello", "de", "secret:fx", async (_url, options) => {
    assert.match(options.headers.Authorization, /secret:fx/);
    return { ok: true, json: async () => ({ translations: [{ text: "Hallo" }] }) };
  });
  assert.deepEqual(result, { text: "Hallo", error: "" });
});

test("IPC backend contract scans and returns sanitized mods", async (t) => {
  const data = temporaryDirectory(t);
  const modsRoot = path.join(data, "mods");
  createMod(modsRoot, "ipc_mod_1", `return { info = { name = "IPC Mod" } }`);
  const backend = new Backend(data, { info() {} });
  await backend.request("/api/config", { method: "POST", body: JSON.stringify({ mods_path: modsRoot }) });
  const { job } = await backend.request("/api/scan", { method: "POST", body: "{}" });
  let current;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    ({ job: current } = await backend.request(`/api/jobs/${job.id}`));
    if (current.status !== "running") break;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.equal(current.status, "done");
  const result = await backend.request("/api/mods?q=ipc");
  assert.equal(result.count, 1);
  assert.equal(result.mods[0].name, "IPC Mod");
});
