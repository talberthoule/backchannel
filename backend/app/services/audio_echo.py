"""Echo-cancelled mixdown for downloaded call audio.

The stored mixed recording is mic + system summed. On a speakerphone the remote
voice reaches the microphone acoustically a couple of hundred milliseconds after
it already arrived digitally on the system track, so the sum carries the remote
side twice. Measured on a real 58-minute call, coherence says 50 to 73 percent
of the microphone's energy is far-end audio - the echo is roughly as loud as the
local talker, and it lands far past the ~50 ms fusion threshold, so it is heard
as a distinct repeat rather than as coloration.

This only ever affected the mixed file. The live pipeline diarizes each track
separately and mixes solely for the audio gateway, so transcription and speaker
attribution never saw the echo. It is a listening problem, and it is fixed here
at download time rather than at capture time: the stored tracks stay untouched,
so re-transcription and any later analysis still operate on exactly the audio
the call produced.

Method: de-drift the reference along a measured delay trajectory, then run a
partitioned block frequency-domain NLMS filter (overlap-save, one FFT per block,
per-partition weight update) over the aligned pair, with a foreground/background
filter pair guarding the output. Four properties of the real recording forced
that shape.

The path is not one tap. A Wiener fit of the real path puts 80 percent of its
energy in a single 32 ms bin but only 97 percent within 100 ms of the direct
arrival, spread over many taps. Subtracting a delayed, scaled copy can therefore
only ever remove a fraction of it, which is why a delay-plus-gain model measured
23 percent reduction on this recording.

The delay slides, and that - not the filter - was the binding constraint. Across
one call it measured 218, 225, 234, 244, 253, 353 and 452 ms: a smooth 18 ppm
slide, because the microphone and the system-audio capture run off different
device clocks, punctuated by two ~100 ms resync jumps. On ground truth built
from this call's own audio, an adaptive filter reaches 13.6 to 17.3 dB ERLE
against a static path and only 2.3 to 6.1 dB once that drift is present - and no
choice of step size or tap span recovers it, because the tracking time constant
(taps / step / rate) can never be short enough to follow the delay without the
step being so large that misadjustment eats the gain. So the drift is measured
by whitened cross-correlation over 4-second segments and divided out first, by
resampling the reference along a smoothed trajectory. What is left is a static
path a short filter can actually converge on.

Echo comes and goes. The last twelve minutes of the same call have no measurable
echo at all (0.1 to 0.5 percent coherent, against 50 to 73 percent earlier) -
someone put headphones on. A filter left adapting there converts far-end audio
into noise and adds up to 7 dB to the near-end track. Passing audio through
untouched is the correct output for that stretch, so the output is driven by a
foreground filter that is only ever replaced by a background copy that has
measurably beaten both it and plain passthrough, and is reset to zero when it
stops beating passthrough.

Near-end speech is loud. The local talker is present through most of the echo,
so the filter adapts under a disturbance roughly its own size. That is what the
double-talk gate and the modest step size are for; both are set from the ground
truth rig rather than from theory.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Delay trajectory. 4-second segments: long enough for a whitened correlation
# peak to stand out of the floor at the measured coherence, short enough that
# the 18 ppm slide only smears the peak by about one sample inside a segment.
_TRAJECTORY_SEGMENT_S = 4.0
_MAX_DELAY_MS = 900.0
# Peak-to-floor ratio a segment must clear to be believed. Measured over the
# real call, echo-bearing segments score 13 to 35 (median 29) and echo-free ones
# 2.6 to 8.7 (median 4.9), so this sits in the gap: it keeps 96 percent of the
# real ones and rejects 93 percent of the confident-looking nonsense the dead
# stretch produces.
_TRAJECTORY_CONFIDENCE = 8.0
_TRAJECTORY_MEDIAN = 3
# Aligning to exactly zero would need the filter to model negative delay, which
# an overlap-save FIR cannot. Leave the echo sitting this far inside the span so
# trajectory error in either direction is still reachable.
_ALIGN_MARGIN_MS = 64.0
_WARP_FFT = 4096

# Tap span, measured from the aligned reference: the margin above plus the
# room's ~150 ms tail, with room for trajectory error. Longer is not free -
# NLMS misadjustment grows with tap count.
_SPAN_MS = 384.0
# Used when no trajectory could be measured, where the filter has to cover the
# raw delay range on its own. It will not cancel much, but the output guard
# means it will not hurt either.
_FALLBACK_SPAN_MS = 832.0
# 64 ms blocks: 54k iterations for a 58-minute file, and fine enough that the
# double-talk gate and the filter swap both act inside a syllable.
_BLOCK_MS = 64.0

# Step size. Against a de-drifted reference the path is static, so this trades
# purely against misadjustment: NLMS leaves residual echo of step/(2-step) times
# whatever disturbance it is adapting under, and here the local talker is that
# disturbance at roughly the echo's own level.
_STEP = 0.3
# Never freeze completely. A hard freeze deadlocks: after a path change the
# echo estimate is wrong, the gate reads that as double talk, and the filter can
# never re-converge. A floor lets it bootstrap - a little correct echo raises
# the gate, which raises the step.
_STEP_FLOOR = 0.12
# ... and the gate only applies once there is something worth protecting. While
# the filter in use is not beating passthrough by this margin there is no
# converged state for double talk to corrupt, so it adapts at full step. Without
# this, recovering from a 100 ms resync jump took 40 seconds (measured), because
# a filter reset to zero explains none of the microphone and the gate read that
# as permanent double talk.
_ACQUIRE_MARGIN = 0.95
# Full step persists this long after the filter starts beating passthrough
# again. Without the hold it switches off the instant the foreground is 5 per
# cent better - which happens in the first second of re-convergence, throttling
# the filter back down before it has actually converged. Six time constants at
# the configured step.
_ACQUIRE_HOLD_S = 8.0
# Diagonal loading on the per-bin reference power, as a fraction of the average
# loud-block power. Without an absolute floor a near-silent block divides by
# almost nothing and the filter explodes; a first attempt used a fraction of the
# current block's power and reached -80 dB output gain.
_POWER_REGULARIZATION = 2e-3
_POWER_SMOOTHING = 0.5

# Reference-activity gate, relative to the file's own loud level, plus an
# absolute floor for tracks that are digitally silent.
_ACTIVE_LEVEL_DB = -45.0
_SILENCE_RMS = 12.0

# Decision smoothing for the filter swap, in seconds. Long enough that one
# syllable cannot trigger a swap, short enough to catch a dead echo path in a
# couple of seconds.
_DECISION_TAU_S = 1.5
# The background must beat the foreground by this margin to replace it. Only
# just: each promotion resets the pair to equality, so a large margin turns the
# foreground into a coarse ratchet that has to re-earn every step. At 0.85 the
# output filter updated 14 times in four minutes and took 35 seconds to recover
# from a resync jump the background had already tracked in under five.
_PROMOTE_MARGIN = 0.98
# It must also beat plain passthrough. This is the clause that keeps the filter
# out of echo-free stretches entirely: nothing there ever beats doing nothing.
_PASSTHROUGH_MARGIN = 0.90
# ... and the reverse. A foreground that stops beating passthrough is stale (the
# path moved or went away) and is dropped back to zero.
_DEMOTE_MARGIN = 1.05
_MIN_DECISION_BLOCKS = 12

# Convergence takes a few seconds of far-end speech, which the front of the file
# would otherwise pay for. Offline we can afford to run the opening twice and
# keep only the second pass.
_WARMUP_S = 60.0


def _read_all(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected mono PCM16")
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float64), rate


def _plan(rate: int, span_ms: float) -> tuple[int, int]:
    """Block size (a power of two near _BLOCK_MS) and partition count."""
    block = 1 << max(6, int(round(np.log2(max(rate * _BLOCK_MS / 1000.0, 64)))))
    partitions = max(1, int(np.ceil(span_ms / 1000.0 * rate / block)))
    return block, partitions


def delay_trajectory(mic: np.ndarray, ref: np.ndarray, rate: int) -> np.ndarray | None:
    """Per-segment delay of the reference inside the microphone, in samples.

    Whitened (phase-transform) cross-correlation, because the room response is
    diffuse: plain correlation peaks broadly and reads the loudest spectral
    overlap rather than the path delay. Segments whose peak does not stand clear
    of the correlation floor are dropped, not interpolated over blindly - the
    echo-free tail of a call produces confident-looking nonsense otherwise.

    Returns one delay per segment, spaced a half-segment apart and describing
    the centre of the segment it was measured over, or None when too little of
    the call has a measurable echo to be worth aligning.
    """
    segment = int(_TRAJECTORY_SEGMENT_S * rate)
    hop = segment // 2
    n = min(len(mic), len(ref))
    if n < 4 * segment:
        return None
    max_lag = int(_MAX_DELAY_MS / 1000.0 * rate)
    size = 1 << int(np.ceil(np.log2(2 * segment)))

    starts = np.arange(0, n - segment + 1, hop)
    lags = np.full(len(starts), np.nan)
    for i, start in enumerate(starts):
        a = mic[start: start + segment]
        b = ref[start: start + segment]
        spectrum = np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size))
        magnitude = np.abs(spectrum)
        spectrum = np.divide(spectrum, magnitude, out=np.zeros_like(spectrum),
                             where=magnitude > 1e-12)
        correlation = np.fft.irfft(spectrum, size)[: max_lag + 2]
        peak = int(np.argmax(correlation))
        floor = float(np.sqrt(np.mean(correlation ** 2)))
        if floor <= 0 or correlation[peak] < _TRAJECTORY_CONFIDENCE * floor:
            continue
        if 0 < peak < len(correlation) - 1:
            # Parabolic interpolation: the drift is a fraction of a sample per
            # second, so integer resolution would quantize it into a staircase
            # the filter then has to chase.
            left, mid, right = correlation[peak - 1: peak + 2]
            denominator = left - 2 * mid + right
            offset = 0.5 * (left - right) / denominator if denominator else 0.0
            lags[i] = peak + np.clip(offset, -0.5, 0.5)
        else:
            lags[i] = peak

    good = ~np.isnan(lags)
    if good.sum() < max(4, 0.05 * len(lags)):
        return None

    # Median filter over the accepted points before filling the gaps: it drops
    # single-segment outliers while keeping a real resync jump a step rather
    # than smearing it into a ramp.
    index = np.flatnonzero(good)
    values = lags[index]
    half = _TRAJECTORY_MEDIAN // 2
    smoothed = np.array([
        np.median(values[max(0, i - half): i + half + 1]) for i in range(len(values))
    ])
    return np.interp(np.arange(len(lags)), index, smoothed)


def _align_reference(ref: np.ndarray, trajectory: np.ndarray, rate: int) -> np.ndarray:
    """Resample the reference so the echo it explains stops moving.

    Overlap-add with a fractional delay applied as a phase ramp: the integer
    part is a read offset and the remainder is exact band-limited interpolation.
    Linear interpolation would have done the arithmetic but not the job - its
    error is worst exactly where cancellation is hardest to get, in the top
    octaves, and it varies as the fractional delay walks, so the filter cannot
    learn it away.
    """
    segment = int(_TRAJECTORY_SEGMENT_S * rate)
    hop_traj = segment // 2
    margin = _ALIGN_MARGIN_MS / 1000.0 * rate
    nfft = _WARP_FFT
    hop = nfft // 2
    n = len(ref)
    blocks = (n + hop - 1) // hop

    # A trajectory point describes the centre of its segment, not its start.
    # Ignoring that offsets the whole curve by half a segment, which at 18 ppm
    # is a permanent half-sample of misalignment - small, but bought for free.
    centres = np.arange(blocks) * hop + hop
    shift = np.interp((centres - segment / 2) / hop_traj,
                      np.arange(len(trajectory)), trajectory) - margin
    whole = np.floor(shift).astype(np.int64)
    fraction = shift - whole

    pad = int(_MAX_DELAY_MS / 1000.0 * rate) + nfft
    padded = np.concatenate((np.zeros(pad), ref, np.zeros(pad + nfft)))
    window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(nfft) / nfft)
    ramp = np.arange(nfft // 2 + 1)
    out = np.zeros(n + nfft)

    step = 512
    offsets = np.arange(nfft)
    for first in range(0, blocks, step):
        last = min(first + step, blocks)
        base = (np.arange(first, last) * hop - whole[first:last] + pad)
        frames = padded[base[:, None] + offsets[None, :]] * window
        spectra = np.fft.rfft(frames, axis=-1)
        spectra *= np.exp(-2j * np.pi * np.outer(fraction[first:last], ramp) / nfft)
        frames = np.fft.irfft(spectra, nfft, axis=-1)
        for j in range(last - first):
            start = (first + j) * hop
            out[start: start + nfft] += frames[j]
    return out[:n]


def cancel_echo(mic: np.ndarray, ref: np.ndarray, rate: int) -> np.ndarray:
    """Near-end track with the far end's acoustic bleed removed.

    Returns a copy the same length as ``mic``. Where the far end has been silent
    for longer than the tap span the result is bit-identical to the input: the
    filter is an FIR of the reference, so a zero reference produces a zero
    estimate and nothing is subtracted.
    """
    n = min(len(mic), len(ref))
    whole_mic = np.asarray(mic[:n], dtype=np.float64)
    mic = whole_mic
    ref = np.asarray(ref[:n], dtype=np.float64)

    trajectory = delay_trajectory(mic, ref, rate)
    if trajectory is None:
        logger.info("[audio_echo] no measurable delay trajectory; wide-span fallback")
        span_ms = _FALLBACK_SPAN_MS
    else:
        logger.info(
            "[audio_echo] delay trajectory %.0f to %.0f ms over the call",
            trajectory.min() / rate * 1000, trajectory.max() / rate * 1000,
        )
        ref = _align_reference(ref, trajectory, rate)
        span_ms = _SPAN_MS

    block, partitions = _plan(rate, span_ms)
    if n < block * (partitions + 2):
        return mic.copy()

    blocks = n // block
    mic = mic[: blocks * block]
    ref = ref[: blocks * block]
    nfft = 2 * block
    bins = nfft // 2 + 1

    # Reference activity per block, and the loud-block level the power floor and
    # the activity gate are both expressed relative to.
    block_power = (ref.reshape(blocks, block) ** 2).mean(axis=1)
    loud = block_power[block_power > _SILENCE_RMS ** 2]
    if not loud.size:
        return mic.copy()
    active_level = float(np.percentile(loud, 75))
    gate = max(active_level * 10 ** (_ACTIVE_LEVEL_DB / 10), _SILENCE_RMS ** 2)
    regularization = _POWER_REGULARIZATION * partitions * nfft * active_level

    fore = np.zeros((partitions, bins), dtype=np.complex128)
    back = np.zeros((partitions, bins), dtype=np.complex128)
    spectra = np.zeros((2 * partitions, bins), dtype=np.complex128)
    powers = np.zeros((2 * partitions, bins), dtype=np.float64)
    smoothed_power = np.zeros(bins, dtype=np.float64)
    out = np.zeros(blocks * block, dtype=np.float64)
    padded_ref = np.concatenate((np.zeros(block), ref))
    fade = np.linspace(0.0, 1.0, block, endpoint=False)
    silent_head = np.zeros(block, dtype=np.float64)

    decay = float(np.exp(-block / (_DECISION_TAU_S * rate)))
    acquire_hold = max(1, int(_ACQUIRE_HOLD_S * rate / block))
    acquiring = acquire_hold
    mic_energy = fore_energy = back_energy = 0.0
    decided = 0
    promotions = demotions = adapted = 0

    warmup = min(blocks, int(_WARMUP_S * rate / block))
    schedule = list(range(warmup)) + list(range(blocks))
    live_from = len(schedule) - blocks

    for index, t in enumerate(schedule):
        spectrum = np.fft.rfft(padded_ref[t * block: t * block + nfft])
        slot = t % partitions
        spectra[slot] = spectrum
        spectra[slot + partitions] = spectrum
        powers[slot] = spectrum.real ** 2 + spectrum.imag ** 2
        powers[slot + partitions] = powers[slot]
        history = spectra[slot + 1: slot + 1 + partitions]

        estimate = np.fft.irfft(np.einsum("pk,pk->k", back, history))[block:]
        near = mic[t * block: (t + 1) * block]
        back_error = near - estimate
        if fore.any():
            fore_estimate = np.fft.irfft(np.einsum("pk,pk->k", fore, history))[block:]
            fore_error = near - fore_estimate
        else:
            fore_error = near

        active = block_power[t] > gate
        emit = fore_error
        if active:
            mic_energy = decay * mic_energy + (1 - decay) * float(near @ near)
            fore_energy = decay * fore_energy + (1 - decay) * float(fore_error @ fore_error)
            back_energy = decay * back_energy + (1 - decay) * float(back_error @ back_error)
            decided += 1

            if decided >= _MIN_DECISION_BLOCKS:
                if (back_energy < _PROMOTE_MARGIN * fore_energy
                        and back_energy < _PASSTHROUGH_MARGIN * mic_energy):
                    # Cross-fade rather than switch: the two filters differ, and
                    # a hard swap steps the waveform mid-syllable.
                    emit = fore_error + fade * (back_error - fore_error)
                    fore = back.copy()
                    fore_energy = back_energy
                    promotions += 1
                elif fore_energy > _DEMOTE_MARGIN * mic_energy:
                    # The foreground is now worse than doing nothing: the path
                    # moved or stopped existing. Drop it and fall back to the
                    # microphone. The background is deliberately left alone -
                    # what usually triggers this is a resync jump, where the
                    # reference is briefly incoherent while the trajectory steps
                    # and the background is a second away from being right
                    # again. Wiping it too turned a 256 ms glitch into a full
                    # re-convergence from zero.
                    emit = fore_error + fade * (near - fore_error)
                    fore = np.zeros_like(fore)
                    fore_energy = mic_energy
                    demotions += 1

        if index >= live_from:
            out[t * block: (t + 1) * block] = emit

        if not active:
            continue
        adapted += 1

        # Freeze-free double-talk control. This ratio is the share of the mic
        # block the current echo estimate accounts for: near 1 when the far end
        # is all that is in the microphone, and falling towards 0 as the local
        # talker adds energy the reference cannot explain. Scaling the step by
        # it slows adaptation exactly when fitting would be fitting near-end
        # speech, which is the classic way these filters diverge - but only once
        # there is a converged filter whose accuracy is worth protecting.
        if fore_energy >= _ACQUIRE_MARGIN * mic_energy:
            acquiring = acquire_hold
        if acquiring > 0:
            acquiring -= 1
            step = _STEP
        else:
            near_energy = float(near @ near)
            explained = float(estimate @ near) / near_energy if near_energy > 0 else 0.0
            step = _STEP * min(1.0, max(_STEP_FLOOR, explained))

        span_power = powers[slot + 1: slot + 1 + partitions].sum(axis=0)
        smoothed_power = (_POWER_SMOOTHING * smoothed_power
                          + (1 - _POWER_SMOOTHING) * span_power)
        error_spectrum = np.fft.rfft(np.concatenate((silent_head, back_error)))
        back += history.conj() * (step * error_spectrum / (smoothed_power + regularization))

        # Round-robin gradient constraint: each partition must stay a
        # block-length impulse response, or the overlap-save output stops being
        # a linear convolution. One partition per block keeps every one of them
        # constrained within a tap span and costs a single FFT pair.
        constrained = np.fft.irfft(back[slot])
        constrained[block:] = 0.0
        back[slot] = np.fft.rfft(constrained)

    logger.info(
        "[audio_echo] %d blocks, adapted in %d (%.0f%%), %d filter promotions, "
        "%d resets",
        blocks, adapted, 100.0 * adapted / max(blocks, 1), promotions, demotions,
    )

    # The trailing partial block is passed through rather than dropped, so the
    # caller can rely on getting back exactly what it handed over.
    if len(out) < n:
        out = np.concatenate((out, whole_mic[len(out):]))
    return out


def cancel_and_mix(mic: np.ndarray, system: np.ndarray, rate: int) -> np.ndarray:
    """Remove the system track's bleed from mic, then remix both cleanly."""
    n = min(len(mic), len(system))
    system = np.asarray(system[:n], dtype=np.float64)
    near = cancel_echo(np.asarray(mic[:n], dtype=np.float64), system, rate)
    return np.clip(near + system, -32768, 32767)


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.rint(samples).astype(np.int16).tobytes())


def build_echo_cancelled_mix(mic_path: Path, system_path: Path, out_path: Path) -> Path:
    """Produce (and cache) an echo-cancelled mixdown of two split tracks."""
    mic, rate = _read_all(mic_path)
    system, system_rate = _read_all(system_path)
    if rate != system_rate:
        raise ValueError(f"track sample rates differ: {rate} vs {system_rate}")
    mixed = cancel_and_mix(mic, system, rate)
    write_wav(out_path, mixed, rate)
    return out_path
