import json
import urllib.error
import urllib.parse
import urllib.request

try:
    import deepl  # official SDK
    DEEPL_SDK_AVAILABLE = True
except ImportError:
    deepl = None
    DEEPL_SDK_AVAILABLE = False

LANG_TO_DEEPL = {
    "de": "DE",
    "en": "EN",
    "es": "ES",
    "it": "IT",
}


class DeepLClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = (api_key or "").strip()
        self._cache: dict[tuple[str, str], tuple[str, str]] = {}
        self._sdk_client = None

        if self.api_key and DEEPL_SDK_AVAILABLE:
            try:
                self._sdk_client = deepl.DeepLClient(self.api_key)
            except Exception:
                self._sdk_client = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def using_sdk(self) -> bool:
        return self._sdk_client is not None

    def translate(self, text: str, target_lang: str) -> tuple[str, str]:
        clean_text = (text or "").strip()
        if not clean_text:
            return "", ""

        deepl_lang = LANG_TO_DEEPL.get(target_lang.lower())
        if not deepl_lang:
            return clean_text, ""

        if not self.enabled:
            return clean_text, ""

        cache_key = (clean_text, deepl_lang)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Preferred path: official DeepL SDK
        if self._sdk_client is not None:
            try:
                result = self._sdk_client.translate_text(clean_text, target_lang=deepl_lang)
                translated = str(getattr(result, "text", clean_text) or clean_text)
                out = (translated, "")
                self._cache[cache_key] = out
                return out
            except Exception as exc:
                fallback_text, fallback_error = self._translate_via_http(clean_text, deepl_lang)
                if fallback_error:
                    out = (
                        clean_text,
                        f"DeepL SDK Fehler: {exc}; HTTP Fallback Fehler: {fallback_error}",
                    )
                else:
                    out = (fallback_text, "")
                self._cache[cache_key] = out
                return out

        # SDK not available -> fallback to HTTP
        translated, error = self._translate_via_http(clean_text, deepl_lang)
        if error:
            hint = " (pip install deepl)" if not DEEPL_SDK_AVAILABLE else ""
            out = (clean_text, f"DeepL Fehler: {error}{hint}")
        else:
            out = (translated, "")

        self._cache[cache_key] = out
        return out

    def _translate_via_http(self, text: str, target_lang: str) -> tuple[str, str]:
        payload = urllib.parse.urlencode(
            {
                "auth_key": self.api_key,
                "text": text,
                "target_lang": target_lang,
            }
        ).encode("utf-8")

        urls = [
            "https://api-free.deepl.com/v2/translate",
            "https://api.deepl.com/v2/translate",
        ]

        last_error = ""
        for url in urls:
            try:
                request = urllib.request.Request(url, data=payload, method="POST")
                request.add_header("Content-Type", "application/x-www-form-urlencoded")
                with urllib.request.urlopen(request, timeout=12) as response:
                    data = json.loads(response.read().decode("utf-8"))
                translations = data.get("translations", [])
                if translations:
                    translated = str(translations[0].get("text", text))
                    return translated, ""
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="ignore")
                except Exception:
                    detail = str(exc)
                last_error = f"HTTP {exc.code}: {detail}"
            except Exception as exc:
                last_error = str(exc)

        return text, (last_error or "Unbekannter HTTP Fehler")
