# Backchannel UI Translation Handoff

## Source

English is the source language. The canonical catalog is:

`frontend/src/locales/en/translation.json`

Use that file as the key, nesting, and source-text reference. The 13 target catalogs are under `frontend/src/locales/<locale>/translation.json`.

## Target locales

The required locale codes are:

`de`, `fr`, `es`, `it`, `pt-BR`, `zh-CN`, `ja`, `ko`, `nl`, `ru`, `pl`, `tr`, `ca`.

`pt-BR` means Brazilian Portuguese. Do not return generic `pt` or `pt-PT`.

## Return format

Return the existing JSON file for each locale, preserving the complete nested key structure from the English catalog. Every leaf must remain a string. Do not add, remove, rename, or flatten keys.

Preserve:

- i18next placeholders such as `{{name}}`, `{{count}}`, and `{{filename}}`;
- plural-form key suffixes exactly as supplied (`_one`, `_other`, `_few`, `_many`);
- URLs, code identifiers, product names, and tokens such as `[PERSON_1]`;
- punctuation that is part of structured text, including list separators.

For plural entries, translate each supplied form. Languages that do not use every English plural category may keep the closest grammatical wording in the supplied keys; do not change the key set.

## Content boundaries

Translate only stable frontend UI copy represented by catalog keys. Do not translate:

- live or saved meeting transcripts;
- speaker names or user-entered names;
- user-created session or group names;
- uploaded or imported content;
- AI-generated summaries, answers, insights, or other model output;
- prompts, model instructions, logs, telemetry, API payloads, or WebSocket payloads;
- dynamic backend messages that are not mapped through a frontend catalog key.

Comments and developer-only diagnostics are not part of the catalog.

## Validation and delivery

All 13 externally supplied catalogs are now integrated. Keep the completed JSON files as the translation source of truth; do not copy English text into a target field as a placeholder.

From `frontend/`, run:

```bash
npm run i18n:check
npm run i18n:check:complete
```

The first command verifies key and placeholder structure across all catalogs. The complete command additionally requires all 13 target catalogs to contain non-empty values.

For a future empty translation template, run `npm run i18n:check:staging`; that mode requires every target value to remain an empty string until translation is supplied.

Return the 13 completed JSON files, or place them at the paths above, for integration and final UI validation. Translations are integrated only when all 13 catalogs pass the strict check together.
