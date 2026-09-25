// Whether a transcription model suits the workspace meeting language (ALP-405).
// Mirrors backend recommendable_for_language: a model's `languages` lists what
// it can transcribe; a model without one is multilingual or provider-decided.

export interface LanguageAwareModel {
  name: string;
  languages?: string[] | null;
}

/** A sentence explaining why the model does not suit the language, or null. */
export function languageMismatch(
  model: LanguageAwareModel | undefined,
  language: string,
  languageName: (code: string) => string,
): string | null {
  const covered = model?.languages;
  if (!model || !covered || covered.length === 0) return null;
  if (language === "auto") {
    return covered.length === 1 && covered[0] === "en"
      ? `${model.name} transcribes English only. Set the meeting language to English, or pick a multilingual model.`
      : null;
  }
  if (covered.includes(language)) return null;
  return `${model.name} does not transcribe ${languageName(language)}. Pick a model that covers it.`;
}
