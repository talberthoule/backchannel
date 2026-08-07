# ALP-292: WeSpeaker ResNet152-LM vs ResNet34-LM on real Backchannel audio

Requested by: Talbert Houle
Performed by: Claude (Opus 5)
Date: 2026-08-07
Scope: Evaluation only. Measures whether the ResNet152-LM speaker embedding
model earns its cost against ResNet34-LM on recorded Backchannel calls, and
produces a verdict plus supporting numbers. No runtime code was changed. Files
touched: `backend/scripts/diarizer_ab.py`, `backend/scripts/download_models.py`,
and this report. `backend/app/services/speaker_diarizer.py` and
`backend/app/config.py` were read but not modified.

## Verdict

**Keep WeSpeaker ResNet152-LM. Do not switch the default, and leave
`SPEAKER_SIMILARITY_THRESHOLD` at 0.68.** This is an evaluation result, not an
implementation; nothing in the runtime was changed.

The question was whether ResNet152 measurably beats ResNet34 on real
Backchannel audio. It does. On the only labels this corpus can support, and in
a paired test on identical pairs, ResNet152 cuts the rate at which a
different-speaker pair outscores a same-speaker pair from 1.581 percent to
0.920 percent, a 1.7x reduction, with a 95 percent bootstrap interval on the
difference of [+0.287, +1.096] percentage points that excludes zero. The
smaller 3.0 second condition reproduces it, 0.385 against 0.205 percent. Every
clean measurement points the same way: equal error rate 3.61 against 5.37
percent, minimum total error 6.65 against 10.47 percent, separation margin
+0.043 against -0.005, and independently in the production regime a wider
operating gap, 0.144 against 0.125.

That advantage costs 3.3x the CPU at the tuned operating point and about 50 MB
of disk. It is a real trade rather than a free one, and two things decide it:

- The regression from switching is not hypothetical. ResNet34 over-segments at
  the current threshold, enrolling 208 new speakers against 185 over the same
  ten recordings and finding one extra speaker on two of them. Speaker-count
  errors are user-visible in the transcript and in every downstream agent
  prompt, which is the kind of error Backchannel can least afford.
- The CPU argument that motivated the question has already been answered
  elsewhere. ALP-289's session-option tuning cut real-call diarization CPU by
  4.4x to 5.6x on its own, without touching accuracy at all: that lane verified
  embeddings are bit-identical across thread configurations. Spending a
  measured accuracy regression to chase what remains is the wrong order of
  operations.

An earlier draft of this report recommended the opposite, on 50 positive pairs
where the signals were mixed and the difference was not significant. Increasing
the positive set to 278 by shortening the analysis window resolved the
direction and reversed the conclusion. The lesson is worth carrying: at 50
pairs this comparison could not tell the models apart, and the underpowered
answer happened to favour the cheaper model.

Two secondary notes rather than recommendations:

- ResNet34 remains a reasonable option to expose for genuinely constrained
  hardware, where a 1.7x increase in speaker confusion may be an acceptable
  price for 3.3x less CPU and 50 MB. That is a product decision, and it would
  need its own threshold: ResNet34's same-speaker distribution sits about 0.02
  lower, so roughly 0.66 rather than 0.68. Do not ship that without retuning
  against real labels.
- WeSpeaker's published VoxCeleb1-O equal error rates, 0.495 percent for
  ResNet152-LM against 0.723 percent for ResNet34-LM, are a 1.46x ratio. The
  1.4x to 1.9x ratios measured here on Backchannel audio are consistent with
  that, which is a useful sanity check that this harness is measuring the
  thing it claims to measure.

Confidence: moderate, not high. The direction is consistent and paired-
significant, but no speaker ground truth was ever established on this corpus
(section 3), the positives are easy ones, and the pair-level bootstrap
understates clustering. Section 10 says what would settle it properly. The
practical consequence of that uncertainty is small, though, because the
recommendation is to change nothing.

## 1. The question

`backend/app/services/speaker_diarizer.py` runs one WeSpeaker ResNet152-LM
forward pass per diarized speech segment. Under ALP-288 that pass measured as
roughly 88 percent of the diarization CPU budget. ResNet34-LM is the same
family at roughly a fifth of the compute. If ResNet152 does not measurably beat
ResNet34 on Backchannel's own audio, replacing it saves more CPU than every
other fix under ALP-288 combined.

