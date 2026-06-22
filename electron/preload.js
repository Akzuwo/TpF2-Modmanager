const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("desktopShell", {
  platform: process.platform,
  isElectron: true,
  request: (route, options = {}) => ipcRenderer.invoke("backend:request", route, options),
  previewUrl: (token) => token ? `tpf2-preview://image/${encodeURIComponent(token)}` : "",
  pickModsFolder: () => ipcRenderer.invoke("dialog:mods-folder"),
  pickWorkshopFolder: () => ipcRenderer.invoke("dialog:workshop-folder"),
  pickAppWorkshopFile: () => ipcRenderer.invoke("dialog:appworkshop-file"),
  pickInstallInputs: () => ipcRenderer.invoke("dialog:install-inputs"),
  getPathForFile: (file) => webUtils.getPathForFile(file),
  openExternal: (url) => ipcRenderer.invoke("shell:open-external", url)
});
