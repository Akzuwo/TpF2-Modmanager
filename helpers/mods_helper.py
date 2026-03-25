import copy
import hashlib
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from helpers.deepl_helper import DeepLClient

SUPPORTED_MOD_LANGS = ["de", "en", "es", "it"]
LANG_ALIASES = {
    "de": ["de", "de_de", "deutsch", "ger"],
    "en": ["en", "en_us", "en_gb", "eng", "english"],
    "es": ["es", "es_es", "spa", "spanish", "espanol"],
    "it": ["it", "it_it", "ita", "italian", "italiano"],
}

_MOD_PARSE_CACHE: dict[tuple[str, int, int, str, str], dict] = {}
_MOD_PARSE_CACHE_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def _build_mod_cache_key(file_path: Path, primary_lang: str, fallback_lang: str) -> tuple[str, int, int, str, str] | None:
    try:
        stat = file_path.stat()
    except Exception:
        return None
    return (str(file_path), int(stat.st_mtime_ns), int(stat.st_size), primary_lang, fallback_lang)


def _get_mod_cache(cache_key: tuple[str, int, int, str, str] | None) -> dict | None:
    if cache_key is None:
        return None
    with _MOD_PARSE_CACHE_LOCK:
        item = _MOD_PARSE_CACHE.get(cache_key)
    if item is None:
        return None
    return copy.deepcopy(item)


def _set_mod_cache(cache_key: tuple[str, int, int, str, str] | None, payload: dict) -> None:
    if cache_key is None:
        return
    with _MOD_PARSE_CACHE_LOCK:
        _MOD_PARSE_CACHE[cache_key] = copy.deepcopy(payload)


