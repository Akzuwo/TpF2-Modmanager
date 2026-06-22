# TpF2 Modmanager

Electron-Desktop-App zum Verwalten von Transport Fever 2 Mods. Die Oberfläche läuft in Electron; Scannen, Installieren und Mod-Verwaltung übernimmt ein lokales Python-Backend. Es gibt keine Qt/PySide-Oberfläche mehr.

## Funktionen

- Lokale Mods und Steam-Workshop-Mods scannen
- Mods suchen, Details und Abhängigkeiten anzeigen
- `.zip`-, `.7z`- und `.rar`-Archive installieren
- Doppelte lokale/Workshop-Mods erkennen
- Mod-Ordner öffnen und Mods löschen
- Deutsche und englische Oberfläche sowie übersetzte Mod-Texte

## Entwicklung

Voraussetzungen:

- Node.js 20 oder neuer
- Python 3.10 oder neuer

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm ci
npm start
```

`npm start` startet Electron. Electron startet seinerseits das Python-Backend auf einem freien lokalen Port. Die Konfiguration liegt im Entwicklungsmodus als `config.json` im Projektordner.

## Windows-Build

```powershell
.\build.ps1 2.0
```

Das Skript installiert die Build-Abhängigkeiten, synchronisiert die Version in `package.json` und `package-lock.json` und erzeugt den NSIS-Installer `dist-electron/TpF2-Modmanager-Setup-2.0.0.exe`. Mit `-SkipInstall` kann die erneute Installation übersprungen werden. Python und Node.js werden auf dem Zielrechner nicht benötigt.

## Struktur

- `electron/`: Desktop-Fenster, native Dateidialoge und Prozessverwaltung
- `web_static/`: HTML-, CSS- und JavaScript-Oberfläche
- `web_backend/`: lokale HTTP-API
- `helpers/`: Mod-, Archiv-, Konfigurations- und Plattformlogik
- `app.py`: Einstiegspunkt des gebündelten Python-Backends

## English

TpF2 Modmanager is an Electron desktop application for managing Transport Fever 2 mods. Electron renders the UI and starts a bundled local Python backend; Qt/PySide is no longer used.

For development, install Python dependencies with `python -m pip install -r requirements.txt`, install Node dependencies with `npm ci`, and run `npm start`. Build a versioned Windows NSIS installer with `.\build.ps1 2.0`.
