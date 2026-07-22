export interface RefusedSessionSnapshot {
  state: string;
  ended_at: string | null;
}

// Prior state of a session left "active" by a refused start. ended_at
// survives only when no resume PATCH cleared it; transcript entries prove a
// completed life even for imported/analyzed sessions that have zero call
// segments, so segment count must not be used here.
export function refusalRollbackState(
  session: RefusedSessionSnapshot,
  transcriptCount: number,
): "completed" | "pre_call" {
  if (session.ended_at) return "completed";
  return transcriptCount > 0 ? "completed" : "pre_call";
}

export interface RefusalReconcileDeps {
  getSession: (id: string) => Promise<RefusedSessionSnapshot>;
  updateSession: (
    id: string,
    data: { state: "completed" | "pre_call" },
  ) => Promise<unknown>;
}

// The backend restores the session row itself when it refuses an unready
// call; this client-side pass re-reads the row and PATCHes only when that
// restore did not land. Returns null on success, or a description of the
// problem so the caller surfaces it instead of leaving the session active
// silently.
export async function reconcileRefusedSession(
  sessionId: string,
  transcriptCount: number,
  deps: RefusalReconcileDeps,
): Promise<string | null> {
  try {
    const latest = await deps.getSession(sessionId);
    if (latest.state !== "active") {
      return null;
    }
    await deps.updateSession(sessionId, {
      state: refusalRollbackState(latest, transcriptCount),
    });
    return null;
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}
