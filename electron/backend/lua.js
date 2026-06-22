const fs = require("node:fs");
const path = require("node:path");

const LANG_ALIASES = {
  de: ["de", "de_de", "german"],
  en: ["en", "en_us", "en_gb", "english"],
  es: ["es", "es_es", "spanish"],
  it: ["it", "it_it", "italian"],
  fr: ["fr", "fr_fr", "french"]
};

function readText(filePath) {
  const bytes = fs.readFileSync(filePath);
  let text = bytes.toString("utf8");
  if (text.includes("�")) text = bytes.toString("latin1");
  return text;
}

function extractBalancedBlock(text, openIndex) {
  let depth = 0;
  let quote = "";
  let escaped = false;
  let longString = false;
  for (let index = openIndex; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1] || "";
    if (longString) {
      if (char === "]" && next === "]") { longString = false; index += 1; }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "[" && next === "[") { longString = true; index += 1; continue; }
    if (char === '"' || char === "'") { quote = char; continue; }
    if (char === "{") depth += 1;
    else if (char === "}" && --depth === 0) return text.slice(openIndex, index + 1);
  }
  return text.slice(openIndex);
}

function extractTableAfter(text, expression) {
  const match = expression.exec(text);
  return match ? extractBalancedBlock(text, match.index + match[0].lastIndexOf("{")) : "";
}

function splitTopLevel(tableText) {
  const text = tableText.trim().replace(/^\{/, "").replace(/\}$/, "");
  const entries = [];
  let current = "";
  let depth = 0;
  let quote = "";
  let escaped = false;
  let longString = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1] || "";
    if (!quote && !longString && char === "-" && next === "-") {
      while (index < text.length && text[index] !== "\n") index += 1;
      continue;
    }
    current += char;
    if (longString) {
      if (char === "]" && next === "]") { current += next; longString = false; index += 1; }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === "[" && next === "[") { current += next; longString = true; index += 1; continue; }
    if (char === '"' || char === "'") { quote = char; continue; }
    if ("{([".includes(char)) depth += 1;
    else if ("})]".includes(char)) depth = Math.max(0, depth - 1);
    else if ((char === "," || char === ";") && depth === 0) {
      const entry = current.slice(0, -1).trim();
      if (entry) entries.push(entry);
      current = "";
    }
  }
  if (current.trim()) entries.push(current.trim());
  return entries;
}

function unescapeLua(value) {
  return value.replace(/\\n/g, "\n").replace(/\\t/g, "\t")
    .replace(/\\"/g, '"').replace(/\\'/g, "'").replace(/\\\\/g, "\\");
}

function splitConcat(expression) {
  const parts = [];
  let current = "";
  let quote = "";
  let escaped = false;
  let depth = 0;
  for (let index = 0; index < expression.length; index += 1) {
    const char = expression[index];
    if (quote) {
      current += char;
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === '"' || char === "'") { quote = char; current += char; continue; }
    if ("({[".includes(char)) depth += 1;
    else if (")}]".includes(char)) depth = Math.max(0, depth - 1);
    if (char === "." && expression[index + 1] === "." && depth === 0) {
      parts.push(current.trim()); current = ""; index += 1; continue;
    }
    current += char;
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}

function evaluate(expression, variables = {}) {
  let value = String(expression || "").trim().replace(/,$/, "").trim();
  if (!value) return null;
  const wrapped = value.match(/^_\(\s*([\s\S]+)\s*\)$/);
  if (wrapped) return evaluate(wrapped[1], variables);
  const doubleQuoted = value.match(/^"((?:[^"\\]|\\.)*)"$/s);
  if (doubleQuoted) return unescapeLua(doubleQuoted[1]);
  const singleQuoted = value.match(/^'((?:[^'\\]|\\.)*)'$/s);
  if (singleQuoted) return unescapeLua(singleQuoted[1]);
  const long = value.match(/^\[\[([\s\S]*?)\]\]$/);
  if (long) return long[1];
  const parts = splitConcat(value);
  if (parts.length > 1) {
    const resolved = parts.map((part) => evaluate(part, variables));
    return resolved.some((item) => item === null) ? null : resolved.join("");
  }
  if (/^[A-Za-z_]\w*$/.test(value)) return variables[value] ?? value;
  if (/^-?\d+(?:\.\d+)?$/.test(value)) return value;
  return null;
}

