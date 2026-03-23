import logging
import sys
import threading
from pathlib import Path

LOG_FILE_NAME = "modmanager.log"
_EXCEPTION_HOOKS_INSTALLED = False


def get_log_file_path(data_dir: Path) -> Path:
    return data_dir / LOG_FILE_NAME


def _handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
    logger = logging.getLogger("unhandled")
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


def _handle_thread_exception(args) -> None:
    logger = logging.getLogger("threading")
    logger.critical(
        "Unhandled thread exception in %s",
        getattr(args.thread, "name", "unknown"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def install_exception_hooks() -> None:
    global _EXCEPTION_HOOKS_INSTALLED
    if _EXCEPTION_HOOKS_INSTALLED:
        return
    sys.excepthook = _handle_uncaught_exception
    threading.excepthook = _handle_thread_exception
    _EXCEPTION_HOOKS_INSTALLED = True


def configure_logging(data_dir: Path, debug_enabled: bool) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = get_log_file_path(data_dir)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    handlers: list[logging.Handler] = [console_handler]
    if debug_enabled:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        handlers.append(file_handler)

    logging.basicConfig(
        level=logging.DEBUG if debug_enabled else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
        force=True,
    )
    install_exception_hooks()
    logging.getLogger(__name__).info(
        "Logging configured. debug_enabled=%s logfile=%s",
        debug_enabled,
        log_file if debug_enabled else "disabled",
    )
    return log_file