## 2. What the recorded audio actually contains

`C:/Users/thoule/AppData/Local/Backchannel/data/audio` holds 44 WAV files
across 22 session directories, all PCM16 16 kHz mono. Eight recordings, in five
sessions, have the split `_mic` / `_sys` tracks that the evaluation design
depends on.

| Session | Recording | Duration | mic RMS | sys RMS |
| --- | --- | --- | --- | --- |
| 0b1f2a76 | segment_1 | 1398.6 s | 0.08548 | 0.00000 |
| 8c544c12 | segment_1 | 76.2 s | 0.08301 | 0.05659 |
| 8c544c12 | segment_2 | 710.9 s | 0.10246 | 0.07645 |
| 8c544c12 | segment_3 | 755.7 s | 0.09526 | 0.07964 |
| 8c544c12 | segment_4 | 576.1 s | 0.09573 | 0.08331 |
| 97b2f7dd | segment_1 | 108.6 s | 0.02473 | 0.00000 |
| 99985052 | segment_1 | 3329.2 s | 0.06843 | 0.06487 |
| b5737919 | segment_1 | 2668.8 s | 0.01929 | 0.09371 |

That is 160 minutes of dual-track audio, which looks like plenty. It is not,
and the reason is the most important finding in this report.

## 3. The split tracks are mostly not usable as labels

The evaluation design assumed that anything on `_mic` is the local user and
anything on `_sys` is a remote participant. Two separate effects break that
assumption, and both had to be detected before any similarity number meant
anything.

### 3.1 Acoustic echo

If the local user is on open speakers rather than headphones, the remote audio
is re-recorded by the microphone and the `_mic` track contains the remote
speakers. A normalized sample-level cross-correlation between the two tracks
detects this: real echo appears as a sharp peak at a lag of roughly 30-350 ms,
whereas ordinary turn-taking does not correlate at the sample level at all.

| Session | Recording | xcorr peak | lag | reading |
| --- | --- | --- | --- | --- |
| 8c544c12 | segment_1 | 0.341 | 29.6 ms | echo |
| 8c544c12 | segment_2 | 0.552 | 148.8 ms | echo |
| 8c544c12 | segment_3 | 0.490 | 154.7 ms | echo |
| 8c544c12 | segment_4 | 0.569 | 260.4 ms | echo |
| 99985052 | segment_1 | 0.270 | 345.4 ms | echo |
| b5737919 | segment_1 | 0.016 | 90.1 ms | clean |

Five of the six recordings that have audio on both tracks are echo
contaminated. Their `_mic` tracks cannot be used as a local-user label.

This check has a trap worth recording, because the first version of it fell
into the trap and produced a confident wrong answer. Scoring a single window
chosen for maximum remote energy can land on a stretch where the microphone is
muted; the correlation is then exactly 0.000 and the recording is declared
clean. Session 99985052 was cleared that way before the check was corrected to
consider only windows where both tracks carry signal, and to take the worst
case over several such windows. Its true correlation is 0.270. Any future use
of this harness should keep that constraint.

### 3.2 A silent output track means an in-person meeting

Sessions 0b1f2a76 and 97b2f7dd have a digitally silent `_sys` track. The
initial reading was that this makes their `_mic` tracks perfectly clean, since
there is no remote audio to echo. That is true but useless: an empty output
track means no remote participants, which means the recording is an in-person
meeting captured on the laptop microphone, and the `_mic` track therefore holds
every person in the room rather than one local user.

The embeddings confirm it directly. A track holding one voice produces a tight,
high self-similarity cloud. Median pairwise cosine within each track, and the
length of the mean embedding (1.0 would be a single point, and lower means more
spread), for ResNet152 / ResNet34:

| Track | Windows | median self-similarity | mean-vector length |
| --- | --- | --- | --- |
| 0b1f2a76 mic | 432 | 0.107 / 0.120 | 0.377 / 0.379 |
| b5737919 mic | 55 | 0.319 / 0.324 | 0.553 / 0.561 |
| 97b2f7dd mic | 3 | too few | too few |
| 8c544c12 s2 output | 270 | 0.067 / 0.062 | 0.386 / 0.374 |
| 8c544c12 s4 output | 203 | 0.220 / 0.183 | 0.512 / 0.474 |
| 99985052 output | 1004 | 0.126 / 0.132 | 0.410 / 0.409 |
| b5737919 output | 885 | 0.093 / 0.103 | 0.389 / 0.393 |