function parseEntry(entry) {
  const bracket = entry.match(/^\s*\[([\s\S]+?)\]\s*=\s*([\s\S]+)$/);
  if (bracket) return [bracket[1], bracket[2]];
  const plain = entry.match(/^\s*([A-Za-z_]\w*)\s*=\s*([\s\S]+)$/);
  return plain ? [plain[1], plain[2]] : [null, null];
}

function parseVariables(text) {
  const variables = {};
  for (const line of text.split(/[\n;]/)) {
    const match = line.match(/^\s*(?:local\s+)?([A-Za-z_]\w*)\s*=\s*(.+)$/);
    if (!match) continue;
    const value = evaluate(match[2], variables);
    if (value !== null) variables[match[1]] = value;
  }
  return variables;
}

function normalizeLanguage(value) {
  const normalized = String(value || "").trim().toLowerCase().replaceAll("-", "_");
  return Object.entries(LANG_ALIASES).find(([, aliases]) => aliases.includes(normalized))?.[0] || normalized;
}

function isLanguage(value) {
  const normalized = normalizeLanguage(value);
  return Object.hasOwn(LANG_ALIASES, normalized) || /^[a-z]{2,3}(?:_[a-z0-9]{2,8})?$/.test(normalized);
}

function parseStringTable(table, variables) {
  const result = {};
  for (const entry of splitTopLevel(table)) {
    const [keyExpr, valueExpr] = parseEntry(entry);
    const key = evaluate(keyExpr, variables);
    const value = evaluate(valueExpr, variables);
    if (key !== null && value !== null) result[String(key)] = value;
  }
  return result;
}

