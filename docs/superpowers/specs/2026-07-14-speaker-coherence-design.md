# Adaptive Speaker Coherence Design

## Goal

Keep the lightweight diarizer at the released `0.68` speaker-identity
threshold while preventing one VAD segment that contains multiple turns from
creating phantom speakers. The default path must handle the common topologies
we can identify today:

- one local person on the microphone plus one or more remote people on the
  system-audio track;
- split-track live calls where exactly one local user is configured;
- imported or other mixed audio where every voice must be diarized.

The change is complete only when the supplied two-person Recorder fixture
produces two remote profiles at the existing threshold and a live Docker replay
does not regress local routing, transcript completeness, or capture lifecycle.

## Root Cause and Evidence

The released lightweight diarizer closes a segment after 600 ms of silence or
15 seconds of accumulated speech, then computes one embedding for the entire
segment. In the supplied recording, two false-new segments contain alternating
speakers. Their single averaged embeddings do not match either established
profile, so lowering the identity threshold creates more profiles instead of
fixing the count.

Replay of the stored 501.9-second system track reproduced the live result:

- threshold `0.68`: three remote profiles for a two-person recording;
- threshold `0.60`: four remote profiles and additional fragmentation;
- shorter maximum segments or a 300 ms silence gap: 65 segments and four
  profiles, which is worse;
- the real second speaker's first clean turn is internally coherent, with
  adjacent 3-second-window similarities at or above `0.571`;
- the two false-new mixed segments have adjacent similarities as low as
  `-0.067` and `-0.041`.

A maximum-similarity exemplar bank is rejected because a prior exemplar of the
first speaker scores `0.642` against the true second speaker. At a lowered
identity threshold that approach would merge two real people. Sortformer stays
optional because it adds a materially heavier runtime and does not remove the
need for stable profile assignment in the default path.

## Design

### Preserve the confident fast path

For every finalized VAD segment, compute the existing full-segment embedding
and use `SpeakerRegistry.match()` as a read-only probe for an established
identity. When that probe succeeds, pass the same embedding through
`match_or_create()` so the current centroid update still occurs; do not extract
the embedding again. The matched segment then follows the current assignment
without coherence-window work.

The current behavior also remains unchanged for:

- segments shorter than `MIN_NEW_SPEAKER_MS`;
- the first usable segment, when no speaker profile exists;
- segments that cannot form at least two coherence windows.

### Analyze only long unmatched segments

When a long segment does not match an established profile, partition its PCM
into non-overlapping windows controlled by:

```text
SPEAKER_COHERENCE_WINDOW_MS=3000
SPEAKER_COHERENCE_THRESHOLD=0.40
```

If the final window is shorter than `MIN_SEGMENT_MS`, merge it into the prior
window before computing embeddings. Compare each adjacent pair of window
embeddings. The coherence threshold is deliberately independent of the `0.68`
identity threshold: it answers whether adjacent audio is acoustically
consistent, not which registered person produced it.

- If every adjacent similarity is at least `0.40`, treat the segment as one
  coherent voice and run the existing full-segment `match_or_create()` path.
- If any adjacent similarity is below `0.40`, group consecutive windows between
  those boundaries. Normalize the mean of each group's already-computed window
  embeddings, assign the group only to existing profiles using
  `allow_create=False`, then merge adjacent groups that receive the same
  speaker ID. Do not re-embed a group.

Mixed-segment pieces must never create a profile. This is intentionally
conservative: a previously unheard speaker first encountered inside mixed audio
is assigned to the nearest existing profile until a coherent standalone turn
can enroll that person.

### Output contract

One finalized input segment may now produce several `DiarizedSegment` values.
`feed_audio()` and a new `flush_segments()` method return ordered lists. The
existing shared flush helper already accepts list-returning diarizers; the
offline comparison script will use that helper instead of calling the
lightweight `flush()` method directly.

For every split, concatenating the output PCM in order must equal the input PCM
byte-for-byte. There may be no overlap, gap, duplicated byte, or reordered
piece. Adjacent pieces assigned to the same speaker are merged before ASR so an
unnecessary coherence check does not fragment the transcript.

If coherence analysis cannot produce valid embeddings, the diarizer falls back
to the existing full-segment decision rather than dropping audio.

## Topology Behavior and Boundaries

With exactly one configured `is_user` speaker, microphone segments captured
after split-track system audio is active remain bound directly to that user.
They bypass this remote-speaker registry. The system-audio track retains
diarization and receives the coherence behavior. Once split-track state is
established, mic-first versus system-first queued processing must not change
remote assignment.

Mic-only sessions and sessions with zero or multiple configured local users
continue to diarize microphone audio because the data model does not identify
which physical person owns the mic. This is the explicit multi-local
limitation; the implementation must not select an arbitrary user row.

For imported or other single-track mixed audio, all voices use the same
lightweight diarizer and receive the new behavior automatically. Identity is
still encounter-order state scoped to one connection or import, not persistent
voice enrollment across sessions.

Expected profile behavior:

- one remote speaker: inconsistent outliers cannot create profiles two through
  four;
- two remote speakers: each coherent first turn can enroll a profile, and later
  mixed turns split back to those profiles;
- three or four remote speakers: each new voice needs a coherent standalone
  turn before it can enroll;
- more than four remote speakers: the existing profile cap remains the hard
  limit, so additional voices are forced to the nearest established profile.

Echoed remote speech on the microphone can still be transcribed as the local
user. Headphones or echo cancellation remain necessary because cross-track
transcript deduplication is outside this change.

## Performance and Failure Handling

Additional ECAPA inference occurs only for long segments that miss every
existing profile. A 15-second segment adds at most about five window embeddings.
The work continues through the existing off-event-loop diarization path.

A fixed 3-second grid can cut a word. The byte-preservation contract, short-tail
merge, and same-speaker merge limit that damage. Fixture ASR checks at the two
observed boundaries produced coherent text on both sides. Finer boundary search
is deferred until live evidence shows measurable word loss.

Coherence does not solve every identity error. A genuinely new coherent voice
that exceeds the identity threshold can still be merged, and a coherent
acoustic shift from one person can still enroll a false profile. Those cases
need measured fixtures before adding more state or another model.

## Verification

Unit tests will use deterministic embeddings and cover:

- a coherent unmatched turn enrolling exactly one new profile;
- mixed turns splitting at low-similarity boundaries without increasing the
  profile count;
- byte-for-byte partitioning with no gap or overlap;
- adjacent same-ID pieces merging;
- matched and short segments avoiding coherence analysis;
- a matched fast-path segment preserving the existing centroid update;
- one-speaker inconsistent audio retaining one profile;
- three coherent speakers enrolling three identities while later mixtures add
  none;
- a mixed first appearance being forced, followed by enrollment on a clean
  turn;
- `flush_segments()` returning every tail piece in order;
- the offline comparison script handling list-returning finalization.

Stored-fixture acceptance at both `0.68` and the diagnostic `0.60` setting is:
exactly two profiles, the true second-speaker turn assigned to profile two, and
neither known mixed segment creating a profile. The product default remains
`0.68`.

Docker live validation will replay the same Recorder session and check remote
speaker count, local-speaker routing, remote fragmentation, false merges,
turn-label accuracy, duplicate transcript count, and transcript completeness.
It will also exercise start, end, resume, and reconnect so the released capture
single-flight protections remain intact. Installers are built only after this
Docker gate passes.
