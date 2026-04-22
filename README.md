# TpF2 Modmanager

Deutsch | English  
Dieses README enthaelt eine kurze Bedienungsanleitung in Deutsch und Englisch.

## EXE-Version / EXE Version

### Deutsch
- Wenn du die `.exe` nutzt, brauchst du kein Python.
- Starte `TpF2-Modmanager.exe`.
- Die neueste Version findest du hier: https://github.com/Akzuwo/TpF2-Modmanager/releases
- Beim ersten Start wird `config.json` neben der `.exe` erstellt.
- Stelle in der App dein `Mods-Verzeichnis` ein und klicke danach auf `Scannen`.
- Falls du DeepL nutzen willst, trage deinen API-Key in `Einstellungen` ein.
- GitHub Actions baut bei jedem Push zusätzlich eine Linux-Binary ohne Dateiendung.

### English
- If you use the `.exe`, you do not need Python.
- Start `TpF2-Modmanager.exe`.
- You can find the latest version here: https://github.com/Akzuwo/TpF2-Modmanager/releases
- On first launch, `config.json` is created next to the `.exe`.
- Set your `Mods folder` in the app and then click `Scan`.
- If you want to use DeepL, enter your API key in `Settings`.
- GitHub Actions also builds a Linux binary without a file extension on every push.

## Deutsch

### Überblick
Desktop-Tool (PySide6) zum Verwalten von Transport Fever 2 Mods:
- Mods-Ordner scannen und Mod-Infos anzeigen
- Mods suchen/filtern
- Archive (`.zip`, `.7z`, `.rar`) installieren (inkl. Drag & Drop, falls verfuegbar)
- Abhaengigkeiten anzeigen und aufloesen
- Mod-Details mit aufgelösten Feldern und Preview-Bild
- Mod-Ordner direkt oeffnen oder Mod loeschen
- UI-Sprache (`de`/`en`) sowie Mod-Textsprache (`de`/`en`/`es`/`it`)

### Voraussetzungen
- Python 3.10+
- Windows oder Linux

Optionale Python-Pakete:
- `Pillow` für Bildvorschau
- `py7zr` für `.7z`-Archive
- `rarfile` für `.rar`-Archive
- `deepl` für DeepL SDK (HTTP-Fallback ist eingebaut)
- `PySide6` für das Desktop-GUI

Optionales System-Tool:
- `7z` CLI als Fallback beim Entpacken

### Installation
```powershell
python -m venv .venv
pip install PySide6 pillow py7zr rarfile deepl
```

Windows aktivieren:
```powershell
.\.venv\Scripts\Activate.ps1
```

Linux aktivieren:
```bash
source .venv/bin/activate
```

### Start
```powershell
python app.py
```

### Bedienungsanleitung
1. App starten.
2. Bei `Mods-Verzeichnis` den Transport Fever 2 Mod-Ordner auswaehlen.
3. `Scannen` klicken, um alle Mods einzulesen.
4. In der Tabelle nach Name/Autor/Version/Abhaengigkeiten suchen (Suchfeld oben).
5. Mod-Details oeffnen:
   - Doppelklick auf eine Zeile fuer Detailansicht.
6. Mods installieren:
   - `Manuelle Installation` klicken und Archiv(e) waehlen, oder
   - Archiv/Ordner per Drag & Drop auf die Drop-Zone ziehen (wenn verfuegbar).
7. Rechtsklick auf Mod-Zeile fuer Kontextmenue:
   - Mod-Ordner oeffnen
   - Mod loeschen (mit Abhaengigkeitswarnung)
8. Einstellungen oeffnen:
   - App-Sprache setzen
   - Mod-Sprache + Fallback setzen
   - optional DeepL API Key eintragen

### Konfigurationsdatei
Beim ersten Start wird `config.json` erstellt. Wichtige Felder:
- `mods_path`: Pfad zum Mods-Ordner
- `language`: bevorzugte Mod-Sprache
- `fallback_language`: Ausweichsprache
- `app_language`: Sprache der App (`de`/`en`)
- `deepl_api_key`: optional fuer DeepL

Hinweis: `config.json` sollte nicht mit sensiblen Werten gepusht werden.

