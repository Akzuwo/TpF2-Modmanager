function endpointForKey(apiKey) {
  return apiKey.endsWith(":fx") ? "https://api-free.deepl.com/v2/translate" : "https://api.deepl.com/v2/translate";
}

async function translateText(text, targetLanguage, apiKey, fetchImplementation = fetch) {
  if (!apiKey || !text) return { text, error: "" };
  const body = new URLSearchParams({ text, target_lang: String(targetLanguage || "de").split(/[-_]/)[0].toUpperCase() });
  try {
    const response = await fetchImplementation(endpointForKey(apiKey), {
      method: "POST",
      headers: { Authorization: `DeepL-Auth-Key ${apiKey}`, "Content-Type": "application/x-www-form-urlencoded" },
      body
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || `DeepL HTTP ${response.status}`);
    return { text: payload.translations?.[0]?.text || text, error: "" };
  } catch (error) {
    return { text, error: error?.message || String(error) };
  }
}

async function translateDescriptions(mods, config, onProgress = () => {}) {
  if (!config.deepl_api_key) return mods;
  for (let index = 0; index < mods.length; index += 1) {
    const mod = mods[index];
    if (!mod.description) continue;
    onProgress(index, mods.length, `Uebersetze Beschreibung ${index + 1}/${mods.length}`);
    const result = await translateText(mod.description, config.language, config.deepl_api_key);
    mod.description_translated = result.text;
    mod.deepl_error = result.error;
  }
  return mods;
}

module.exports = { endpointForKey, translateDescriptions, translateText };