def normalize_lang_code(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def canonical_lang_code(lang: str) -> str:
    normalized = normalize_lang_code(lang)
    for code, aliases in LANG_ALIASES.items():
        if normalized == code or normalized in aliases:
            return code
    return normalized


def read_text_with_fallback(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1", errors="ignore")


def extract_balanced_block(text: str, open_index: int) -> str:
    depth = 0
    in_string = False
    string_char = ""
    escaped = False

    for index in range(open_index, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_char:
                in_string = False
            continue

        if char in ('"', "'"):
            in_string = True
            string_char = char
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index:index + 1]

    return text[open_index:]


def extract_info_block(lua_text: str) -> str:
    match = re.search(r"\binfo\s*=\s*\{", lua_text)
    if not match:
        return lua_text
    return extract_balanced_block(lua_text, match.end() - 1)


def extract_return_table(lua_text: str) -> str:
    match = re.search(r"\breturn\s*\{", lua_text)
    if not match:
        return ""
    return extract_balanced_block(lua_text, match.end() - 1)


def extract_assigned_table(lua_text: str, variable_name: str) -> str:
    match = re.search(rf"\b(?:local\s+)?{re.escape(variable_name)}\s*=\s*\{{", lua_text)
    if not match:
        return ""
    return extract_balanced_block(lua_text, match.end() - 1)


def split_top_level_lua_entries(table_text: str) -> list[str]:
    text = table_text.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]

    entries = []
    current = []
    depth = 0
    in_string = False
    in_long_string = False
    string_char = ""
    escaped = False

    i = 0
    while i < len(text):
        char = text[i]
        next_char = text[i + 1] if i + 1 < len(text) else ""

        if not in_string and not in_long_string and char == "-" and next_char == "-":
            i += 2
            while i < len(text) and text[i] != "\n":
                i += 1
            continue

        if in_long_string:
            current.append(char)
            if char == "]" and next_char == "]":
                current.append(next_char)
                in_long_string = False
                i += 2
                continue
            i += 1
            continue

        if in_string:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_char:
                in_string = False
            i += 1
            continue

        if char == "[" and next_char == "[":
            in_long_string = True
            current.append(char)
            current.append(next_char)
            i += 2
            continue

        if char in ('"', "'"):
            in_string = True
            string_char = char
            current.append(char)
            i += 1
            continue

        if char == "{":
            depth += 1
            current.append(char)
            i += 1
            continue

        if char == "}":
            depth = max(0, depth - 1)
            current.append(char)
            i += 1
            continue

        if char in {",", ";"} and depth == 0:
            part = "".join(current).strip()
            if part:
                entries.append(part)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    last = "".join(current).strip()
    if last:
        entries.append(last)

    return entries


def unescape_lua_string(value: str) -> str:
    value = value.replace("\\n", "\n")
    value = value.replace("\\t", "\t")
    value = value.replace('\\"', '"')
    value = value.replace("\\'", "'")
    value = value.replace("\\\\", "\\")
    return value


def clean_lua_value(value: str) -> str:
    value = value.strip().rstrip(",").strip()

    wrapped_match = re.fullmatch(r'_\(\s*"([^"]+)"\s*\)', value)
    if wrapped_match:
        return wrapped_match.group(1)

    wrapped_match = re.fullmatch(r"_\(\s*'([^']+)'\s*\)", value)
    if wrapped_match:
        return wrapped_match.group(1)

    wrapped_match = re.fullmatch(r"_\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", value)
    if wrapped_match:
        return wrapped_match.group(1)

    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return unescape_lua_string(value[1:-1])

    return value


def parse_info_fields(info_block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for entry in split_top_level_lua_entries(info_block):
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)\s*$", entry, flags=re.S)
        if not match:
            continue
        fields[match.group(1)] = clean_lua_value(match.group(2))
    return fields


def split_lua_statements(text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []

    in_string = False
    in_long_string = False
    string_char = ""
    escaped = False
    paren_depth = 0
    brace_depth = 0
    bracket_depth = 0

    i = 0
    while i < len(text):
        char = text[i]
        next_char = text[i + 1] if i + 1 < len(text) else ""

        if in_long_string:
            current.append(char)
            if char == "]" and next_char == "]":
                current.append(next_char)
                in_long_string = False
                i += 2
                continue
            i += 1
            continue

        if in_string:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_char:
                in_string = False
            i += 1
            continue

        if char == "[" and next_char == "[":
            in_long_string = True
            current.append(char)
            current.append(next_char)
            i += 2
            continue

        if char in ('"', "'"):
            in_string = True
            string_char = char
            current.append(char)
            i += 1
            continue

        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)

        if (char == "\n" or char == ";") and paren_depth == 0 and brace_depth == 0 and bracket_depth == 0:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def split_lua_concat_expression(expr: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []

    in_string = False
    string_char = ""
    escaped = False
    depth = 0

    i = 0
    while i < len(expr):
        char = expr[i]

        if in_string:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_char:
                in_string = False
            i += 1
            continue

        if char in ('"', "'"):
            in_string = True
            string_char = char
            current.append(char)
            i += 1
            continue

        if char in "([{":
            depth += 1
            current.append(char)
            i += 1
            continue

        if char in ")]}":
            depth = max(0, depth - 1)
            current.append(char)
            i += 1
            continue

        if char == "." and i + 1 < len(expr) and expr[i + 1] == "." and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            i += 2
            continue

        current.append(char)
        i += 1

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)

    return parts


def eval_lua_expression(expr: str, variables: dict[str, str]) -> str | None:
    value = expr.strip().rstrip(",").strip()
    if not value:
        return None

    while value.startswith("(") and value.endswith(")"):
        inner = value[1:-1].strip()
        if not inner:
            break

        depth = 0
        balanced = True
        in_string = False
        string_char = ""
        escaped = False
        for idx, char in enumerate(value):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == string_char:
                    in_string = False
                continue
            if char in ('"', "'"):
                in_string = True
                string_char = char
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and idx != len(value) - 1:
                    balanced = False
                    break
        if balanced:
            value = inner
            continue
        break

    for pattern in [
        r'"((?:[^"\\]|\\.)*)"',
        r"'((?:[^'\\]|\\.)*)'",
        r"\[\[([\s\S]*?)\]\]",
    ]:
        match = re.fullmatch(pattern, value, flags=re.S)
        if match:
            return unescape_lua_string(match.group(1))

    wrapped = re.fullmatch(r"_\(\s*(.+?)\s*\)", value, flags=re.S)
    if wrapped:
        return eval_lua_expression(wrapped.group(1), variables)

    concat_parts = split_lua_concat_expression(value)
    if len(concat_parts) > 1:
        resolved: list[str] = []
        for part in concat_parts:
            piece = eval_lua_expression(part, variables)
            if piece is None:
                return None
            resolved.append(piece)
        return "".join(resolved)

    identifier = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)", value)
    if identifier:
        name = identifier.group(1)
        return variables.get(name, name)

    cleaned = clean_lua_value(value)
    if cleaned != value:
        return cleaned

    return None


def parse_lua_table_entry(entry: str) -> tuple[str | None, str | None]:
    line = entry.strip()
    if not line:
        return None, None

    if line.startswith("["):
        depth = 0
        in_string = False
        string_char = ""
        escaped = False
        end_index = -1

        for idx, char in enumerate(line):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == string_char:
                    in_string = False
                continue

            if char in ('"', "'"):
                in_string = True
                string_char = char
                continue

            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    end_index = idx
                    break

        if end_index == -1:
            return None, None

        key_expr = line[1:end_index].strip()
        rest = line[end_index + 1 :].lstrip()
        if not rest.startswith("="):
            return None, None

        value_expr = rest[1:].strip()
        return key_expr, value_expr

    match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)\s*$", line, flags=re.S)
    if not match:
        return None, None

    return match.group(1), match.group(2)


def parse_lua_string_table(table_text: str, variables: dict[str, str]) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for entry in split_top_level_lua_entries(table_text):
        key_expr, value_expr = parse_lua_table_entry(entry)
        if key_expr is None or value_expr is None:
            continue

        key = eval_lua_expression(key_expr, variables)
        value = eval_lua_expression(value_expr, variables)
        if key is not None and value is not None:
            mapping[str(key)] = value

    return mapping


def parse_lua_variables(text: str) -> dict[str, str]:
    variables: dict[str, str] = {}

    for statement in split_lua_statements(text):
        if statement.startswith("return"):
            continue
        if statement.startswith("function") or statement.startswith("local function") or statement.startswith("end"):
            continue

        match = re.match(r"\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)\s*$", statement, flags=re.S)
        if not match:
            continue

        name = match.group(1)
        expr = match.group(2)
        resolved = eval_lua_expression(expr, variables)
        if resolved is not None:
            variables[name] = resolved

    return variables


