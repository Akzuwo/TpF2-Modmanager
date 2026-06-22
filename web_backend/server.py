import json
import logging
import mimetypes
import os
import threading
import time
from io import BytesIO
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from helpers.archive_helper import ARCHIVE_EXTENSIONS
from helpers.config_helper import DEFAULT_CONFIG, load_config, save_config
from helpers.install_helper import install_inputs
from helpers.mods_helper import (
    delete_mod_folder,
    delete_or_unsubscribe_workshop_mod,
    find_duplicate_mods,
    find_mod_link,
    find_preview_image,
    resolve_dependency_graph,
    scan_mods_parallel,
    scan_workshop_mods,
)
from helpers.platform_helper import open_path_in_file_manager

logger = logging.getLogger(__name__)
WEB_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


class JobCancelled(RuntimeError):
    pass


def contains_mod_lua(root: Path, max_depth: int = 3) -> bool:
    if (root / "mod.lua").is_file():
        return True

    root_depth = len(root.parts)
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
        if "mod.lua" in filenames:
            return True
    return False


class AppState:
    def __init__(self, resource_dir: Path, data_dir: Path) -> None:
        self.resource_dir = resource_dir
        self.data_dir = data_dir
        self.config_path = data_dir / "config.json"
        self.static_dir = resource_dir / "web_static"
        self.lock = threading.RLock()
        self.mods: list[dict] = []
        self.logs: list[str] = []
        self.jobs: dict[str, dict] = {}
        self.next_job_id = 1

    def load_config(self) -> dict:
        return load_config(self.config_path)

    def save_config(self, payload: dict) -> dict:
        config = dict(DEFAULT_CONFIG)
        config.update(self.load_config())
        config.update({key: value for key, value in payload.items() if key in DEFAULT_CONFIG})
        save_config(self.config_path, config)
        return config

    def path_info(self, path_text: str) -> dict:
        path_text = str(path_text or "").strip()
        if not path_text:
            return {
                "path": "",
                "exists": False,
                "is_dir": False,
                "mod_count": 0,
                "child_count": 0,
                "status": "missing",
                "message": "Kein Mod-Ordner gesetzt.",
            }

        root = Path(path_text)
        if not root.exists():
            return {
                "path": path_text,
                "exists": False,
                "is_dir": False,
                "mod_count": 0,
                "child_count": 0,
                "status": "invalid",
                "message": "Dieser Ordner existiert nicht.",
            }
        if not root.is_dir():
            return {
                "path": path_text,
                "exists": True,
                "is_dir": False,
                "mod_count": 0,
                "child_count": 0,
                "status": "invalid",
                "message": "Der Pfad ist kein Ordner.",
            }

        child_dirs = [path for path in root.iterdir() if path.is_dir()]
        mod_count = sum(1 for child in child_dirs if contains_mod_lua(child))
        if (root / "mod.lua").is_file():
            return {
                "path": path_text,
                "exists": True,
                "is_dir": True,
                "mod_count": 1,
                "child_count": len(child_dirs),
                "status": "single_mod",
                "message": "Das sieht wie ein einzelner Mod-Ordner aus. Waehle besser den uebergeordneten Mods-Ordner.",
            }
        if mod_count:
            return {
                "path": path_text,
                "exists": True,
                "is_dir": True,
                "mod_count": mod_count,
                "child_count": len(child_dirs),
                "status": "ok",
                "message": f"{mod_count} Mod-Ordner gefunden.",
            }
        return {
            "path": path_text,
            "exists": True,
            "is_dir": True,
            "mod_count": 0,
            "child_count": len(child_dirs),
            "status": "empty",
            "message": "Ordner existiert, aber ich finde darin keine mod.lua.",
        }

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        logger.info(message)
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-300:]

    def create_job(self, label: str, target, *args, cancellable: bool = False) -> dict:
        with self.lock:
            job_id = str(self.next_job_id)
            self.next_job_id += 1
            job = {
                "id": job_id,
                "label": label,
                "status": "running",
                "progress": {"current": 0, "total": 1, "message": label},
                "result": None,
                "error": "",
                "cancellable": cancellable,
                "cancel_requested": False,
                "started_at": time.time(),
                "finished_at": None,
            }
            self.jobs[job_id] = job

        thread = threading.Thread(target=self._run_job, args=(job_id, target, args), daemon=True)
        thread.start()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def cancel_job(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            if job["status"] == "running" and job.get("cancellable"):
                job["cancel_requested"] = True
                job["progress"]["message"] = "Abbruch wird angefordert..."
            return dict(job)

    def check_cancelled(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job.get("cancel_requested"):
                raise JobCancelled("Vorgang abgebrochen.")

    def set_progress(self, job_id: str, current: int, total: int, message: str = "") -> None:
        self.check_cancelled(job_id)
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job["progress"] = {
                "current": current,
                "total": max(1, total),
                "message": message or job["label"],
            }

    def _run_job(self, job_id: str, target, args) -> None:
        try:
            result = target(job_id, *args)
            with self.lock:
                job = self.jobs[job_id]
                job["status"] = "done"
                job["result"] = result
                job["finished_at"] = time.time()
        except JobCancelled as exc:
            self.log(str(exc))
            with self.lock:
                job = self.jobs[job_id]
                job["status"] = "cancelled"
                job["error"] = str(exc)
                job["finished_at"] = time.time()
        except Exception as exc:
            logger.exception("Web UI job failed: %s", job_id)
            self.log(f"ERROR: {exc}")
            with self.lock:
                job = self.jobs[job_id]
                job["status"] = "error"
                job["error"] = str(exc)
                job["finished_at"] = time.time()

    def scan_job(self, job_id: str) -> dict:
        config = self.load_config()
        root = Path(str(config.get("mods_path", "")).strip())
        if not root.exists() or not root.is_dir():
            raise ValueError("Das Mod-Verzeichnis existiert nicht oder ist ungueltig.")

        self.log(f"Scan gestartet: {root}")

        def progress(done: int, total: int) -> None:
            self.set_progress(job_id, done, total, f"Scanne Mod-Ordner {done}/{total}")

        cpu = os.cpu_count() or 4
        mods = scan_mods_parallel(
            root,
            config.get("language", "de"),
            config.get("fallback_language", "en"),
            max_workers=max(4, min(20, cpu * 2)),
            progress_callback=progress,
            resolve_dependencies=False,
        )
        resolve_dependency_graph(mods)
        with self.lock:
            self.mods = mods
        self.log(f"Scan abgeschlossen: {len(mods)} Mods")
        return {"mods_count": len(mods)}

    def install_job(self, job_id: str, paths: list[str]) -> dict:
        config = self.load_config()
        root = Path(str(config.get("mods_path", "")).strip())
        if not root.exists() or not root.is_dir():
            raise ValueError("Das Mod-Verzeichnis existiert nicht oder ist ungueltig.")

        inputs = [Path(item) for item in paths if str(item).strip()]
        inputs = [path for path in inputs if path.is_dir() or (path.is_file() and path.suffix.lower() in ARCHIVE_EXTENSIONS)]
        if not inputs:
            raise ValueError("Keine unterstuetzten Archive oder Ordner angegeben.")

        total = len(inputs)
        self.set_progress(job_id, 0, total, "Installiere Mods...")
        any_success = install_inputs(
            inputs,
            root,
            "Keine mod.lua gefunden",
            bool(config.get("parallel_install_enabled", False)),
            bool(config.get("delete_download_archives_after_install", False)),
            int(config.get("max_parallel_workers", 2)),
            progress_callback=lambda current, total, status: self.set_progress(job_id, current, total, status),
            log_callback=self.log,
        )
        self.set_progress(job_id, total, total, "Installation abgeschlossen.")
        self.log(f"Installation abgeschlossen: {'Erfolg' if any_success else 'keine Mod installiert'}")
        return {"installed_any": any_success}

    def duplicate_job(self, job_id: str) -> dict:
        config = self.load_config()
        local_root = Path(str(config.get("mods_path", "")).strip())
        workshop_root = Path(str(config.get("workshop_mods_path", "")).strip())
        appworkshop = str(config.get("appworkshop_path", "")).strip()
        appworkshop_path = Path(appworkshop) if appworkshop else None

        if not local_root.exists() or not local_root.is_dir():
            raise ValueError("Das lokale Mod-Verzeichnis ist ungueltig.")
        if not workshop_root.exists() or not workshop_root.is_dir():
            raise ValueError("Der Steam-Workshop-Modordner ist ungueltig.")
        if appworkshop_path and (not appworkshop_path.exists() or not appworkshop_path.is_file()):
            raise ValueError("Die appworkshop_1066780.acf ist ungueltig.")

        cpu = os.cpu_count() or 4
        max_workers = max(4, min(20, cpu * 2))
        self.set_progress(job_id, 0, 1, "Scanne lokale Mods...")
        self.check_cancelled(job_id)
        local_mods = scan_mods_parallel(
            local_root,
            config.get("language", "de"),
            config.get("fallback_language", "en"),
            max_workers=max_workers,
            progress_callback=lambda done, total: self.set_progress(job_id, done, total, "Scanne lokale Mods..."),
            resolve_dependencies=False,
        )
        self.check_cancelled(job_id)
        self.set_progress(job_id, 0, 1, "Scanne Workshop-Mods...")
        workshop_mods = scan_workshop_mods(
            workshop_root,
            appworkshop_path,
            config.get("language", "de"),
            config.get("fallback_language", "en"),
            progress_callback=lambda done, total: self.set_progress(job_id, done, total, "Scanne Workshop-Mods..."),
            resolve_dependencies=False,
        )
        self.check_cancelled(job_id)
        self.set_progress(job_id, 0, 1, "Vergleiche Mods...")
        matches = find_duplicate_mods(
            local_mods,
            workshop_mods,
            progress_callback=lambda done, total: self.set_progress(job_id, done, total, "Vergleiche Mods..."),
        )
        self.log(f"Duplikat-Scan abgeschlossen: {len(matches)} Treffer")
        return {"matches": sanitize_matches(matches), "matches_count": len(matches)}

    def apply_duplicate_action(self, match: dict, action: str) -> tuple[bool, str]:
        config = self.load_config()
        appworkshop_text = str(config.get("appworkshop_path", "")).strip()
        appworkshop_path = Path(appworkshop_text) if appworkshop_text else None
        local_mod = match.get("local_mod", {})
        workshop_mod = match.get("workshop_mod", {})

        if action == "delete_local":
            ok, message = delete_mod_folder(Path(local_mod.get("path", "")))
        elif action == "delete_workshop":
            ok, message = delete_or_unsubscribe_workshop_mod(workshop_mod, appworkshop_path)
        else:
            return False, "Unbekannte Duplikat-Aktion"

        if ok:
            removed_path = local_mod.get("path", "") if action == "delete_local" else workshop_mod.get("path", "")
            with self.lock:
                self.mods = [mod for mod in self.mods if mod.get("path", "") != removed_path]
            self.log(message)
        else:
            self.log(f"ERROR: {message}")
        return ok, message


def sanitize_mod(mod: dict) -> dict:
    dependency_links = []
    for dep in mod.get("dependency_links", []):
        target = dep.get("target")
        dependency_links.append(
            {
                "raw": dep.get("raw", ""),
                "id": dep.get("id", ""),
                "target_name": target.get("name", "") if target else "",
                "target_path": target.get("path", "") if target else "",
                "missing": target is None,
            }
        )

    required_by = [
        {"name": item.get("name", ""), "id": item.get("id", ""), "path": item.get("path", "")}
        for item in mod.get("required_by", [])
    ]

    return {
        "id": mod.get("id", ""),
        "name": mod.get("name", ""),
        "author": mod.get("author", ""),
        "version": mod.get("version", ""),
        "path": mod.get("path", ""),
        "mod_lua": mod.get("mod_lua", ""),
        "description": mod.get("description_translated") or mod.get("description", ""),
        "source_description": mod.get("description", ""),
        "translation_notice": mod.get("translation_notice", ""),
        "deepl_error": mod.get("deepl_error", ""),
        "available_languages": mod.get("translation_available_languages", []),
        "effective_language": mod.get("translation_effective_language", ""),
        "link": find_mod_link(mod.get("resolved_fields", mod.get("raw_fields", {}))),
        "has_preview": find_preview_image(Path(mod.get("path", ""))) is not None if mod.get("path") else False,
        "dependencies": mod.get("dependencies", []),
        "dependency_links": dependency_links,
        "required_by": required_by,
        "resolved_fields": mod.get("resolved_fields", {}),
        "raw_fields": mod.get("raw_fields", {}),
    }


def sanitize_matches(matches: list[dict]) -> list[dict]:
    return [
        {
            "score": item.get("score", 0),
            "reason": item.get("reason", ""),
            "workshop_id": item.get("workshop_id", ""),
            "local_mod": sanitize_mod(item.get("local_mod", {})),
            "workshop_mod": sanitize_mod(item.get("workshop_mod", {})),
        }
        for item in matches
    ]


class RequestHandler(BaseHTTPRequestHandler):
    state: AppState

    def log_message(self, format: str, *args) -> None:
        logger.debug("web ui: " + format, *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_post(parsed)
            return
        self.send_error(404)

    def handle_api_get(self, parsed) -> None:
        if parsed.path == "/api/config":
            self.send_json({"config": self.state.load_config()})
            return
        if parsed.path == "/api/path-info":
            query = parse_qs(parsed.query)
            path_text = query.get("path", [""])[0]
            self.send_json({"info": self.state.path_info(path_text)})
            return
        if parsed.path == "/api/mods":
            query = parse_qs(parsed.query).get("q", [""])[0].strip().lower()
            with self.state.lock:
                mods = [sanitize_mod(mod) for mod in self.state.mods]
            if query:
                mods = [mod for mod in mods if query in json.dumps(mod, ensure_ascii=False).lower()]
            self.send_json({"mods": mods, "count": len(mods)})
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = unquote(parsed.path.rsplit("/", 1)[-1])
            job = self.state.get_job(job_id)
            if not job:
                self.send_json({"error": "Job nicht gefunden"}, status=404)
                return
            self.send_json({"job": job})
            return
        if parsed.path == "/api/logs":
            with self.state.lock:
                logs = list(self.state.logs)
            self.send_json({"logs": logs})
            return
        if parsed.path == "/api/preview":
            query = parse_qs(parsed.query)
            mod_path = Path(query.get("path", [""])[0])
            preview = find_preview_image(mod_path)
            if preview is None:
                self.send_error(404)
                return
            self.serve_preview(preview)
            return
        self.send_json({"error": "Endpoint nicht gefunden"}, status=404)

    def handle_api_post(self, parsed) -> None:
        try:
            payload = self.read_json()
            if parsed.path == "/api/config":
                config = self.state.save_config(payload)
                self.send_json({"config": config})
                return
            if parsed.path == "/api/scan":
                self.send_json({"job": self.state.create_job("Scan", self.state.scan_job)})
                return
            if parsed.path == "/api/install":
                self.send_json({"job": self.state.create_job("Installation", self.state.install_job, payload.get("paths", []))})
                return
            if parsed.path == "/api/duplicates":
                self.send_json({"job": self.state.create_job("Duplikat-Scan", self.state.duplicate_job, cancellable=True)})
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
                parts = parsed.path.strip("/").split("/")
                job = self.state.cancel_job(unquote(parts[2])) if len(parts) >= 4 else None
                if not job:
                    self.send_json({"error": "Job nicht gefunden"}, status=404)
                    return
                self.send_json({"job": job})
                return
            if parsed.path == "/api/open":
                ok, message = open_path_in_file_manager(Path(str(payload.get("path", ""))))
                self.send_json({"ok": ok, "message": message})
                return
            if parsed.path == "/api/delete":
                ok, message = delete_mod_folder(Path(str(payload.get("path", ""))))
                if ok:
                    with self.state.lock:
                        deleted = str(payload.get("path", ""))
                        self.state.mods = [mod for mod in self.state.mods if mod.get("path", "") != deleted]
                    self.state.log(message)
                self.send_json({"ok": ok, "message": message})
                return
            if parsed.path == "/api/duplicate-action":
                ok, message = self.state.apply_duplicate_action(
                    payload.get("match", {}),
                    str(payload.get("action", "")),
                )
                self.send_json({"ok": ok, "message": message})
                return
            self.send_json({"error": "Endpoint nicht gefunden"}, status=404)
        except Exception as exc:
            logger.exception("API request failed: %s", parsed.path)
            self.send_json({"error": str(exc)}, status=500)

    def serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        root = self.state.static_dir
        relative_path = path.lstrip("/")
        if relative_path.startswith("media/"):
            root = self.state.resource_dir

        candidate = (root / relative_path).resolve()
        safe_root = root.resolve()
        if safe_root not in candidate.parents and candidate != safe_root:
            self.send_error(403)
            return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(404)
            return
        self.serve_file(candidate)

    def serve_file(self, file_path: Path) -> None:
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_bytes(body, content_type)

    def serve_preview(self, file_path: Path) -> None:
        if file_path.suffix.lower() in WEB_IMAGE_SUFFIXES:
            self.serve_file(file_path)
            return

        try:
            from PIL import Image

            with Image.open(file_path) as image:
                output = BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                self.send_bytes(output.getvalue(), "image/png")
                return
        except Exception:
            logger.warning("Could not convert preview image for web UI: %s", file_path, exc_info=True)

        self.send_error(415)

    def send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str, port: int, resource_dir: Path, data_dir: Path) -> ThreadingHTTPServer:
    state = AppState(resource_dir, data_dir)

    class BoundRequestHandler(RequestHandler):
        pass

    BoundRequestHandler.state = state
    return ThreadingHTTPServer((host, port), BoundRequestHandler)