### Fehlerbehebung
- `.7z` kann nicht entpackt werden: `py7zr` installieren oder `7z` CLI bereitstellen.
- `.rar` kann nicht entpackt werden: `rarfile` installieren und `unrar`/`bsdtar` oder `7z` verfuegbar machen.
- Die App startet nicht: `PySide6` installieren.
- Keine Vorschau: `Pillow` installieren und pruefen, ob die Mod ein `image_00.*` hat.

---

## English

### Overview
Desktop tool (PySide6) for managing Transport Fever 2 mods:
- Scan the mods directory and list mod metadata
- Search/filter mods
- Install archives (`.zip`, `.7z`, `.rar`) including drag & drop (if available)
- Show and resolve dependencies
- Open mod details with resolved fields and preview image
- Open mod folder directly or delete a mod
- UI language (`de`/`en`) and mod text language (`de`/`en`/`es`/`it`)

### Requirements
- Python 3.10+
- Windows or Linux

Optional Python packages:
- `Pillow` for image previews
- `py7zr` for `.7z` archives
- `rarfile` for `.rar` archives
- `deepl` for DeepL SDK (HTTP fallback is built in)
- `PySide6` for the desktop GUI

Optional system tool:
- `7z` CLI as extraction fallback

### Installation
```powershell
python -m venv .venv
pip install PySide6 pillow py7zr rarfile deepl
```

Activate on Windows:
```powershell
.\.venv\Scripts\Activate.ps1
```

Activate on Linux:
```bash
source .venv/bin/activate
```

### Run
```powershell
python app.py
```

### User Guide
1. Launch the app.
2. Select your Transport Fever 2 mods directory in `Mods directory`.
3. Click `Scan` to load all mods.
4. Use the search box to filter by name/author/version/dependencies.
5. Open mod details:
   - Double-click a row to open details.
6. Install mods:
   - Click `Manual installation` and select archives, or
   - Drag archive/folder files onto the drop zone (if available).
7. Right-click a mod row for context actions:
   - Open mod folder
   - Delete mod (with dependency warning)
8. Open settings to configure:
   - App language
   - Mod language + fallback language
   - optional DeepL API key

### Config File
On first run, `config.json` is created. Main keys:
- `mods_path`: path to mods directory
- `language`: preferred mod language
- `fallback_language`: fallback language
- `app_language`: app UI language (`de`/`en`)
- `deepl_api_key`: optional DeepL key

Note: do not commit `config.json` when it contains sensitive values.

### Troubleshooting
- Cannot extract `.7z`: install `py7zr` or provide `7z` CLI.
- Cannot extract `.rar`: install `rarfile` and make `unrar`/`bsdtar` or `7z` available.
- App does not start: install `PySide6`.
- No preview image: install `Pillow` and verify the mod contains `image_00.*`.

## Builds / CI

### Deutsch
- Der Workflow liegt unter `.github/workflows/build.yml`.
- Bei jedem Push und manuell ueber `workflow_dispatch` werden zwei PyInstaller-Builds erzeugt:
  - Windows: `TpF2-Modmanager.exe`
  - Linux: `TpF2-Modmanager`
- Die Artefakte findest du im jeweiligen GitHub-Actions-Run unter `Artifacts`.
- Fuer einen manuellen Release-Run oeffne in GitHub `Actions` -> `Build` -> `Run workflow`.
- Setze `publish_release` auf `true`, wenn nach erfolgreichem Build automatisch ein GitHub-Release erstellt werden soll.
- Optional kannst du `version` setzen. Trage nur die Versionsnummer ein, z. B. `1.2.3`, nicht `Release 1.2.3`.
- Dann heissen Tag und Release `v<version>`, z. B. `v1.2.3`.
- Wenn `version` leer bleibt, wird automatisch ein Fallback wie `vmanual-42` verwendet.

### English
- The workflow lives in `.github/workflows/build.yml`.
- On every push and via `workflow_dispatch`, two PyInstaller builds are created:
  - Windows: `TpF2-Modmanager.exe`
  - Linux: `TpF2-Modmanager`
- You can find both artifacts in the corresponding GitHub Actions run under `Artifacts`.
- For a manual release run, open `Actions` -> `Build` -> `Run workflow` in GitHub.
- Set `publish_release` to `true` to automatically create a GitHub release after a successful build.
- You can optionally set `version`. Enter only the version number, for example `1.2.3`, not `Release 1.2.3`.
- Then the tag and release name use `v<version>`, for example `v1.2.3`.
- If `version` is empty, the workflow falls back to a tag like `vmanual-42`.
