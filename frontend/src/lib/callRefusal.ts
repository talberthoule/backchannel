// After the backend refuses an unready call (transcription_unready) the
// session row may already be persisted "active" by the optimistic pre-call
// flow even though no call segment was created. Roll it back to where the
// user came from: post-call review when earlier segments exist (a refused
// resume), otherwise pre-call setup.
export function refusalRollbackState(segmentCount: number): "completed" | "pre_call" {
  return segmentCount > 0 ? "completed" : "pre_call";
}
