import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}

SEVEN_ZIP_CANDIDATES = [
    "7z",
    "7zz",
    "7za",
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]

RAR_TOOL_CANDIDATES = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files\WinRAR\WinRAR.exe",
    r"C:\Program Files\WinRAR\Rar.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
    r"C:\Program Files (x86)\WinRAR\Rar.exe",
    "unrar",
    "unar",
    "bsdtar",
    "rar",
]


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


def _run_extractor(commands: list[list[str]]) -> tuple[bool, str]:
    errors: list[str] = []
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            continue

        if result.returncode == 0:
            return True, ""

        detail = (result.stderr or result.stdout or "").strip()
        errors.append(detail or f"exit code {result.returncode}")

    return False, " | ".join(errors)


def _extract_with_7z(archive_path: Path, destination: Path) -> tuple[bool, str]:
    commands = [[tool, "x", str(archive_path), f"-o{destination}", "-y"] for tool in SEVEN_ZIP_CANDIDATES]
    ok, detail = _run_extractor(commands)
    if ok:
        return True, "Archiv mit 7z entpackt"
    return False, detail


def _extract_with_rar_tools(archive_path: Path, destination: Path) -> tuple[bool, str]:
    destination_arg = f"{destination}{os.sep}"
    commands = [[tool, "x", "-o+", str(archive_path), destination_arg] for tool in RAR_TOOL_CANDIDATES]
    ok, detail = _run_extractor(commands)
    if ok:
        return True, "RAR mit externem Tool entpackt"
    return False, detail


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
                ok, detail = _extract_with_rar_tools(archive_path, destination)
                if ok:
                    return True, detail

                ok, detail_7z = _extract_with_7z(archive_path, destination)
                if ok:
                    return True, detail_7z

                error_parts = ["rarfile fehlt (pip install rarfile)"]
                if detail:
                    error_parts.append(f"RAR-Tool: {detail}")
                if detail_7z:
                    error_parts.append(f"7z: {detail_7z}")
                return False, " | ".join(error_parts)

            with rarfile.RarFile(archive_path) as archive:
                archive.extractall(path=destination)
            return True, "RAR entpackt"

        return False, f"Nicht unterstuetztes Archiv: {suffix}"
    except Exception as first_error:
        if suffix == ".rar":
            ok, detail = _extract_with_rar_tools(archive_path, destination)
            if ok:
                return True, detail

        ok, detail_7z = _extract_with_7z(archive_path, destination)
        if ok:
            return True, detail_7z

        if detail_7z:
            return False, f"Entpacken fehlgeschlagen: {first_error} | 7z: {detail_7z}"
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