The 0b1f2a76 mic track, 23 minutes of it, scores 0.107 against output tracks
that are known to hold several remote people scoring 0.067 to 0.220. It is
indistinguishable from a multi-speaker track, which is what it is. Both models
rank the tracks in the same order, so this is a property of the audio and not
of the embedding.

The consequence is that of eight dual-track recordings, none provides a
verified single-speaker reference. `b5737919/segment_1` is the closest, being
the only echo-free mic track and the tightest of all tracks, but at 0.319
median self-similarity over 55 short windows it does not establish that only
one person is on it either. The premise that the split tracks are labels does
not survive contact with these particular recordings.

## 4. Method

The harness is `backend/scripts/diarizer_ab.py`, extended for this work with
three modes. Everything below is reproducible from the checked-in script.

- `margin` builds pairs from the recordings, validates the track labels as
  described above, cuts VAD speech runs into equal-length windows (minimum
  0.75 s to match `MIN_SEGMENT_MS`), embeds each window with every available
  model, and reports same-speaker and different-speaker cosine distributions
  separately. Equal-length windows keep segment duration from confounding the
  comparison. It also runs the label-free comparison in 7.2 and a paired
  bootstrap between the two models.
- `cost` measures CPU per embedding under explicit `ort.SessionOptions`, and
  additionally through `speaker_diarizer._embed_session_options()` so the
  as-configured row follows ALP-289's tuned defaults rather than a copy. The
  previous harness hardcoded default options at line 79; nothing is inherited
  implicitly now.
- `pipeline` runs the production `SpeakerDiarizer` end to end over mixed
  recordings with each model and reports per-segment assignment agreement under
  the best label permutation.

Both models are always timed and scored under identical settings, and ALP-289
established that embeddings are bit-identical across thread configurations, so
no separation number here can be an artifact of how a session was built.

Two regimes are reported, and the distinction matters for the threshold.
Pairwise similarity compares two segment embeddings. `SpeakerRegistry` never
does that: `match` compares a new embedding against a profile that is the
renormalized running mean of the embeddings already assigned to that speaker
(`speaker_diarizer.py` `_update_profile`). Averaging suppresses per-segment
noise, so profile similarities sit well above pairwise ones and a threshold
derived from pairwise numbers would be set far too low. The harness simulates
the profile regime with oracle enrollment so the profile cannot drift onto the
wrong speaker.

The VAD pass and the embeddings are both cached on disk, keyed by file identity
and by the exact window set, so parameter changes do not force a re-embed.

## 5. Cost

Measured with `diarizer_ab.py cost`, 15 timed runs after 3 warmups, 28-logical
-core machine, onnxruntime 1.21.1, one 5-second segment. Session options are
always set explicitly by the harness so both models are timed under identical,
stated settings; the last row instead calls
`speaker_diarizer._embed_session_options()` directly, so the "as the
application runs it" figure tracks the ALP-289 defaults rather than a frozen
copy of them. `cpu_ms/s_audio` normalizes by segment length, which keeps the
comparison honest given the two models segment the same audio slightly
differently (313 against 315 segments in section 8).

| Config | ResNet152 wall / CPU | ResNet34 wall / CPU | CPU per s audio | CPU ratio |
| --- | --- | --- | --- | --- |
| default, spin on | 158.5 / 3013.5 ms | 33.7 / 655.2 ms | 602.7 vs 131.0 | 4.60x |
| 1 thread, spin on | 754.7 / 734.4 ms | 221.3 / 217.7 ms | 146.9 vs 43.5 | 3.37x |
| 2 threads, spin on | 492.5 / 974.0 ms | 142.2 / 276.0 ms | 194.8 vs 55.2 | 3.53x |
| 4 threads, spin on | 339.7 / 1339.6 ms | 88.9 / 352.1 ms | 267.9 vs 70.4 | 3.80x |
| default, spin off | 166.8 / 1519.8 ms | 35.6 / 412.5 ms | 304.0 vs 82.5 | 3.68x |
| 1 thread, spin off | 782.5 / 760.4 ms | 246.5 / 237.5 ms | 152.1 vs 47.5 | 3.20x |
| 2 threads, spin off | 530.5 / 984.4 ms | 132.5 / 241.7 ms | 196.9 vs 48.3 | 4.07x |
| 4 threads, spin off | 350.5 / 1140.6 ms | 89.5 / 302.1 ms | 228.1 vs 60.4 | 3.78x |
| **as the app configures it** | **347.3 / 1092.7 ms** | **98.3 / 331.2 ms** | **218.5 vs 66.2** | **3.30x** |

