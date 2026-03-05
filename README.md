# TpF2 Modmanager

Deutsch | English  
Dieses README enthaelt eine kurze Bedienungsanleitung in Deutsch und Englisch.

## Deutsch

### Ueberblick
Desktop-Tool (Tkinter) zum Verwalten von Transport Fever 2 Mods:
- Mods-Ordner scannen und Mod-Infos anzeigen
- Mods suchen/filtern
- Archive (`.zip`, `.7z`, `.rar`) installieren (inkl. Drag & Drop, falls verfuegbar)
- Abhaengigkeiten anzeigen und aufloesen
- Mod-Details inkl. `mod.lua`-Ansicht und Preview-Bild
- Mod-Ordner direkt oeffnen oder Mod loeschen
- UI-Sprache (`de`/`en`) sowie Mod-Textsprache (`de`/`en`/`es`/`it`)

### Voraussetzungen
- Python 3.10+
- Windows (wegen `os.startfile`, empfohlen)

Optionale Python-Pakete:
- `Pillow` fuer Bildvorschau
- `tkinterdnd2` fuer Drag & Drop
- `py7zr` fuer `.7z`-Archive
- `rarfile` fuer `.rar`-Archive
- `deepl` fuer DeepL SDK (HTTP-Fallback ist eingebaut)

Optionales System-Tool:
- `7z` CLI als Fallback beim Entpacken

### Installation
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pillow tkinterdnd2 py7zr rarfile deepl
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
   - Doppelklick auf die Abhaengigkeiten-Spalte, um zu abhaengigen Mods zu springen.
6. Mods installieren:
   - `Archive installieren` klicken und Archiv(e) waehlen, oder
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
- Kein Drag & Drop: `tkinterdnd2` installieren.
- Keine Vorschau: `Pillow` installieren und pruefen, ob die Mod ein `image_00.*` hat.

---

## English

### Overview
Desktop tool (Tkinter) for managing Transport Fever 2 mods:
- Scan the mods directory and list mod metadata
- Search/filter mods
- Install archives (`.zip`, `.7z`, `.rar`) including drag & drop (if available)
- Show and resolve dependencies
- Open mod details with `mod.lua` view and preview image
- Open mod folder directly or delete a mod
- UI language (`de`/`en`) and mod text language (`de`/`en`/`es`/`it`)

### Requirements
- Python 3.10+
- Windows recommended (`os.startfile` is used)

Optional Python packages:
- `Pillow` for image previews
- `tkinterdnd2` for drag & drop
- `py7zr` for `.7z` archives
- `rarfile` for `.rar` archives
- `deepl` for DeepL SDK (HTTP fallback is built in)

Optional system tool:
- `7z` CLI as extraction fallback

### Installation
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pillow tkinterdnd2 py7zr rarfile deepl
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
   - Double-click the dependency column to jump to dependency targets.
6. Install mods:
   - Click `Install archives` and select archives, or
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
- No drag & drop: install `tkinterdnd2`.
- No preview image: install `Pillow` and verify the mod contains `image_00.*`.
