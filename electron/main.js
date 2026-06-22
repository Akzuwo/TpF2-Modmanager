const { app, BrowserWindow, dialog, ipcMain, net, protocol, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { Backend } = require("./backend");
const { previewBytes } = require("./backend/image");

protocol.registerSchemesAsPrivileged([
  { scheme: "tpf2-preview", privileges: { secure: true, supportFetchAPI: true, corsEnabled: true } }
]);

let mainWindow = null;
let backend = null;

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  if (!app.isPackaged) console.log(line);
  try { fs.appendFileSync(path.join(app.getPath("userData"), "electron-main.log"), `${line}\n`, "utf8"); }
  catch { /* Logging must never prevent startup. */ }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 860,
    minWidth: 1040,
    minHeight: 700,
    title: "TpF2 Modmanager",
    backgroundColor: "#0f1815",
    icon: path.resolve(__dirname, "..", "media", "icon.png"),
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => { mainWindow = null; });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.loadFile(path.resolve(__dirname, "..", "web_static", "index.html"));
}

async function pickPath(options) {
  if (!mainWindow) return [];
  const result = await dialog.showOpenDialog(mainWindow, options);
  return result.canceled ? [] : result.filePaths;
}

function registerIpc() {
  ipcMain.handle("backend:request", (_event, route, options) => {
    if (typeof route !== "string" || !route.startsWith("/api/")) throw new Error("Ungueltiger Backend-Aufruf");
    return backend.request(route, options || {});
  });
  ipcMain.handle("dialog:mods-folder", () => pickPath({ title: "Mod-Verzeichnis auswaehlen", properties: ["openDirectory"] }));
  ipcMain.handle("dialog:workshop-folder", () => pickPath({ title: "Steam Workshop-Modordner auswaehlen", properties: ["openDirectory"] }));
  ipcMain.handle("dialog:appworkshop-file", () => pickPath({
    title: "appworkshop_1066780.acf auswaehlen",
    filters: [{ name: "Steam appworkshop", extensions: ["acf"] }, { name: "Alle Dateien", extensions: ["*"] }],
    properties: ["openFile"]
  }));
  ipcMain.handle("dialog:install-inputs", () => pickPath({
    title: "Mods installieren",
    filters: [{ name: "Archive", extensions: ["zip", "7z", "rar"] }, { name: "Alle Dateien", extensions: ["*"] }],
    properties: ["openFile", "openDirectory", "multiSelections"]
  }));
  ipcMain.handle("shell:open-external", (_event, url) => {
    if (!/^https?:\/\//i.test(String(url))) throw new Error("Nur HTTP(S)-Links sind erlaubt.");
    return shell.openExternal(url);
  });
}

app.whenReady().then(() => {
  backend = new Backend(app.getPath("userData"), { info: log });
  protocol.handle("tpf2-preview", (request) => {
    const token = new URL(request.url).pathname.replace(/^\//, "");
    const filePath = backend.resolvePreview(token);
    if (!filePath || !fs.existsSync(filePath)) return new Response("Not found", { status: 404 });
    const converted = previewBytes(filePath);
    if (converted) return new Response(converted.body, { headers: { "Content-Type": converted.type } });
    return net.fetch(pathToFileURL(filePath).toString());
  });
  registerIpc();
  createWindow();
}).catch((error) => {
  log(`startup failed: ${error.stack || error.message}`);
  dialog.showErrorBox("TpF2 Modmanager", error.message);
  app.quit();
});

app.on("window-all-closed", () => app.quit());
