import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_app_icon_path(resource_dir: Path) -> Path | None:
    for relative_path in (
        Path("media") / "icon.ico",
        Path("media") / "icon.png",
        Path("media") / "logo.png",
    ):
        candidate = resource_dir / relative_path
        if candidate.exists():
            return candidate
    return None


def open_path_in_file_manager(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"Pfad nicht gefunden: {path}"

    try:
        if os.name == "nt":
            os.startfile(str(path))
            return True, ""

        command = _resolve_open_command()
        if command is None:
            return False, "Kein Dateimanager-Startkommando gefunden"

        result = subprocess.run(
            [command, str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True, ""

        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or f"exit code {result.returncode}"
    except Exception as exc:
        return False, str(exc)


def _resolve_open_command() -> str | None:
    if sys.platform == "darwin":
        return "open"

    for candidate in ("xdg-open", "gio"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None