The Kaldi fbank frontend costs 11.5 ms CPU per segment, so the model forward
pass is effectively the entire embedding cost. ResNet34 is 3.2x to 4.6x cheaper
in CPU across every configuration, and 3.3x at the tuned operating point
ALP-289 landed on (4 threads, spinning off).

Three points that came from the ALP-289 lane and matter for how these numbers
should be read.

First, embeddings are bit-identical across thread configurations: that lane
measured a maximum elementwise delta of exactly 0.0 over 80 real five-second
clips, with none of 6,400 pairwise similarity decisions flipping at the 0.68
threshold. Threading is therefore a pure cost knob and cannot perturb any
separation number in section 7.

Second, this table times a tight loop, which is the fairest way to compare two
models but understates production cost. In service, ORT's intra-op pool
spin-waits after an inference returns, and because live segments arrive seconds
apart that spin is charged to whatever runs next. ALP-289 measured 894.5 ms of
CPU burned during a 300 ms idle gap with spinning on, and 0.0 ms with it off.
That cost is a property of the pool rather than of the model, so it applies to
whichever model is loaded and does not move the comparison.

Third, ALP-289's tuning alone cut real-call diarization CPU by 4.4x to 5.6x.
That materially changes what a further model-driven saving is worth, and it is
the reason section 11 lands where it does.

Both models expose an identical ONNX interface, `feats` of shape [B, T, 80] to
`embs` of shape [B, 256], so a swap would be a filename change with no code
change anywhere.

## 6. Size

`backend/models/` is checked into git and is shipped whole into the desktop
bundles (`desktop/backchannel.spec` line 28) and built into the Docker image
(`backend/Dockerfile` line 23). ResNet152-LM is 79,158,228 bytes; ResNet34-LM
is 26,530,309 bytes. Switching would remove about 50 MB from the repository,
from all three desktop bundles, and from the image. This is a real cost of
keeping ResNet152 and is recorded so the trade is visible, but 50 MB against a
1.7x speaker-confusion regression is not a close call.

## 7. Discrimination

### 7.1 What the track labels produce, and why it is not usable

Run for completeness. With `_mic` treated as the local user and `_sys` as
remote, ResNet152 gives an equal error rate of 33.82 percent and ResNet34
32.73 percent, and both report a negative separation margin. Those numbers
describe the contamination in section 3, not the models. Same-speaker median
cosine comes out at 0.108, which is not a value any working speaker embedding
produces for one voice; the same pipeline in production regime reports 0.851
for genuinely matched segments. This line of evidence is discarded.

### 7.2 A comparison that needs no track labels

Two labels hold on this corpus without any assumption about who is on which
track:

- Same speaker: two windows carved from one uninterrupted VAD speech run with
  no silence between them. Speakers do not swap mid-utterance inside a second.
- Different speaker: windows from the application output tracks of two
  different calls. Different meetings, different remote participants.

