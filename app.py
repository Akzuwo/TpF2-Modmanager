import argparse
import logging
import sys
from pathlib import Path

from helpers.config_helper import load_config
from helpers.logging_helper import configure_logging
from web_backend.server import create_server


def get_runtime_paths() -> tuple[Path, Path]:
    if getattr(sys, "frozen", False):
        resource_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        data_dir = Path(sys.executable).resolve().parent
        return resource_dir, data_dir

    project_dir = Path(__file__).resolve().parent
    return project_dir, project_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the TpF2 Modmanager backend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--resource-dir", default="")
    args = parser.parse_args()

    resource_dir, data_dir = get_runtime_paths()
    if args.resource_dir:
        resource_dir = Path(args.resource_dir)
    if args.data_dir:
        data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(data_dir / "config.json")
    configure_logging(data_dir, bool(config.get("debug_logging_enabled", False)))

    server = create_server(args.host, args.port, resource_dir, data_dir)
    logging.getLogger(__name__).info(
        "Backend listening on http://%s:%s", args.host, server.server_port
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