def _is_probable_lang_key(key: str) -> bool:
    normalized = normalize_lang_code(key)
    if normalized in LANG_ALIASES:
        return True
    for aliases in LANG_ALIASES.values():
        if normalized in aliases:
            return True
    if re.fullmatch(r"[a-z]{2,3}(?:_[a-z0-9]{2,8})?", normalized):
        return True
    return False


def parse_strings_lua(file_path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    text = read_text_with_fallback(file_path)

    return_match = re.search(r"\breturn\s*\{", text)
    return_name_match = re.search(r"\breturn\s+([A-Za-z_][A-Za-z0-9_]*)\b", text)
    preamble_end = return_match.start() if return_match else return_name_match.start() if return_name_match else len(text)
    preamble = text[:preamble_end]
    variables = parse_lua_variables(preamble)

    table = extract_return_table(text)
    if not table and return_name_match:
        table = extract_assigned_table(text, return_name_match.group(1))
    if not table:
        return {}, variables

    lang_tables: dict[str, dict[str, str]] = {}
    top_level: dict[str, str] = dict(variables)

    for entry in split_top_level_lua_entries(table):
        key_expr, raw_value = parse_lua_table_entry(entry)
        if key_expr is None or raw_value is None:
            continue

        resolved_key = eval_lua_expression(key_expr, variables)
        if resolved_key is None:
            continue

        key = str(resolved_key)
        raw_value = raw_value.strip()
        if raw_value.startswith("{"):
            if _is_probable_lang_key(key):
                lang_key = canonical_lang_code(key)
                lang_tables.setdefault(lang_key, {}).update(parse_lua_string_table(raw_value, variables))
        else:
            parsed = eval_lua_expression(raw_value, variables)
            if parsed is not None:
                top_level[key] = parsed

    return lang_tables, top_level


def parse_strings_json(file_path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    try:
        payload = json.loads(read_text_with_fallback(file_path))
    except Exception:
        logger.warning("Could not parse JSON strings file: %s", file_path, exc_info=True)
        return {}, {}

    if not isinstance(payload, dict):
        return {}, {}

    lang_tables: dict[str, dict[str, str]] = {}
    top_level: dict[str, str] = {}

    for key, value in payload.items():
        if isinstance(value, str):
            top_level[str(key)] = value
        elif isinstance(value, dict):
            table: dict[str, str] = {}
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, str):
                    table[str(sub_key)] = sub_value
            if table:
                lang_tables.setdefault(canonical_lang_code(str(key)), {}).update(table)

    return lang_tables, top_level


def merge_translation_payload(all_lang_tables: dict[str, dict[str, str]], all_top_level: dict[str, str], lang_tables: dict[str, dict[str, str]], top_level: dict[str, str]) -> None:
    for lang, values in lang_tables.items():
        all_lang_tables.setdefault(lang, {}).update(values)
    all_top_level.update(top_level)


def build_translation_map(all_lang_tables: dict[str, dict[str, str]], all_top_level: dict[str, str], primary_lang: str, fallback_lang: str) -> dict:
    available_langs = sorted(all_lang_tables.keys())
    primary = canonical_lang_code(primary_lang)
    fallback = canonical_lang_code(fallback_lang)

    selected = ""
    if available_langs:
        for candidate in [primary, fallback, "en"]:
            if candidate in available_langs:
                selected = candidate
                break
        if not selected:
            selected = available_langs[0]

    mapping = dict(all_top_level)
    if selected:
        mapping.update(all_lang_tables.get(selected, {}))
        mapping.update(all_top_level)

    notice_key = ""
    notice_params: dict[str, str] = {}
    if selected and selected != primary:
        if selected == fallback:
            notice_key = "notice_translation_missing_fallback"
            notice_params = {"primary": primary, "selected": selected}
        elif selected == "en":
            notice_key = "notice_translation_missing_english"
            notice_params = {"primary": primary, "fallback": fallback}
        elif len(available_langs) == 1:
            notice_key = "notice_translation_only_language"
            notice_params = {"primary": primary, "selected": selected}
        else:
            notice_key = "notice_translation_other_language"
            notice_params = {"primary": primary, "fallback": fallback, "selected": selected}

    return {
        "map": mapping,
        "available_languages": available_langs,
        "effective_language": selected,
        "notice": "",
        "notice_key": notice_key,
        "notice_params": notice_params,
    }


def load_mod_translations(mod_dir: Path, primary_lang: str, fallback_lang: str) -> dict:
    all_lang_tables: dict[str, dict[str, str]] = {}
    all_top_level: dict[str, str] = {}

    strings_lua = mod_dir / "strings.lua"
    if strings_lua.exists():
        logger.debug("Loading mod-local strings.lua for %s", mod_dir.name)
        lang_tables, top_level = parse_strings_lua(strings_lua)
        merge_translation_payload(all_lang_tables, all_top_level, lang_tables, top_level)

    strings_json = mod_dir / "strings.json"
    if strings_json.exists():
        logger.debug("Loading mod-local strings.json for %s", mod_dir.name)
        lang_tables, top_level = parse_strings_json(strings_json)
        merge_translation_payload(all_lang_tables, all_top_level, lang_tables, top_level)

    for candidate in mod_dir.glob("strings*.json"):
        if candidate.name.lower() == "strings.json":
            continue
        lang_tables, top_level = parse_strings_json(candidate)
        merge_translation_payload(all_lang_tables, all_top_level, lang_tables, top_level)

    strings_dir = mod_dir / "strings"
    if strings_dir.is_dir():
        for candidate in sorted(strings_dir.rglob("*.json")):
            lang_tables, top_level = parse_strings_json(candidate)
            merge_translation_payload(all_lang_tables, all_top_level, lang_tables, top_level)
        for candidate in sorted(strings_dir.rglob("*.lua")):
            lang_tables, top_level = parse_strings_lua(candidate)
            merge_translation_payload(all_lang_tables, all_top_level, lang_tables, top_level)

    payload = build_translation_map(all_lang_tables, all_top_level, primary_lang, fallback_lang)
    payload["namespace"] = mod_dir.name
    payload["top_level"] = dict(all_top_level)
    payload["language_tables"] = copy.deepcopy(all_lang_tables)
    return payload


def resolve_localized_value(value: str, translation_payload: dict | None, field_name: str = "") -> str:
    if value is None:
        return ""

    candidate = str(value).strip()
    if not candidate:
        return ""

    translations = (translation_payload or {}).get("map", {}) or {}
    namespace = (translation_payload or {}).get("namespace", "") or "unknown"
    candidates = [
        candidate,
        candidate.strip("\"'"),
        candidate.lstrip("$"),
        candidate.strip("\"'").lstrip("$"),
    ]
    for key in candidates:
        if key in translations:
            resolved = translations[key]
            logger.debug("Resolved string key '%s' in namespace '%s' for field '%s'", key, namespace, field_name or "?")
            return resolved

    if candidate.startswith("_(") and candidate.endswith(")"):
        logger.warning("Unresolved localized expression '%s' in namespace '%s'", candidate, namespace)
        return candidate[2:-1].strip().strip("\"'")

    if candidate in {"name", "mod_name", "description", "desc"}:
        logger.debug("String key '%s' missing in namespace '%s'; using raw fallback", candidate, namespace)

    return candidate


def parse_dependencies(info_block: str) -> list[str]:
    match = re.search(r"\bdependencies\s*=\s*\{", info_block)
    if not match:
        return []
    dep_block = extract_balanced_block(info_block, match.end() - 1)
    deps: list[str] = []
    for entry in split_top_level_lua_entries(dep_block):
        cleaned = clean_lua_value(entry)
        if cleaned:
            deps.append(cleaned)
    return deps


def dependency_key(dep: str) -> str:
    return dep.split()[0].strip()


def find_field(text: str, field: str) -> str:
    patterns = [
        rf"\b{re.escape(field)}\s*=\s*_\(\s*\"([^\"]+)\"\s*\)",
        rf"\b{re.escape(field)}\s*=\s*_\(\s*'([^']+)'\s*\)",
        rf"\b{re.escape(field)}\s*=\s*\"([^\"]+)\"",
        rf"\b{re.escape(field)}\s*=\s*'([^']+)'",
        rf"\b{re.escape(field)}\s*=\s*([\w\.-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def parse_mod_lua(file_path: Path, primary_lang: str, fallback_lang: str, deepl_client: DeepLClient | None = None) -> dict:
    cache_key = _build_mod_cache_key(file_path, primary_lang, fallback_lang)
    cached = _get_mod_cache(cache_key)
    if cached is not None:
        return cached
    logger.debug("Parsing mod.lua: %s", file_path)
    content = read_text_with_fallback(file_path)
    info_block = extract_info_block(content)
    raw_fields = parse_info_fields(info_block)

    trans_info = load_mod_translations(file_path.parent, primary_lang, fallback_lang)
    translations = trans_info["map"]
    resolved_fields = {k: resolve_localized_value(v, trans_info, k) for k, v in raw_fields.items()}

    name = resolved_fields.get("name") or raw_fields.get("name") or file_path.parent.name

    author = ""
    authors_table = re.search(r"\bauthors\s*=\s*\{([\s\S]*?)\}\s*,", info_block)
    if authors_table:
        author = find_field(authors_table.group(1), "name")
    if not author:
        author = raw_fields.get("author", "")
    author = resolve_localized_value(author, trans_info, "author") if author else ""
    if not author:
        author = "Unbekannt"

    version = raw_fields.get("version", "")
    major = raw_fields.get("majorVersion", "")
    minor = raw_fields.get("minorVersion", "")
    if not version:
        if major and minor:
            version = f"{major}.{minor}"
        elif minor:
            version = minor
        elif major:
            version = major
        else:
            version = "Unbekannt"

    description = resolved_fields.get("description", raw_fields.get("description", ""))
    deepl_error = ""
    description_translated = description
    if deepl_client and deepl_client.enabled and description:
        description_translated, deepl_error = deepl_client.translate(description, primary_lang)

    result = {
        "id": file_path.parent.name,
        "name": name,
        "author": author,
        "version": version,
        "path": str(file_path.parent),
        "mod_lua": str(file_path),
        "description": description,
        "description_translated": description_translated,
        "deepl_error": deepl_error,
        "raw_fields": raw_fields,
        "resolved_fields": resolved_fields,
        "translations": translations,
        "translation_namespace": trans_info.get("namespace", file_path.parent.name),
        "translation_available_languages": trans_info["available_languages"],
        "translation_effective_language": trans_info["effective_language"],
        "translation_notice": trans_info["notice"],
        "translation_notice_key": trans_info.get("notice_key", ""),
        "translation_notice_params": trans_info.get("notice_params", {}),
        "dependencies": parse_dependencies(info_block),
        "dependency_links": [],
        "required_by": [],
    }
    logger.debug(
        "Parsed mod '%s' (%s) with translation namespace '%s' and language '%s'",
        result["name"],
        result["id"],
        result["translation_namespace"],
        result["translation_effective_language"],
    )
    _set_mod_cache(cache_key, result)
    return copy.deepcopy(result)


def resolve_dependency_graph(mods: list[dict]) -> None:
    by_id: dict[str, dict] = {m.get("id", ""): m for m in mods if m.get("id", "")}

    for mod in mods:
        links = []
        for dep in mod.get("dependencies", []):
            dep_id = dependency_key(dep)
            links.append({"raw": dep, "id": dep_id, "target": by_id.get(dep_id)})
        mod["dependency_links"] = links
        mod["required_by"] = []

    for mod in mods:
        for dep in mod.get("dependency_links", []):
            target = dep.get("target")
            if target:
                target.setdefault("required_by", []).append(mod)


def _build_mod_fallback(mod_lua: Path, mod_folder: Path | None = None) -> dict:
    folder = mod_folder if mod_folder is not None else mod_lua.parent
    logger.warning("Using fallback metadata for unreadable mod: %s", folder)
    return {
        "id": folder.name,
        "name": folder.name,
        "author": "Fehler beim Lesen",
        "version": "-",
        "path": str(folder),
        "mod_lua": str(mod_lua),
        "description": "",
        "description_translated": "",
        "deepl_error": "",
        "raw_fields": {},
        "resolved_fields": {},
        "translations": {},
        "translation_namespace": folder.name,
        "translation_available_languages": [],
        "translation_effective_language": "",
        "translation_notice": "",
        "translation_notice_key": "",
        "translation_notice_params": {},
        "dependencies": [],
        "dependency_links": [],
        "required_by": [],
    }


def _find_best_mod_lua_per_folder(mod_root: Path) -> tuple[list[Path], dict[str, Path]]:
    folders = [path for path in mod_root.iterdir() if path.is_dir()]
    folders.sort(key=lambda path: path.name.lower())

    best: dict[str, tuple[Path, int]] = {}
    for mod_lua in mod_root.rglob("mod.lua"):
        try:
            rel = mod_lua.relative_to(mod_root)
        except ValueError:
            continue

        if not rel.parts:
            continue

        top = rel.parts[0]
        rank = len(rel.parts)
        prev = best.get(top)
        if prev is None or rank < prev[1]:
            best[top] = (mod_lua, rank)

    mapping = {name: data[0] for name, data in best.items()}
    return folders, mapping


def _find_best_mod_lua_in_directory(root: Path) -> Path | None:
    best: tuple[Path, int] | None = None
    for mod_lua in root.rglob("mod.lua"):
        try:
            rank = len(mod_lua.relative_to(root).parts)
        except ValueError:
            continue
        if best is None or rank < best[1]:
            best = (mod_lua, rank)
    return best[0] if best else None


def scan_mods_parallel(
    mod_root: Path,
    primary_lang: str,
    fallback_lang: str,
    deepl_client: DeepLClient | None = None,
    max_workers: int | None = None,
    progress_callback=None,
    resolve_dependencies: bool = True,
) -> list[dict]:
    if not mod_root.exists() or not mod_root.is_dir():
        logger.warning("Scan skipped because mod root is invalid: %s", mod_root)
        return []

    folders, mod_lua_by_folder = _find_best_mod_lua_per_folder(mod_root)
    total = len(folders)
    logger.info("Scanning %s mod folders in %s", total, mod_root)
    if progress_callback:
        progress_callback(0, total)

    if total == 0:
        return []

    mods: list[dict] = []
    processed = 0

    if max_workers is None:
        cpu = os.cpu_count() or 4
        max_workers = max(2, min(16, cpu * 2))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_context = {}

        for folder in folders:
            mod_lua = mod_lua_by_folder.get(folder.name)
            if mod_lua is None:
                processed += 1
                if progress_callback:
                    progress_callback(processed, total)
                continue

            future = executor.submit(
                parse_mod_lua,
                mod_lua,
                primary_lang,
                fallback_lang,
                deepl_client,
            )
            future_to_context[future] = (folder, mod_lua)

        for future in as_completed(future_to_context):
            folder, mod_lua = future_to_context[future]
            try:
                mods.append(future.result())
            except Exception:
                logger.exception("Failed to parse mod %s", folder)
                mods.append(_build_mod_fallback(mod_lua, folder))

            processed += 1
            if progress_callback:
                progress_callback(processed, total)

    mods.sort(key=lambda item: item.get("name", "").lower())
    if resolve_dependencies:
        resolve_dependency_graph(mods)
    logger.info("Finished scan for %s: %s mods", mod_root, len(mods))
    return mods


def scan_mods(mod_root: Path, primary_lang: str, fallback_lang: str, deepl_client: DeepLClient | None = None) -> list[dict]:
    return scan_mods_parallel(mod_root, primary_lang, fallback_lang, deepl_client=deepl_client)


def find_preview_image(mod_path: Path) -> Path | None:
    preferred_suffixes = [".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".webp"]
    preferred_names = [f"image_00{suffix}" for suffix in preferred_suffixes]

    for name in preferred_names:
        candidate = mod_path / name
        if candidate.is_file():
            return candidate

    root_files = sorted(
        (candidate for candidate in mod_path.iterdir() if candidate.is_file()),
        key=lambda candidate: candidate.name.lower(),
    )
    for name in preferred_names:
        for candidate in root_files:
            if candidate.name.lower() == name:
                return candidate

    matches: list[Path] = []
    for candidate in mod_path.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.stem.lower() != "image_00":
            continue
        if candidate.suffix.lower() not in preferred_suffixes:
            continue
        matches.append(candidate)

    if not matches:
        return None

    suffix_rank = {suffix: index for index, suffix in enumerate(preferred_suffixes)}
    matches.sort(
        key=lambda candidate: (
            len(candidate.relative_to(mod_path).parts),
            suffix_rank.get(candidate.suffix.lower(), len(preferred_suffixes)),
            str(candidate).lower(),
        )
    )
    return matches[0]


def find_mod_link(fields: dict[str, str]) -> str:
    for key in ["url", "website", "web", "forum", "source", "steamUrl", "workshopUrl"]:
        value = fields.get(key, "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value

    steam_id = fields.get("steamId", "").strip()
    if steam_id.isdigit():
        return f"https://steamcommunity.com/sharedfiles/filedetails/?id={steam_id}"

    for value in fields.values():
        match = re.search(r"https?://[^\s\"']+", value)
        if match:
            return match.group(0)
    return ""


TRACKED_ASSET_SUFFIXES = {
    ".lua",
    ".mdl",
    ".msh",
    ".mtl",
    ".con",
    ".lua5",
    ".png",
    ".dds",
    ".tga",
}


def normalize_compare_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def tokenize_compare_text(value: str) -> set[str]:
    return {token for token in normalize_compare_text(value).split() if len(token) >= 3}


def safe_relative_paths(mod_path: Path) -> list[str]:
    paths: list[str] = []
    if not mod_path.exists():
        return paths
    try:
        for file_path in mod_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(mod_path).as_posix().lower()
            paths.append(rel)
    except Exception:
        logger.exception("Failed to build relative path list for %s", mod_path)
    return paths


def build_mod_signature(mod: dict) -> dict:
    cached = mod.get("_signature")
    if isinstance(cached, dict):
        return cached

    mod_path = Path(mod.get("path", ""))
    relative_paths = safe_relative_paths(mod_path)
    tracked_paths = {path for path in relative_paths if Path(path).suffix.lower() in TRACKED_ASSET_SUFFIXES}
    tracked_names = {Path(path).name for path in tracked_paths}
    dir_names = {Path(path).parent.as_posix() for path in relative_paths if "/" in path}
    folder_name = normalize_compare_text(mod_path.name)
    mod_name = normalize_compare_text(mod.get("name", ""))
    author = normalize_compare_text(mod.get("author", ""))
    structure_seed = "\n".join(sorted(relative_paths))
    structure_hash = hashlib.sha1(structure_seed.encode("utf-8", errors="ignore")).hexdigest() if structure_seed else ""
    signature = {
        "folder_name": folder_name,
        "name": mod_name,
        "author": author,
        "folder_tokens": tokenize_compare_text(mod_path.name),
        "name_tokens": tokenize_compare_text(mod.get("name", "")),
        "author_tokens": tokenize_compare_text(mod.get("author", "")),
        "relative_paths": set(relative_paths),
        "tracked_paths": tracked_paths,
        "tracked_names": tracked_names,
        "dir_names": dir_names,
        "structure_hash": structure_hash,
        "file_count": len(relative_paths),
    }
    mod["_signature"] = signature
    logger.debug("Built signature for mod '%s' with %s files", mod.get("name", mod_path.name), len(relative_paths))
    return signature


def similarity_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    return intersection / max(1, min(len(left), len(right)))


def jaccard_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def parse_workshop_ids_from_acf(acf_path: Path) -> list[str]:
    if not acf_path.exists():
        logger.warning("appworkshop file does not exist: %s", acf_path)
        return []
    try:
        text = read_text_with_fallback(acf_path)
    except Exception:
        logger.exception("Could not read appworkshop file: %s", acf_path)
        return []

    ids = sorted(set(re.findall(r'"(\d{6,})"\s*\{', text)))
    logger.info("Parsed %s workshop ids from %s", len(ids), acf_path)
    return ids


def remove_workshop_item_from_acf(acf_path: Path, workshop_id: str) -> bool:
    if not acf_path.exists():
        return False

    try:
        text = read_text_with_fallback(acf_path)
    except Exception:
        logger.exception("Could not read appworkshop file for update: %s", acf_path)
        return False

    pattern = re.compile(rf'(\s*)"{re.escape(workshop_id)}"\s*\{{', flags=re.M)
    changed = False
    while True:
        match = pattern.search(text)
        if not match:
            break
        block = extract_balanced_block(text, match.end() - 1)
        start = match.start()
        end = match.end() - 1 + len(block)
        text = text[:start] + text[end:]
        changed = True

    if not changed:
        return False

    try:
        acf_path.write_text(text, encoding="utf-8")
        logger.info("Removed workshop id %s from %s", workshop_id, acf_path)
        return True
    except Exception:
        logger.exception("Could not write updated appworkshop file: %s", acf_path)
        return False


def _collect_workshop_folder_candidates(workshop_root: Path, workshop_ids: list[str]) -> dict[str, Path]:
    candidates: dict[str, Path] = {}
    if not workshop_root.exists() or not workshop_root.is_dir():
        return candidates

    for workshop_id in workshop_ids:
        direct = workshop_root / workshop_id
        if direct.is_dir():
            candidates[workshop_id] = direct
            continue

        alt = workshop_root / f"content_{workshop_id}"
        if alt.is_dir():
            candidates[workshop_id] = alt

    return candidates


def scan_workshop_mods(
    workshop_root: Path,
    acf_path: Path | None,
    primary_lang: str,
    fallback_lang: str,
    progress_callback=None,
    resolve_dependencies: bool = True,
) -> list[dict]:
    ids = parse_workshop_ids_from_acf(acf_path) if acf_path else []
    folders = _collect_workshop_folder_candidates(workshop_root, ids)
    if not folders and workshop_root.exists():
        for child in sorted(workshop_root.iterdir(), key=lambda item: item.name.lower()):
            if child.is_dir() and child.name.isdigit():
                folders[child.name] = child

    total = len(folders)
    if progress_callback:
        progress_callback(0, total)
    if total == 0:
        logger.warning("No workshop mods found in %s", workshop_root)
        return []

    max_workers = max(2, min(16, (os.cpu_count() or 4) * 2))
    workshop_mods: list[dict] = []
    processed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for workshop_id, folder in folders.items():
            mod_lua = _find_best_mod_lua_in_directory(folder) or (folder / "mod.lua")
            future = executor.submit(parse_mod_lua, mod_lua, primary_lang, fallback_lang, None)
            future_map[future] = (workshop_id, folder, mod_lua)

        for future in as_completed(future_map):
            workshop_id, folder, mod_lua = future_map[future]
            try:
                mod = future.result()
            except Exception:
                logger.exception("Failed to parse workshop mod %s", workshop_id)
                mod = _build_mod_fallback(mod_lua, folder)
            mod["workshop_id"] = workshop_id
            mod["source"] = "workshop"
            workshop_mods.append(mod)
            processed += 1
            if progress_callback:
                progress_callback(processed, total)

    if resolve_dependencies:
        resolve_dependency_graph(workshop_mods)
    logger.info("Scanned %s workshop mods in %s", len(workshop_mods), workshop_root)
    return workshop_mods


def build_duplicate_candidates(local_mods: list[dict], workshop_mods: list[dict]) -> dict[str, list[dict]]:
    all_small = len(local_mods) * len(workshop_mods) <= 4000
    workshop_signatures = {mod["path"]: build_mod_signature(mod) for mod in workshop_mods}
    index_by_token: dict[str, list[dict]] = {}
    for mod in workshop_mods:
        sig = workshop_signatures[mod["path"]]
        tokens = sig["folder_tokens"] | sig["name_tokens"] | sig["author_tokens"] | sig["tracked_names"]
        for token in tokens:
            index_by_token.setdefault(token, []).append(mod)

    candidates: dict[str, list[dict]] = {}
    for mod in local_mods:
        if all_small:
            candidates[mod["path"]] = list(workshop_mods)
            continue
        sig = build_mod_signature(mod)
        tokens = sig["folder_tokens"] | sig["name_tokens"] | sig["author_tokens"] | sig["tracked_names"]
        bucket: dict[str, dict] = {}
        for token in tokens:
            for workshop_mod in index_by_token.get(token, []):
                bucket[workshop_mod["path"]] = workshop_mod
        if not bucket:
            candidates[mod["path"]] = list(workshop_mods)
        else:
            candidates[mod["path"]] = list(bucket.values())
    return candidates


def score_mod_match(local_mod: dict, workshop_mod: dict) -> dict:
    local_sig = build_mod_signature(local_mod)
    workshop_sig = build_mod_signature(workshop_mod)

    folder_score = similarity_ratio(local_sig["folder_name"], workshop_sig["folder_name"])
    name_score = similarity_ratio(local_sig["name"], workshop_sig["name"])
    author_score = similarity_ratio(local_sig["author"], workshop_sig["author"])
    path_overlap = overlap_ratio(local_sig["tracked_paths"], workshop_sig["tracked_paths"])
    asset_overlap = overlap_ratio(local_sig["tracked_names"], workshop_sig["tracked_names"])
    structure_overlap = max(
        jaccard_ratio(local_sig["dir_names"], workshop_sig["dir_names"]),
        1.0 if local_sig["structure_hash"] and local_sig["structure_hash"] == workshop_sig["structure_hash"] else 0.0,
    )

    score = (
        folder_score * 12
        + name_score * 22
        + author_score * 8
        + structure_overlap * 18
        + path_overlap * 28
        + asset_overlap * 12
    )

    reasons: list[str] = []
    if path_overlap >= 0.6:
        reasons.append(f"{int(path_overlap * 100)}% gleiche Asset-/Dateipfade")
    if asset_overlap >= 0.6:
        reasons.append(f"{int(asset_overlap * 100)}% gleiche markante Dateien")
    if name_score >= 0.8:
        reasons.append("Modname sehr aehnlich")
    if folder_score >= 0.8:
        reasons.append("Ordnername sehr aehnlich")
    if author_score >= 0.8 and local_sig["author"]:
        reasons.append("Autor stimmt weitgehend ueberein")
    if structure_overlap >= 0.7:
        reasons.append("Dateistruktur stark aehnlich")

    result = {
        "local_mod": local_mod,
        "workshop_mod": workshop_mod,
        "workshop_id": workshop_mod.get("workshop_id", ""),
        "score": round(score, 1),
        "reason": "; ".join(reasons[:3]) or "Mehrere Metadaten- und Dateimerkmale stimmen ueberein",
        "metrics": {
            "folder_score": folder_score,
            "name_score": name_score,
            "author_score": author_score,
            "path_overlap": path_overlap,
            "asset_overlap": asset_overlap,
            "structure_overlap": structure_overlap,
        },
    }
    logger.debug(
        "Duplicate score %s%%: local='%s' workshop='%s' (%s)",
        result["score"],
        local_mod.get("name", local_mod.get("id", "?")),
        workshop_mod.get("name", workshop_mod.get("id", "?")),
        result["workshop_id"],
    )
    return result


def find_duplicate_mods(
    local_mods: list[dict],
    workshop_mods: list[dict],
    min_score: float = 45.0,
    progress_callback=None,
) -> list[dict]:
    if not local_mods or not workshop_mods:
        return []

    candidates = build_duplicate_candidates(local_mods, workshop_mods)
    jobs: list[tuple[dict, dict]] = []
    for local_mod in local_mods:
        for workshop_mod in candidates.get(local_mod["path"], []):
            if Path(local_mod.get("path", "")).resolve() == Path(workshop_mod.get("path", "")).resolve():
                continue
            jobs.append((local_mod, workshop_mod))

    total = len(jobs)
    if progress_callback:
        progress_callback(0, total)
    if total == 0:
        return []

    results_by_local: dict[str, dict] = {}
    processed = 0
    max_workers = max(2, min(24, (os.cpu_count() or 4) * 2))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(score_mod_match, local_mod, workshop_mod): (local_mod, workshop_mod) for local_mod, workshop_mod in jobs}
        for future in as_completed(future_map):
            processed += 1
            if progress_callback:
                progress_callback(processed, total)
            try:
                result = future.result()
            except Exception:
                logger.exception("Failed to score duplicate candidate")
                continue

            if result["score"] < min_score:
                continue

            local_key = result["local_mod"].get("path", "")
            previous = results_by_local.get(local_key)
            if previous is None or result["score"] > previous["score"]:
                results_by_local[local_key] = result

    results = sorted(results_by_local.values(), key=lambda item: item["score"], reverse=True)
    logger.info("Found %s duplicate candidates >= %s%%", len(results), min_score)
    return results


def delete_mod_folder(mod_path: Path) -> tuple[bool, str]:
    if not mod_path.exists():
        return False, f"Pfad nicht gefunden: {mod_path}"
    try:
        import shutil

        shutil.rmtree(mod_path)
        logger.info("Deleted mod folder: %s", mod_path)
        return True, f"Ordner geloescht: {mod_path.name}"
    except Exception as exc:
        logger.exception("Could not delete mod folder: %s", mod_path)
        return False, str(exc)


def delete_or_unsubscribe_workshop_mod(workshop_mod: dict, acf_path: Path | None = None) -> tuple[bool, str]:
    mod_path = Path(workshop_mod.get("path", ""))
    workshop_id = str(workshop_mod.get("workshop_id", "") or "")
    ok, message = delete_mod_folder(mod_path)
    if not ok:
        return ok, message

    acf_updated = False
    if acf_path and workshop_id:
        acf_updated = remove_workshop_item_from_acf(acf_path, workshop_id)

    if workshop_id and acf_updated:
        return True, f"Workshop-Mod entfernt und appworkshop fuer {workshop_id} aktualisiert"
    if workshop_id:
        return True, f"Workshop-Mod entfernt: {workshop_id}"
    return True, message

