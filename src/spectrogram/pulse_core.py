from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any
import numpy as np
import soundfile as sf


@dataclass
class PingRegion:
    """
    Container for one detected pulse region in the slowed TE waveform.

    The analyser works in sample/time regions rather than abstract "calls" because
    each detected unit starts life as a thresholded envelope segment. Those regions
    are then refined, merged if necessary, and finally annotated as normal hunting
    pulses or terminal buzz pulses.
    """

    start_sample: int
    end_sample: int
    start_time_s: float
    end_time_s: float
    peak_time_s: float
    peak_amplitude: float
    is_feeding_buzz: bool = False


def _load_audio_mono(path: str) -> Tuple[np.ndarray, int]:
    """
    Read a WAV file, fold stereo to mono if needed, and normalise peak level.

    Purpose:
    the rest of the analyser assumes a single waveform and a broadly comparable
    amplitude scale across files. Peak normalisation does not preserve absolute
    recording level, but it makes envelope thresholds much more stable for the
    cleaned TE recordings this analyser is designed for.
    """
    samples, sr = sf.read(path)
    samples = np.asarray(samples, dtype=np.float64)

    if samples.ndim == 2:
        samples = np.mean(samples, axis=1)

    if len(samples) == 0:
        raise ValueError(f"No audio data found in '{path}'")

    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak

    return samples, sr



def _build_envelope(samples: np.ndarray, sr: int, smooth_ms: float) -> np.ndarray:
    """
    Build a simple smoothed amplitude envelope from the waveform.

    Purpose:
    pulse detection is much easier on a rectified, smoothed envelope than on the
    raw oscillating waveform. The envelope turns each pulse into a broad shape that
    better reflects the attack and conical decay you want to identify in TE calls.
    """
    rectified = np.abs(samples)
    window = max(1, int(round(sr * smooth_ms / 1000.0)))
    kernel = np.ones(window, dtype=np.float64) / window
    return np.convolve(rectified, kernel, mode="same")



def _detect_active_regions(
    envelope: np.ndarray,
    sr: int,
    threshold_sigma: float,
    threshold_percentile: float,
    min_threshold: float,
    max_gap_ms: float,
    min_region_ms: float,
) -> np.ndarray:
    """
    Convert the continuous envelope into a boolean mask of active vs inactive audio.

    Purpose:
    this is the first coarse detection stage. It estimates a robust background level,
    applies a threshold, bridges very short inactive gaps that would otherwise split a
    single pulse, and removes very short active fragments that are more likely to be
    residual noise than genuine bat-call structure.
    """
    noise_floor = np.percentile(envelope, threshold_percentile)
    env_median = np.median(envelope)
    env_mad = np.median(np.abs(envelope - env_median)) * 1.4826
    threshold = max(min_threshold, noise_floor + threshold_sigma * env_mad)

    mask = envelope >= threshold

    gap_samples = max(1, int(round(sr * max_gap_ms / 1000.0)))
    min_region_samples = max(1, int(round(sr * min_region_ms / 1000.0)))

    mask = _fill_short_false_gaps(mask, gap_samples)
    mask = _remove_short_true_runs(mask, min_region_samples)

    return mask



def _mask_to_regions(mask: np.ndarray) -> List[Tuple[int, int]]:
    """
    Convert a boolean activity mask into a list of contiguous sample ranges.

    Purpose:
    later stages work with explicit start/end regions rather than a sample-level mask.
    Padding the mask with False values at each end makes rising and falling edges easy
    to find via a simple difference operation.
    """
    if len(mask) == 0:
        return []

    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    changes = np.diff(padded)

    starts = np.where(changes == 1)[0]
    ends = np.where(changes == -1)[0]

    return [(int(s), int(e)) for s, e in zip(starts, ends)]



def _refine_regions(
    samples: np.ndarray,
    envelope: np.ndarray,
    sr: int,
    candidate_regions: List[Tuple[int, int]],
    pre_padding_ms: float,
    post_padding_ms: float,
    attack_threshold_fraction: float,
    decay_threshold_fraction: float,
) -> List[PingRegion]:
    """
    Refine coarse candidate regions so they better match pulse attack and decay shape.

    Purpose:
    the initial threshold mask is intentionally blunt. This stage adds a little padding,
    finds the local envelope peak, then redefines the start and end using fractions of
    that peak so the region better captures the sharp attack and the longer trailing
    decay. The result is a more biologically useful pulse window for plotting and for
    downstream measurements.
    """
    pre_pad = int(round(sr * pre_padding_ms / 1000.0))
    post_pad = int(round(sr * post_padding_ms / 1000.0))

    refined: List[PingRegion] = []

    for start, end in candidate_regions:
        s0 = max(0, start - pre_pad)
        e0 = min(len(samples), end + post_pad)

        local_env = envelope[s0:e0]
        if len(local_env) == 0:
            continue

        peak_rel = int(np.argmax(local_env))
        peak_val = float(local_env[peak_rel])

        if peak_val <= 0:
            continue

        attack_level = peak_val * attack_threshold_fraction
        decay_level = peak_val * decay_threshold_fraction

        left = local_env[:peak_rel + 1]
        attack_hits = np.where(left >= attack_level)[0]
        refined_start = s0 + int(attack_hits[0]) if len(attack_hits) else s0

        right = local_env[peak_rel:]
        decay_hits = np.where(right >= decay_level)[0]
        refined_end = s0 + peak_rel + int(decay_hits[-1]) + 1 if len(decay_hits) else e0

        refined_start = max(0, refined_start)
        refined_end = min(len(samples), refined_end)

        if refined_end <= refined_start:
            continue

        signal_slice = np.abs(samples[refined_start:refined_end])
        if len(signal_slice) == 0:
            continue

        # The peak stored on the region is taken from the raw signal slice rather than
        # from the envelope so inter-pulse timing uses the sharpest point available.
        raw_peak_rel = int(np.argmax(signal_slice))
        raw_peak_amp = float(signal_slice[raw_peak_rel])
        raw_peak_abs = refined_start + raw_peak_rel

        refined.append(
            PingRegion(
                start_sample=refined_start,
                end_sample=refined_end,
                start_time_s=refined_start / sr,
                end_time_s=refined_end / sr,
                peak_time_s=raw_peak_abs / sr,
                peak_amplitude=raw_peak_amp,
                is_feeding_buzz=False,
            )
        )

    return _merge_overlaps(refined, sr)


