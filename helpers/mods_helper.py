import copy
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def split_top_level_lua_entries(table_text: str) -> list[str]:
    text = table_text.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]

    entries = []
    current = []
    depth = 0
    in_string = False
    string_char = ""
    escaped = False

    for char in text:
        if in_string:
            current.append(char)
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
            current.append(char)
            continue

        if char == "{":
            depth += 1
            current.append(char)
            continue

        if char == "}":
            depth = max(0, depth - 1)
            current.append(char)
            continue

        if char == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                entries.append(part)
            current = []
            continue

        current.append(char)

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
    string_char = ""
    escaped = False
    paren_depth = 0
    brace_depth = 0
    bracket_depth = 0

    for char in text:
        if in_string:
            current.append(char)
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
            current.append(char)
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
            continue

        current.append(char)

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
        if statement.startswith("function") or statement.startswith("end"):
            continue

        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)\s*$", statement, flags=re.S)
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
    return False


def parse_strings_lua(file_path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    text = read_text_with_fallback(file_path)

    return_match = re.search(r"\breturn\s*\{", text)
    preamble = text[: return_match.start()] if return_match else text
    variables = parse_lua_variables(preamble)

    table = extract_return_table(text)
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
    import json

    try:
        payload = json.loads(read_text_with_fallback(file_path))
    except Exception:
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

    notice = ""
    if selected and selected != primary:
        if selected == fallback:
            notice = f"Uebersetzung fuer '{primary}' fehlt, fallback '{selected}' verwendet."
        elif selected == "en":
            notice = f"Uebersetzung fuer '{primary}'/{fallback} fehlt, fallback 'en' verwendet."
        elif len(available_langs) == 1:
            notice = f"Keine Uebersetzung fuer '{primary}'. Nur '{selected}' verfuegbar."
        else:
            notice = f"Keine Uebersetzung fuer '{primary}'/{fallback}. Verwendet: '{selected}'."

    return {
        "map": mapping,
        "available_languages": available_langs,
        "effective_language": selected,
        "notice": notice,
    }


def load_mod_translations(mod_dir: Path, primary_lang: str, fallback_lang: str) -> dict:
    all_lang_tables: dict[str, dict[str, str]] = {}
    all_top_level: dict[str, str] = {}

    strings_lua = mod_dir / "strings.lua"
    if strings_lua.exists():
        lang_tables, top_level = parse_strings_lua(strings_lua)
        merge_translation_payload(all_lang_tables, all_top_level, lang_tables, top_level)

    strings_json = mod_dir / "strings.json"
    if strings_json.exists():
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

    return build_translation_map(all_lang_tables, all_top_level, primary_lang, fallback_lang)


def resolve_localized_value(value: str, translations: dict[str, str]) -> str:
    candidate = value.strip()
    for key in [candidate, candidate.strip("\"'"), candidate.lstrip("$"), candidate.strip("\"'").lstrip("$")]:
        if key in translations:
            return translations[key]
    return value


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
    content = read_text_with_fallback(file_path)
    info_block = extract_info_block(content)
    raw_fields = parse_info_fields(info_block)

    trans_info = load_mod_translations(file_path.parent, primary_lang, fallback_lang)
    translations = trans_info["map"]
    resolved_fields = {k: resolve_localized_value(v, translations) for k, v in raw_fields.items()}

    name = resolved_fields.get("name") or raw_fields.get("name") or file_path.parent.name

    author = ""
    authors_table = re.search(r"\bauthors\s*=\s*\{([\s\S]*?)\}\s*,", info_block)
    if authors_table:
        author = find_field(authors_table.group(1), "name")
    if not author:
        author = raw_fields.get("author", "")
    author = resolve_localized_value(author, translations) if author else ""
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
        "translation_available_languages": trans_info["available_languages"],
        "translation_effective_language": trans_info["effective_language"],
        "translation_notice": trans_info["notice"],
        "dependencies": parse_dependencies(info_block),
        "dependency_links": [],
        "required_by": [],
    }
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
        "translation_available_languages": [],
        "translation_effective_language": "",
        "translation_notice": "",
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


def scan_mods_parallel(
    mod_root: Path,
    primary_lang: str,
    fallback_lang: str,
    deepl_client: DeepLClient | None = None,
    max_workers: int | None = None,
    progress_callback=None,
) -> list[dict]:
    if not mod_root.exists() or not mod_root.is_dir():
        return []

    folders, mod_lua_by_folder = _find_best_mod_lua_per_folder(mod_root)
    total = len(folders)
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
                mods.append(_build_mod_fallback(mod_lua, folder))

            processed += 1
            if progress_callback:
                progress_callback(processed, total)

    mods.sort(key=lambda item: item.get("name", "").lower())
    resolve_dependency_graph(mods)
    return mods


def scan_mods(mod_root: Path, primary_lang: str, fallback_lang: str, deepl_client: DeepLClient | None = None) -> list[dict]:
    return scan_mods_parallel(mod_root, primary_lang, fallback_lang, deepl_client=deepl_client)


def find_preview_image(mod_path: Path) -> Path | None:
    preferred = ["image_00.tga", "image_00.dds", "image_00.png", "image_00.jpg", "image_00.jpeg"]
    for name in preferred:
        candidate = mod_path / name
        if candidate.exists():
            return candidate
    for candidate in mod_path.glob("image_00.*"):
        if candidate.is_file():
            return candidate
    return None


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

