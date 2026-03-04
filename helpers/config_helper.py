import json
from pathlib import Path

DEFAULT_CONFIG = {
    "mods_path": "",
    "language": "de",
    "fallback_language": "en",
    "app_language": "de",
    "deepl_api_key": "",
}


def load_config(path: Path) -> dict:
    if not path.exists():
        save_config(path, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Config is not a dict")
    except Exception:
        return dict(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    return merged


def save_config(path: Path, config: dict) -> None:
    payload = dict(DEFAULT_CONFIG)
    payload.update({k: v for k, v in config.items() if k in DEFAULT_CONFIG})
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
