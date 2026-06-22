const fs = require("node:fs");

const DEFAULT_CONFIG = Object.freeze({
  mods_path: "",
  language: "de",
  fallback_language: "en",
  app_language: "de",
  debug_logging_enabled: false,
  deepl_api_key: "",
  appworkshop_path: "",
  workshop_mods_path: "",
  duplicate_behavior: "manual",
  parallel_install_enabled: false,
  max_parallel_workers: 2,
  delete_download_archives_after_install: false
});

function mergeConfig(input = {}) {
  const config = { ...DEFAULT_CONFIG };
  for (const key of Object.keys(DEFAULT_CONFIG)) {
    if (Object.hasOwn(input, key)) config[key] = input[key];
  }
  config.max_parallel_workers = Math.max(1, Math.min(16, Number(config.max_parallel_workers) || 2));
  return config;
}

function loadConfig(filePath) {
  try {
    return mergeConfig(JSON.parse(fs.readFileSync(filePath, "utf8")));
  } catch {
    const config = mergeConfig();
    saveConfig(filePath, config);
    return config;
  }
}

function saveConfig(filePath, input) {
  const config = mergeConfig(input);
  fs.writeFileSync(filePath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
  return config;
}

module.exports = { DEFAULT_CONFIG, loadConfig, mergeConfig, saveConfig };
