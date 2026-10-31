import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const SUPPORTED_LOCALES = [
  "en",
  "de",
  "fr",
  "es",
  "it",
  "pt-BR",
  "zh-CN",
  "ja",
  "ko",
  "nl",
  "ru",
  "pl",
  "tr",
  "ca",
];
const TARGET_LOCALES = SUPPORTED_LOCALES.filter((locale) => locale !== "en");
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const localeRoot = path.resolve(scriptDir, "../src/locales");
const strict = process.argv.includes("--complete");

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function flatten(value, prefix = "", output = new Map()) {
  for (const [key, child] of Object.entries(value)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (isObject(child)) flatten(child, fullKey, output);
    else output.set(fullKey, child);
  }
  return output;
}

function placeholders(value) {
  if (typeof value !== "string") return [];
  return [...value.matchAll(/{{\s*([^},\s]+)[^}]*}}/g)]
    .map((match) => match[1])
    .sort();
}

function readCatalog(locale) {
  const file = path.join(localeRoot, locale, "translation.json");
  if (!fs.existsSync(file)) throw new Error(`${locale}: missing ${file}`);
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    throw new Error(`${locale}: invalid JSON (${error.message})`);
  }
}

const errors = [];
let source;
try {
  source = flatten(readCatalog("en"));
} catch (error) {
  console.error(`i18n check failed: ${error.message}`);
  process.exit(1);
}

for (const [key, value] of source) {
  if (typeof value !== "string" || value.trim() === "") {
    errors.push(`en.${key}: English source values must be non-empty strings`);
  }
}

for (const locale of TARGET_LOCALES) {
  let catalog;
  try {
    catalog = flatten(readCatalog(locale));
  } catch (error) {
    errors.push(error.message);
    continue;
  }

  for (const key of source.keys()) {
    if (!catalog.has(key)) {
      errors.push(`${locale}.${key}: missing key`);
      continue;
    }
    const value = catalog.get(key);
    if (typeof value !== "string") {
      errors.push(`${locale}.${key}: expected a string leaf`);
      continue;
    }
    const sourceTokens = placeholders(source.get(key));
    const targetTokens = placeholders(value);
    if (strict && sourceTokens.join("|") !== targetTokens.join("|")) {
      errors.push(
        `${locale}.${key}: placeholder mismatch (expected ${sourceTokens.join(", ") || "none"}; got ${targetTokens.join(", ") || "none"})`,
      );
    }
    if (strict && value.trim() === "") {
      errors.push(`${locale}.${key}: translation is still empty`);
    }
    if (!strict && value !== "") {
      errors.push(`${locale}.${key}: staging catalog must contain an empty string`);
    }
  }

  for (const key of catalog.keys()) {
    if (!source.has(key)) errors.push(`${locale}.${key}: unexpected key`);
  }
}

if (errors.length > 0) {
  console.error(`i18n check failed (${errors.length}):`);
  for (const error of errors.slice(0, 100)) console.error(`- ${error}`);
  if (errors.length > 100) console.error(`- ...and ${errors.length - 100} more`);
  process.exit(1);
}

console.log(
  strict
    ? `i18n complete: ${source.size} keys across ${SUPPORTED_LOCALES.length} locales`
    : `i18n staging catalogs valid: ${source.size} keys, ${TARGET_LOCALES.length} empty target locales`,
);