function parseStringsLua(filePath) {
  const text = readText(filePath);
  const returnMatch = /\breturn\s*\{/.exec(text);
  const namedReturn = /\breturn\s+([A-Za-z_]\w*)/.exec(text);
  const preambleEnd = returnMatch?.index ?? namedReturn?.index ?? text.length;
  const variables = parseVariables(text.slice(0, preambleEnd));
  let table = extractTableAfter(text, /\breturn\s*\{/);
  if (!table && namedReturn) table = extractTableAfter(text, new RegExp(`\\b(?:local\\s+)?${namedReturn[1]}\\s*=\\s*\\{`));
  const languages = {};
  const topLevel = { ...variables };
  for (const entry of splitTopLevel(table)) {
    const [keyExpr, valueExpr] = parseEntry(entry);
    const key = evaluate(keyExpr, variables);
    if (key === null || valueExpr === null) continue;
    if (valueExpr.trim().startsWith("{") && isLanguage(key)) {
      const language = normalizeLanguage(key);
      languages[language] = { ...(languages[language] || {}), ...parseStringTable(valueExpr, variables) };
    } else {
      const value = evaluate(valueExpr, variables);
      if (value !== null) topLevel[key] = value;
    }
  }
  return { languages, topLevel };
}

function parseStringsJson(filePath) {
  const payload = JSON.parse(readText(filePath));
  const languages = {};
  const topLevel = {};
  for (const [key, value] of Object.entries(payload || {})) {
    if (typeof value === "string") topLevel[key] = value;
    else if (value && typeof value === "object") {
      languages[normalizeLanguage(key)] = Object.fromEntries(Object.entries(value).filter(([, item]) => typeof item === "string"));
    }
  }
  return { languages, topLevel };
}

function walkFiles(root) {
  if (!fs.existsSync(root)) return [];
  const result = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const item = path.join(root, entry.name);
    if (entry.isDirectory()) result.push(...walkFiles(item));
    else result.push(item);
  }
  return result;
}

function loadTranslations(modDir, primaryLanguage, fallbackLanguage) {
  const languages = {};
  const topLevel = {};
  const candidates = walkFiles(modDir).filter((file) => {
    const relative = path.relative(modDir, file).replaceAll("\\", "/").toLowerCase();
    return relative === "strings.lua" || relative.startsWith("strings/") || /^strings[^/]*\.json$/.test(relative);
  });
  for (const file of candidates) {
    try {
      const parsed = path.extname(file).toLowerCase() === ".lua" ? parseStringsLua(file) : parseStringsJson(file);
      Object.assign(topLevel, parsed.topLevel);
      for (const [language, values] of Object.entries(parsed.languages)) {
        languages[language] = { ...(languages[language] || {}), ...values };
      }
    } catch { /* A broken translation file must not hide the mod. */ }
  }
  const available = Object.keys(languages).sort();
  const primary = normalizeLanguage(primaryLanguage);
  const fallback = normalizeLanguage(fallbackLanguage);
  const selected = [primary, fallback, "en", ...available].find((item) => available.includes(item)) || "";
  return {
    map: { ...topLevel, ...(selected ? languages[selected] : {}), ...topLevel },
    available_languages: available,
    effective_language: selected,
    namespace: path.basename(modDir)
  };
}

function resolveLocalized(value, translations) {
  const candidate = String(value || "").trim();
  const keys = [candidate, candidate.replace(/^['"]|['"]$/g, ""), candidate.replace(/^\$/, "")];
  for (const key of keys) if (Object.hasOwn(translations.map, key)) return translations.map[key];
  return candidate.replace(/^_\(\s*/, "").replace(/\s*\)$/, "").replace(/^['"]|['"]$/g, "");
}

function parseModLua(filePath, primaryLanguage = "de", fallbackLanguage = "en") {
  const content = readText(filePath);
  const info = extractTableAfter(content, /\binfo\s*=\s*\{/) || content;
  const raw_fields = {};
  for (const entry of splitTopLevel(info)) {
    const [key, expression] = parseEntry(entry);
    if (!key || expression === null) continue;
    raw_fields[key] = evaluate(expression) ?? expression.trim().replace(/,$/, "");
  }
  const translations = loadTranslations(path.dirname(filePath), primaryLanguage, fallbackLanguage);
  const resolved_fields = Object.fromEntries(Object.entries(raw_fields).map(([key, value]) => [key, resolveLocalized(value, translations)]));
  const authorBlock = extractTableAfter(info, /\bauthors\s*=\s*\{/);
  let author = "";
  if (authorBlock) {
    const authorMatch = /\bname\s*=\s*(?:_\(\s*)?(["'][\s\S]*?["']|[A-Za-z_]\w*)/.exec(authorBlock);
    if (authorMatch) author = resolveLocalized(evaluate(authorMatch[1]) ?? authorMatch[1], translations);
  }
  author ||= resolveLocalized(raw_fields.author || "", translations) || "Unbekannt";
  const dependencies = [];
  const dependencyTable = extractTableAfter(info, /\bdependencies\s*=\s*\{/);
  for (const entry of splitTopLevel(dependencyTable)) {
    const value = evaluate(entry);
    if (value) dependencies.push(value);
  }
  const major = raw_fields.majorVersion || "";
  const minor = raw_fields.minorVersion || "";
  const version = raw_fields.version || (major && minor ? `${major}.${minor}` : minor || major || "Unbekannt");
  return {
    id: path.basename(path.dirname(filePath)),
    name: resolved_fields.name || raw_fields.name || path.basename(path.dirname(filePath)),
    author,
    version,
    path: path.dirname(filePath),
    mod_lua: filePath,
    description: resolved_fields.description || raw_fields.description || "",
    description_translated: resolved_fields.description || raw_fields.description || "",
    deepl_error: "",
    raw_fields,
    resolved_fields,
    translations: translations.map,
    translation_namespace: translations.namespace,
    translation_available_languages: translations.available_languages,
    translation_effective_language: translations.effective_language,
    translation_notice: "",
    dependencies,
    dependency_links: [],
    required_by: []
  };
}

module.exports = {
  extractBalancedBlock,
  extractTableAfter,
  loadTranslations,
  parseModLua,
  parseStringsJson,
  parseStringsLua,
  splitTopLevel
};
