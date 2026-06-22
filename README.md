# TpF2 Modmanager

Electron-Desktop-App zum Verwalten von Transport Fever 2 Mods. Anwendung, Mod-Parser und Dateiverwaltung laufen vollständig in JavaScript – ohne Python, PyInstaller, lokalen Webserver oder Qt.

## Funktionen

- Lokale Mods und Steam-Workshop-Mods scannen
- `mod.lua`, `strings.lua` und `strings*.json` auswerten
- Mods suchen sowie Details und Abhängigkeiten anzeigen
- ZIP-, 7Z- und RAR-Archive installieren
- Doppelte lokale/Workshop-Mods erkennen
- Mod-Ordner öffnen und Mods löschen

## Entwicklung

Voraussetzungen: Node.js 20 oder neuer.

```powershell
npm ci
npm start
```

Der Renderer läuft mit aktivierter Context Isolation und ohne Node-Integration. Alle privilegierten Aktionen gehen über die schmale API in `electron/preload.js` an die Node-Services unter `electron/backend/`.

## Test und Build

```powershell
npm test
.\build.ps1 2.0
```

Das Buildskript synchronisiert die Version und erzeugt den NSIS-Installer `dist-electron/TpF2-Modmanager-Setup-2.0.0.exe`. Mit `-SkipInstall` lässt sich die erneute Ausführung von `npm ci` überspringen.

## Struktur

- `electron/main.js`: Fenster, Protokoll- und IPC-Grenze
- `electron/preload.js`: sichere Renderer-API
- `electron/backend/`: Config, Lua-Parser, Scans, Archive, Jobs und Mod-Verwaltung
- `web_static/`: HTML-, CSS- und Renderer-JavaScript
- `test/`: Node-Testfälle mit temporären Mod-Fixtures

## English

TpF2 Modmanager is an Electron-only desktop application. Its UI, Lua metadata parser, archive installation, scans and file management are implemented in JavaScript; Python and Qt are not required. Run `npm ci && npm start` for development, `npm test` for tests, and `.\build.ps1 2.0` for a versioned Windows NSIS installer.
