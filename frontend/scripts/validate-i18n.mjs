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
const complete = process.argv.includes("--complete");
const staging = process.argv.includes("--staging");

if (complete && staging) {
  console.error("i18n check failed: --complete and --staging cannot be used together");
  process.exit(1);
}

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

function structuredTokens(value) {
  if (typeof value !== "string") return [];
  return [...value.matchAll(/\[PERSON_\d+\]/g)]
    .map((match) => match[0])
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
    if (value !== "" && sourceTokens.join("|") !== targetTokens.join("|")) {
      errors.push(
        `${locale}.${key}: placeholder mismatch (expected ${sourceTokens.join(", ") || "none"}; got ${targetTokens.join(", ") || "none"})`,
      );
    }
    const sourceStructuredTokens = structuredTokens(source.get(key));
    const targetStructuredTokens = structuredTokens(value);
    if (value !== "" && sourceStructuredTokens.join("|") !== targetStructuredTokens.join("|")) {
      errors.push(
        `${locale}.${key}: structured token mismatch (expected ${sourceStructuredTokens.join(", ") || "none"}; got ${targetStructuredTokens.join(", ") || "none"})`,
      );
    }
    if (complete && value.trim() === "") {
      errors.push(`${locale}.${key}: translation is still empty`);
    }
    if (staging && value !== "") {
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
  complete
    ? `i18n complete: ${source.size} keys across ${SUPPORTED_LOCALES.length} locales`
    : staging
      ? `i18n staging catalogs valid: ${source.size} keys, ${TARGET_LOCALES.length} empty target locales`
      : `i18n catalogs structurally valid: ${source.size} keys across ${SUPPORTED_LOCALES.length} locales`,
);
