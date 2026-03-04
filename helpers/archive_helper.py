import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}


def parse_drop_files(raw: str) -> list[Path]:
    parts = re.findall(r"\{[^}]+\}|[^\s]+", raw)
    result: list[Path] = []
    for part in parts:
        part = part.strip()
        if part.startswith("{") and part.endswith("}"):
            part = part[1:-1]
        if part:
            result.append(Path(part))
    return result


def extract_archive(archive_path: Path, destination: Path) -> tuple[bool, str]:
    suffix = archive_path.suffix.lower()

    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(destination)
            return True, "ZIP entpackt"

        if suffix == ".7z":
            try:
                import py7zr
            except ImportError:
                return False, "py7zr fehlt (pip install py7zr)"

            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=destination)
            return True, "7Z entpackt"

        if suffix == ".rar":
            try:
                import rarfile
            except ImportError:
                return False, "rarfile fehlt (pip install rarfile + unrar/bsdtar)"

            with rarfile.RarFile(archive_path) as archive:
                archive.extractall(path=destination)
            return True, "RAR entpackt"

        return False, f"Nicht unterstuetztes Archiv: {suffix}"
    except Exception as first_error:
        try:
            result = subprocess.run(
                ["7z", "x", str(archive_path), f"-o{destination}", "-y"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return True, "Archiv mit 7z CLI entpackt"
            return False, f"Entpacken fehlgeschlagen: {first_error}"
        except FileNotFoundError:
            return False, f"Entpacken fehlgeschlagen: {first_error}"


def find_valid_mod_roots(root: Path) -> list[Path]:
    found: list[Path] = []
    for mod_lua in root.rglob("mod.lua"):
        mod_dir = mod_lua.parent
        if (mod_dir / "res").is_dir():
            found.append(mod_dir)

    unique: list[Path] = []
    seen = set()
    for item in sorted(found):
        key = str(item.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def install_mod_folder(source_mod_dir: Path, mods_root: Path) -> tuple[bool, str]:
    target_dir = mods_root / source_mod_dir.name
    try:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_mod_dir, target_dir)
        return True, f"Installiert: {source_mod_dir.name}"
    except Exception as exc:
        return False, f"Fehler beim Kopieren ({source_mod_dir.name}): {exc}"
