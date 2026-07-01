const { app, BrowserWindow, dialog, ipcMain, net, protocol, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { Backend } = require("./backend");
const { previewBytes } = require("./backend/image");
const { autoUpdater } = require("electron-updater");

protocol.registerSchemesAsPrivileged([
  { scheme: "tpf2-preview", privileges: { secure: true, supportFetchAPI: true, corsEnabled: true } }
]);

let mainWindow = null;
let backend = null;
let updateDownloadStarted = false;

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

function configureAutoUpdater() {
  if (!app.isPackaged) {
    log("update check skipped in development mode");
    return;
  }

  autoUpdater.logger = { info: log, warn: log, error: log, debug: log };
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;

  autoUpdater.on("update-available", async (info) => {
    if (!mainWindow || updateDownloadStarted) return;
    const result = await dialog.showMessageBox(mainWindow, {
      type: "info",
      title: "Update verfügbar",
      message: `TpF2 Modmanager ${info.version} ist verfügbar.`,
      detail: "Soll das Update jetzt heruntergeladen und automatisch installiert werden?",
      buttons: ["Ja, jetzt aktualisieren", "Nein"],
      defaultId: 0,
      cancelId: 1,
      noLink: true
    });
    if (result.response !== 0) return;

    updateDownloadStarted = true;
    log(`downloading update ${info.version}`);
    autoUpdater.downloadUpdate().catch((error) => {
      updateDownloadStarted = false;
      log(`update download failed: ${error.stack || error.message}`);
      if (mainWindow) dialog.showErrorBox("Update fehlgeschlagen", "Das Update konnte nicht heruntergeladen werden. Bitte versuche es später erneut.");
    });
  });

  autoUpdater.on("download-progress", ({ percent }) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.setProgressBar(percent / 100);
  });

  autoUpdater.on("update-downloaded", (info) => {
    log(`update ${info.version} downloaded; starting installer`);
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.setProgressBar(-1);
    autoUpdater.quitAndInstall(true, true);
  });

  autoUpdater.on("update-not-available", () => log("application is up to date"));
  autoUpdater.on("error", (error) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.setProgressBar(-1);
    log(`update error: ${error.stack || error.message}`);
  });

  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((error) => log(`update check failed: ${error.stack || error.message}`));
  }, 1500);
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
  configureAutoUpdater();
}).catch((error) => {
  log(`startup failed: ${error.stack || error.message}`);
  dialog.showErrorBox("TpF2 Modmanager", error.message);
  app.quit();
});

app.on("window-all-closed", () => app.quit());
