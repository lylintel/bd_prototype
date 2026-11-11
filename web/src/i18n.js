import zhCN from "./locales/zh-CN.json" with { type: "json" };

const catalogs = Object.freeze({ "zh-CN": Object.freeze(zhCN) });

export function hasMessage(key, locale = "zh-CN") {
  const catalog = Object.hasOwn(catalogs, locale) ? catalogs[locale] : catalogs["zh-CN"];
  return Object.hasOwn(catalog, key) && typeof catalog[key] === "string";
}

export function t(key, parameters = {}, locale = "zh-CN") {
  const catalog = Object.hasOwn(catalogs, locale) ? catalogs[locale] : catalogs["zh-CN"];
  if (!hasMessage(key, locale)) {
    throw new Error(catalogs["zh-CN"]["i18n.missingKey"].replace("{key}", String(key)));
  }
  return catalog[key].replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (_, name) => {
    if (!Object.hasOwn(parameters, name)) {
      throw new Error(catalogs["zh-CN"]["i18n.missingParameter"].replace("{name}", name));
    }
    return String(parameters[name]);
  });
}