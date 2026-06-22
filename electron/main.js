const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const http = require("node:http");
const net = require("node:net");

let mainWindow = null;
let backendProcess = null;
let backendUrl = null;
let isQuitting = false;

const isDev = !app.isPackaged;
let port = 8765;

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  if (isDev) {
    console.log(line.trim());
    return;
  }
  try {
    fs.appendFileSync(path.join(app.getPath("userData"), "electron-main.log"), line, "utf8");
  } catch {
    // Logging must never prevent startup.
  }
}

function backendExecutable() {
  if (isDev) {
    return {
      command: "python",
      args: ["app.py", "--port", String(port)],
      cwd: path.resolve(__dirname, "..")
    };
  }

  return {
    command: path.join(process.resourcesPath, "backend", "TpF2-Modmanager-Backend.exe"),
    args: ["--port", String(port), "--data-dir", app.getPath("userData")],
    cwd: path.dirname(process.execPath)
  };
}

function isPortFree(candidatePort) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(candidatePort, "127.0.0.1");
  });
}

async function findFreePort(startPort) {
  for (let candidate = startPort; candidate < startPort + 40; candidate += 1) {
    if (await isPortFree(candidate)) {
      return candidate;
    }
  }
  throw new Error("Kein freier lokaler Port fuer das Python-Backend gefunden.");
}

function waitForBackend(url, timeoutMs = 18000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const request = http.get(`${url}/api/config`, (response) => {
        response.resume();
        if (response.statusCode === 200) {
          resolve();
        } else {
          retry();
        }
      });
      request.on("error", retry);
      request.setTimeout(1200, () => {
        request.destroy();
        retry();
      });
    };

    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error("Python-Backend konnte nicht gestartet werden."));
        return;
      }
      setTimeout(tick, 300);
    };

    tick();
  });
}

async function startBackend() {
  port = await findFreePort(port);
  backendUrl = `http://127.0.0.1:${port}`;
  const backend = backendExecutable();
  log(`starting backend: ${backend.command} ${backend.args.join(" ")} cwd=${backend.cwd}`);
  backendProcess = spawn(backend.command, backend.args, {
    cwd: backend.cwd,
    windowsHide: true,
    stdio: isDev ? "inherit" : "ignore"
  });

  backendProcess.on("exit", (code) => {
    log(`backend exited: ${code}`);
    if (!isQuitting && mainWindow && !mainWindow.isDestroyed() && code !== 0) {
      mainWindow.webContents.send("backend-exit", code);
    }
  });
  backendProcess.on("error", (error) => {
    log(`backend spawn error: ${error.message}`);
  });

  await waitForBackend(backendUrl);
  log(`backend ready: ${backendUrl}`);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 860,
    minWidth: 1040,
    minHeight: 700,
    title: "TpF2 Modmanager",
    backgroundColor: "#0f1815",
    icon: path.resolve(__dirname, "..", "media", "icon.ico"),
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  mainWindow.webContents.on("did-fail-load", (_event, code, description) => {
    log(`window failed load: ${code} ${description}`);
  });
  mainWindow.loadURL(backendUrl);
}

async function pickPath(options) {
  if (!mainWindow) return [];
  const result = await dialog.showOpenDialog(mainWindow, options);
  return result.canceled ? [] : result.filePaths;
}

app.whenReady().then(async () => {
  try {
    log(`electron ready. packaged=${app.isPackaged} resources=${process.resourcesPath} exe=${process.execPath}`);
    await startBackend();
    createWindow();
  } catch (error) {
    log(`startup failed: ${error.stack || error.message}`);
    dialog.showErrorBox("TpF2 Modmanager", error.message);
    app.quit();
  }
});

ipcMain.handle("dialog:mods-folder", () =>
  pickPath({
    title: "Mod-Verzeichnis auswaehlen",
    properties: ["openDirectory"]
  })
);

ipcMain.handle("dialog:workshop-folder", () =>
  pickPath({
    title: "Steam Workshop-Modordner auswaehlen",
    properties: ["openDirectory"]
  })
);

ipcMain.handle("dialog:appworkshop-file", () =>
  pickPath({
    title: "appworkshop_1066780.acf auswaehlen",
    filters: [
      { name: "Steam appworkshop", extensions: ["acf"] },
      { name: "Alle Dateien", extensions: ["*"] }
    ],
    properties: ["openFile"]
  })
);

ipcMain.handle("dialog:install-inputs", () =>
  pickPath({
    title: "Mods installieren",
    filters: [
      { name: "Archive", extensions: ["zip", "7z", "rar"] },
      { name: "Alle Dateien", extensions: ["*"] }
    ],
    properties: ["openFile", "openDirectory", "multiSelections"]
  })
);

ipcMain.handle("shell:open-external", (_event, url) => shell.openExternal(url));

app.on("before-quit", () => {
  isQuitting = true;
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
});

app.on("window-all-closed", () => {
  app.quit();
});