def _merge_overlaps(regions: List[PingRegion], sr: int) -> List[PingRegion]:
    """
    Merge overlapping or touching regions into a single region.

    Purpose:
    refinement and buzz recovery can produce overlapping windows. Downstream logic
    expects one region per detected pulse window, so overlaps are collapsed here.
    The timing and amplitude of the strongest member of the merged group are kept as
    the representative peak.
    """
    if not regions:
        return []

    regions = sorted(regions, key=lambda r: r.start_sample)
    merged = [regions[0]]

    for region in regions[1:]:
        last = merged[-1]

        if region.start_sample <= last.end_sample:
            new_start = last.start_sample
            new_end = max(last.end_sample, region.end_sample)
            strongest = last if last.peak_amplitude >= region.peak_amplitude else region

            merged[-1] = PingRegion(
                start_sample=new_start,
                end_sample=new_end,
                start_time_s=new_start / sr,
                end_time_s=new_end / sr,
                peak_time_s=strongest.peak_time_s,
                peak_amplitude=strongest.peak_amplitude,
                is_feeding_buzz=last.is_feeding_buzz or region.is_feeding_buzz,
            )
        else:
            merged.append(region)

    return merged



def _fill_short_false_gaps(mask: np.ndarray, max_gap_samples: int) -> np.ndarray:
    """
    Fill short inactive gaps inside otherwise continuous active regions.

    Purpose:
    small dips in the envelope can appear inside one real pulse, especially in noisy
    or highly structured decays. Filling only short False runs helps preserve the full
    pulse shape without accidentally joining genuinely separate pulses that are farther
    apart.
    """
    result = mask.copy()
    n = len(result)
    i = 0

    while i < n:
        if result[i]:
            i += 1
            continue

        j = i
        while j < n and not result[j]:
            j += 1

        gap_len = j - i
        left_true = i > 0 and result[i - 1]
        right_true = j < n and result[j]

        if left_true and right_true and gap_len <= max_gap_samples:
            result[i:j] = True

        i = j

    return result



def _remove_short_true_runs(mask: np.ndarray, min_run_samples: int) -> np.ndarray:
    """
    Remove very short active runs from a boolean activity mask.

    Purpose:
    after thresholding, tiny positive blips can survive that are too short to be
    plausible pulse regions. Removing them early makes later region refinement and
    buzz identification more stable.
    """
    result = mask.copy()
    n = len(result)
    i = 0

    while i < n:
        if not result[i]:
            i += 1
            continue

        j = i
        while j < n and result[j]:
            j += 1

        run_len = j - i
        if run_len < min_run_samples:
            result[i:j] = False

        i = j

    return result



def _compute_time_metrics(
    region: PingRegion,
    prev_region: PingRegion | None,
    next_region: PingRegion | None,
    expansion_factor: float,
) -> Dict[str, Any]:
    """
    Compute timing metrics for one pulse, including inter-pulse intervals.

    Purpose:
    timing is central to behavioural interpretation. This function keeps all of the
    expanded-time and converted real-time timing fields together in one place so the
    JSON output remains consistent and easy to extend.
    """
    duration_s = region.end_time_s - region.start_time_s

    ipi_prev_s = None
    if prev_region is not None:
        ipi_prev_s = region.peak_time_s - prev_region.peak_time_s

    ipi_next_s = None
    if next_region is not None:
        ipi_next_s = next_region.peak_time_s - region.peak_time_s

    return {
        "start_time_s": region.start_time_s,
        "end_time_s": region.end_time_s,
        "peak_time_s": region.peak_time_s,
        "duration_ms": duration_s * 1000.0,
        "real_start_time_s": region.start_time_s / expansion_factor,
        "real_end_time_s": region.end_time_s / expansion_factor,
        "real_peak_time_s": region.peak_time_s / expansion_factor,
        "real_duration_ms": duration_s * 1000.0 / expansion_factor,
        "ipi_prev_ms": None if ipi_prev_s is None else ipi_prev_s * 1000.0,
        "ipi_next_ms": None if ipi_next_s is None else ipi_next_s * 1000.0,
        "real_ipi_prev_ms": None if ipi_prev_s is None else ipi_prev_s * 1000.0 / expansion_factor,
        "real_ipi_next_ms": None if ipi_next_s is None else ipi_next_s * 1000.0 / expansion_factor,
    }