The headline statistic is the overlap rate, the probability that a
different-speaker pair scores at least as high as a same-speaker pair. It is
purely rank-based, which matters here: the two models put their similarities on
noticeably different scales (ResNet34's different-speaker mean is 0.062 against
ResNet152's 0.050), and a rank statistic is invariant to that, so neither model
is helped or hurt by being globally tighter.

At 1.5 s windows, capped at 400 windows per track, 2,131 windows embedded:

| Metric | ResNet152 | ResNet34 |
| --- | --- | --- |
| SAME, contiguous windows (n=278) | mean 0.470, p5 0.250, p50 0.479 | mean 0.445, p5 0.219, p50 0.459 |
| DIFF, two calls (n=851,200) | mean 0.050, p95 0.207 | mean 0.062, p95 0.224 |
| Overlap, P(DIFF >= SAME) | **0.920%** | **1.581%** |
| Equal error rate | 3.61% at t=0.224 | 5.37% at t=0.221 |
| Minimum total error | 6.65% at t=0.247 | 10.47% at t=0.220 |
| Separation p5(SAME) - p95(DIFF) | +0.043 | -0.005 |

At 3.0 s windows, 3,135 windows embedded, the same direction with a smaller
positive set:

| Metric | ResNet152 | ResNet34 |
| --- | --- | --- |
| Overlap, P(DIFF >= SAME) | 0.205% | 0.385% |
| Equal error rate | 2.09% at t=0.265 | 2.97% at t=0.246 |
| Separation p5(SAME) - p95(DIFF) | +0.048 | +0.011 |

Both models score the identical, identically ordered set of pairs, so the
comparison is paired and much more sensitive than comparing two independent
error rates. Bootstrapping over the positive pairs, 5,000 resamples:

| Windows | Pairs | Overlap 152 | Overlap 34 | Difference, 95% CI | P(152 better) |
| --- | --- | --- | --- | --- | --- |
| 1.5 s | 278 | 0.920% | 1.581% | +0.661% [+0.287, +1.096] | 100.0% |
| 3.0 s | 40 | 0.205% | 0.385% | +0.180% [+0.013, +0.393] | 98.4% |

**ResNet152 separates speakers measurably better than ResNet34 on this audio.**
The interval excludes zero at both window lengths, the effect size is a 1.7x to
1.9x reduction in false-accept mass, and the direction is the same on every
clean measurement taken: overlap, equal error rate, minimum total error,
separation margin, and the production-regime operating gap in 7.3.

Two honest qualifications. The bootstrap resamples pairs as if they were
independent, but pairs cluster within speech runs and within the nine tracks,
so the effective sample size is smaller than 278 and the true interval is wider
than shown; the 1.5 s result has margin to spare, the 3.0 s result at 40 pairs
does not. And contiguous windows are easy positives that share a breath, a
channel and a moment, so these absolute error rates are optimistic for both
models. Neither qualification touches the direction, which is what the verdict
turns on, and the direction is consistent across two window lengths, five
metrics, and an independent measurement in 7.3.

### 7.3 The regime the threshold actually gates

`SpeakerRegistry.match` compares against a running profile, not against another
segment, so this is the distribution `SPEAKER_SIMILARITY_THRESHOLD` sits in.
Measured by running the production `SpeakerDiarizer` over ten mixed recordings
(about 46 minutes, 313 and 315 segments respectively) at the current 0.68:

| | ResNet152 | ResNet34 |
| --- | --- | --- |
| Matched segments, count | 161 | 147 |
| Matched similarity p10 / p50 / p90 | 0.736 / 0.851 / 0.912 | 0.723 / 0.829 / 0.908 |
| New-speaker enrollments, count | 185 | 208 |
| Best rejected similarity p10 / p50 / p90 | 0.043 / 0.324 / 0.592 | 0.085 / 0.347 / 0.598 |
| Operating gap, p10(matched) - p90(rejected) | +0.144 | +0.125 |
| Midpoint-of-medians suggestion | 0.59 | 0.59 |

Both models put the same-speaker mode far above the threshold and the
different-speaker mode far below it, and both suggest the same threshold by the
midpoint heuristic. ResNet34's same-speaker distribution sits about 0.02 lower
and its rejected distribution about 0.02 higher, which narrows the operating
gap from 0.144 to 0.125. That is a real but small effect, and it has a visible
consequence: at an unchanged 0.68, ResNet34 enrolled 208 new speakers against
ResNet152's 185 and matched 147 against 161. ResNet34 over-segments slightly.

These two distributions are conditioned on the 0.68 decision itself, so they
describe the operating point rather than the underlying separability. They are
reported because the operating point is what has to keep working.

## 8. Agreement on real mixed recordings

Ten mixed recordings, production `SpeakerDiarizer` end to end, per-segment
speaker labels compared under the best label permutation.

| Recording | Segments 152 / 34 | Speakers 152 / 34 | Agreement |
| --- | --- | --- | --- |
| 4864dab8 segment_1 | 27 / 27 | 2 / 2 | 26/27 = 96.3% |
| 725c5151 segment_1 | 19 / 17 | 2 / 2 | 12/17 = 70.6% |
| 9834d0c8 segment_1 | 30 / 30 | 2 / 2 | 30/30 = 100.0% |
| 9ebdcd67 segment_1 | 76 / 78 | 4 / 4 | 55/76 = 72.4% |
| af04966c segment_1 | 27 / 27 | 3 / 4 | 24/27 = 88.9% |
| c1368dc6 segment_1 | 14 / 14 | 2 / 2 | 12/14 = 85.7% |
| c1368dc6 segment_2 | 13 / 14 | 3 / 3 | 12/13 = 92.3% |
| 8c544c12 segment_2 | 73 / 74 | 4 / 4 | 64/71 = 90.1% |
| 97b2f7dd segment_1 | 27 / 27 | 1 / 2 | 18/27 = 66.7% |
| 9e1eef6e segment_1 | 7 / 7 | 2 / 2 | 6/7 = 85.7% |
| Total | 313 / 315 | 8 of 10 identical | 259/309 = 83.8% |

Segment counts differ by 0.6 percent overall, and the speaker count is
identical on eight of ten recordings. Where it differs, ResNet34 found one more
speaker both times, which matches the enrollment counts in 7.3.

Agreement is not accuracy. Two models that are each imperfect in different
places will disagree without either being better, so 83.8 percent does not rank
them by itself. What it establishes is that swapping the model is not
behaviourally free: roughly one segment in six would receive a different speaker
label. Section 7.2 is what says which of those labellings is more often right.
Agreement is also computed under the most generous label permutation, so 83.8
percent is a ceiling.

The disagreement is concentrated. On six of the ten recordings agreement is 85
to 100 percent; the three worst are 725c5151 at 70.6, 9ebdcd67 at 72.4 and
97b2f7dd at 66.7. Those are the recordings with the lowest signal levels or the
most speakers, which is where both models are least certain rather than where
one is clearly wrong.

One case is worth naming because it points the same way as section 7.2.
Recording 97b2f7dd is 109 seconds at RMS 0.025 with a silent output track and
28.7 percent speech activity, and ResNet152 assigns it one speaker where
ResNet34 assigns two. A short quiet recording of a single person is the most
likely reading, which would make ResNet152 right and ResNet34 over-split. That
is one recording and it was not verified by listening, so on its own it is a
hint rather than evidence; it is reported because it agrees with the
enrollment counts in 7.3 and with the separation result.

## 9. Secondary checks

### Session speaker counts from the database

Not available. The recordings belong to the desktop instance, whose PostgreSQL
lives at `C:/Users/thoule/AppData/Local/Backchannel/pgdata` and was not
running; per the task constraint it was not started. The Docker Compose
`backchannel-db-1` container is running and readable, but it is the development
database and holds 12 unrelated sessions; none of the session UUIDs above are
present in it.

### Production diarizer behaviour from the application log

`C:/Users/thoule/AppData/Local/Backchannel/backchannel.log` covers real runs,
all of them on ResNet152 (`Loaded speaker embedding model:
voxceleb_resnet152_LM.onnx`, 11 occurrences, no other model). It records 206
speaker enrollments with the best rejected similarity distributed p10 0.000,
p50 0.487, p90 0.664, max 0.719. Nearly a tenth of enrollment decisions land
within 0.02 of the 0.68 threshold, so threshold placement is consequential at
the current operating point. The log also shows 350 reuses forced by
`MAX_SPEAKER_PROFILES_PER_TRACK` and 2,960 reuses of the closest profile for
segments too short to enroll.

## 10. Limitations

State these plainly. The cost measurements are solid; the quality result is
directionally consistent and paired-significant but rests on substitute labels,
and the two should not be quoted with equal confidence.

1. No speaker ground truth was established. The evaluation was designed around
   the split tracks as labels and that design failed on this corpus: five of
   six two-sided recordings have speakerphone echo, and the two with a silent
   output track are in-person meetings whose mic holds several people. Nothing
   here was validated against known speaker identities.
2. The label-free substitute uses easy positives. Contiguous windows share a
   breath, a channel and a moment, so the absolute error rates in 7.2 are
   optimistic for both models. The comparison is still fair, since both face
   the identical task on identical pairs, but these are not diarization error
   rates and should never be quoted as such.
3. The bootstrap treats 278 pairs as independent when they cluster within
   speech runs and within nine tracks, so the real interval is wider than
   [+0.287, +1.096]. The 1.5 s result has margin for that; the 3.0 s result at
   40 pairs is marginal on its own and is corroboration, not proof.
4. The negatives assume two different meetings have different remote
   participants. Recurring colleagues would put some same-speaker pairs in the
   negative set, which inflates measured error for both models equally.
5. One machine, one microphone, one primary user. Nothing here speaks to how
   either model behaves across microphones, rooms, accents or languages, and a
   deeper model's advantage is exactly the kind of thing that can change with
   channel conditions.
6. Agreement is not accuracy, and 83.8 percent is a permutation-optimal
   ceiling.
7. The distributions in 7.3 are conditioned on the 0.68 decision, so they
   characterise the current operating point rather than separability.
8. The machine was shared with concurrent agent lanes for part of the run.
   Ratios in section 5 are stable across configurations and are the figures to
   rely on; absolute milliseconds drifted between an idle first pass and a
   contended second one, and the per-embedding CPU printed by `margin` is
   indicative only.
9. `MAX_SPEAKER_PROFILES_PER_TRACK` is 4, and the application log shows the cap
   binding 350 times. Beyond four speakers the registry stops discriminating
   regardless of which embedding model is loaded, so on the busiest calls the
   model choice is not the limiting factor and this result does not apply.

### What would settle it

Two options, in order of cost.

The cheap one, and the reason the harness now validates labels instead of
trusting them: collect five to ten more dual-track calls recorded on
headphones. `diarizer_ab.py margin` already rejects echo-contaminated
recordings automatically, so the only operational requirement is that the local
user wears headphones and that the call has at least two remote participants.
Ten such calls would give hundreds of verified same-speaker and
different-speaker windows, which is enough to resolve a one-point difference in
equal error rate and to tune `SPEAKER_SIMILARITY_THRESHOLD` per model with
evidence rather than by inference. The two conditions that ruined this corpus,
echo and in-person recording, are both detectable up front by the checks in
section 3.

The thorough one: score both models end to end on a public diarization
benchmark with reference annotations, such as AMI, VoxConverse or DIHARD,
reporting diarization error rate at each model's tuned threshold. That measures
the quantity Backchannel actually cares about, including the segmentation and
overlap behaviour that dominates real meetings, and it is the only route to a
claim about diarization quality rather than pairwise verification.

Neither is needed to act on this report, since the recommendation is to change
nothing. They matter if someone later wants to revisit the trade, most likely
to offer ResNet34 on constrained hardware.

## 11. Reproducing

```
cd backend
python scripts/download_models.py --optional
python scripts/diarizer_ab.py cost --both-spin
python scripts/diarizer_ab.py margin --audio-root <DATA_DIR>/audio \
    --window-seconds 1.5 --own-min-rms 0.020 --max-segments 400
python scripts/diarizer_ab.py pipeline <mixed wav files>
```

`--optional` is opt-in and a normal install is unaffected: the default
`download_models.py` run still fetches only `silero_vad.onnx` and
`voxceleb_resnet152_LM.onnx`, and nothing at runtime reads the ResNet34 file.

The VAD pass and the embeddings are cached under
`<tempdir>/diarizer_ab_cache`, keyed by file identity, VAD threshold, model and
the exact window set, so re-running an analysis with different metrics costs
nothing. Delete that directory to force a recompute.

The downloaded `backend/models/voxceleb_resnet34_LM.onnx` has already been
removed. `backend/models/` is a tracked directory in a checkout several lanes
are working in, and leaving a 25 MB untracked binary there invites an
accidental `git add -A`. Re-fetching it is one command, and because the
embedding cache is keyed on the model filename rather than its contents, a
re-download lands on the existing cache and the analysis above reproduces
immediately without re-embedding anything.
