import json
from pathlib import Path

APP_LANGS = ["de", "en"]


class I18N:
    def __init__(self, strings_path: Path, language: str = "de") -> None:
        self._strings_path = strings_path
        self._data = self._load_strings()
        self.language = language if language in APP_LANGS else "de"

    def _load_strings(self) -> dict:
        try:
            payload = json.loads(self._strings_path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    def set_language(self, language: str) -> None:
        self.language = language if language in APP_LANGS else "de"

    def t(self, key: str, **kwargs) -> str:
        de_block = self._data.get("de", {})
        block = self._data.get(self.language, {})
        text = block.get(key, de_block.get(key, key))
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

