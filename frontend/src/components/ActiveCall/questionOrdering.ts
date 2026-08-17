import type { Question } from "../../types";

function createdAtMs(question: Question): number {
  const value = Date.parse(question.created_at);
  return Number.isFinite(value) ? value : 0;
}

function isPinned(question: Question): boolean {
  return question.starred || (question.vote ?? 0) > 0;
}

export function sortQuestionsForLiveDisplay(questions: Question[]): Question[] {
  return [...questions].sort((a, b) => {
    const pinnedA = isPinned(a);
    const pinnedB = isPinned(b);

    if (pinnedA !== pinnedB) {
      return pinnedA ? -1 : 1;
    }

    const timeDelta = createdAtMs(b) - createdAtMs(a);
    if (timeDelta !== 0) return timeDelta;

    return a.id.localeCompare(b.id);
  });
}
