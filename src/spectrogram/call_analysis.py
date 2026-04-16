from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import List, Tuple, Dict, Any

import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

from spectrogram.config_reader import get_call_analysis_property


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



def analyse_audio_file(input: str, expansion_factor: float, output_folder: str):
    """
    Run the full TE call-analysis pipeline for one cleaned WAV file.

    Purpose:
    it provides a single entry point for downstream code and keeps the overall
    workflow easy to understand. The function deliberately reads like a pipeline:
    load audio, build an envelope, detect candidate regions, refine them, identify
    a terminal feeding buzz, optionally recover missed buzz pulses, then emit the
    two user-facing artefacts: a diagnostic plot and a JSON summary.

    Parameters
    ----------
    input:
        Path to the WAV file.
    expansion_factor:
        TE expansion factor (for example 10.0). This is used when converting
        expanded-time timings and audio frequencies back to estimated real-time
        bat-call values.
    output_folder:
        Folder where the output files are written

    Returns
    -------
    dict
        Summary including detected regions, output plot path, JSON path, and the
        pulse-level summaries written to disk.
    """
    samples, sr = _load_audio_mono(input)
    duration_s = len(samples) / sr

    envelope = _build_envelope(
        samples=samples,
        sr=sr,
        smooth_ms=float(get_call_analysis_property("envelope_smooth_ms")),
    )

    active_mask = _detect_active_regions(
        envelope=envelope,
        sr=sr,
        threshold_sigma=float(get_call_analysis_property("threshold_sigma")),
        threshold_percentile=float(get_call_analysis_property("noise_floor_percentile")),
        min_threshold=float(get_call_analysis_property("min_threshold")),
        max_gap_ms=float(get_call_analysis_property("max_gap_ms")),
        min_region_ms=float(get_call_analysis_property("min_region_ms")),
    )

    candidate_regions = _mask_to_regions(active_mask)

    refined_regions = _refine_regions(
        samples=samples,
        envelope=envelope,
        sr=sr,
        candidate_regions=candidate_regions,
        pre_padding_ms=float(get_call_analysis_property("pre_padding_ms")),
        post_padding_ms=float(get_call_analysis_property("post_padding_ms")),
        attack_threshold_fraction=float(get_call_analysis_property("attack_threshold_fraction")),
        decay_threshold_fraction=float(get_call_analysis_property("decay_threshold_fraction")),
    )

    refined_regions = _mark_feeding_buzz(
        regions=refined_regions,
        buzz_max_ipi_ms=float(get_call_analysis_property("buzz_max_ipi_ms")),
        buzz_min_run_length=int(get_call_analysis_property("buzz_min_run_length")),
        buzz_search_tail_fraction=float(get_call_analysis_property("buzz_search_tail_fraction")),
        expansion_factor=expansion_factor,
    )

    if bool(get_call_analysis_property("buzz_recovery_enabled")):
        refined_regions = _recover_missing_buzz_pulses(
            samples=samples,
            envelope=envelope,
            sr=sr,
            regions=refined_regions,
            recovery_threshold_fraction=float(
                get_call_analysis_property("buzz_recovery_threshold_fraction")
            ),
            min_peak_distance_ms=float(
                get_call_analysis_property("buzz_recovery_min_peak_distance_ms")
            ),
            region_ms=float(get_call_analysis_property("buzz_recovery_region_ms")),
            expansion_factor=expansion_factor,
        )

    plot_path = _plot_waveform_with_regions(
        samples=samples,
        sr=sr,
        regions=refined_regions,
        input_path=input,
        expansion_factor=expansion_factor,
        output_folder=output_folder
    )

    pulse_summaries = _build_pulse_summaries(
        samples=samples,
        envelope=envelope,
        sr=sr,
        regions=refined_regions,
        expansion_factor=expansion_factor,
    )

    json_path = _write_analysis_json(
        input_path=input,
        sample_rate=sr,
        duration_s=duration_s,
        expansion_factor=expansion_factor,
        pulses=pulse_summaries,
        output_folder=output_folder
    )

    return {
        "input": str(input),
        "sample_rate": sr,
        "duration_s": duration_s,
        "expansion_factor": expansion_factor,
        "real_time_duration_s": duration_s / expansion_factor,
        "region_count": len(refined_regions),
        "plot_path": str(plot_path),
        "json_path": str(json_path),
        "pulses": pulse_summaries,
    }



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



def _mark_feeding_buzz(
    regions: List[PingRegion],
    buzz_max_ipi_ms: float,
    buzz_min_run_length: int,
    buzz_search_tail_fraction: float,
    expansion_factor: float,
) -> List[PingRegion]:
    """
    Identify the terminal feeding buzz as the densest late-stage run of closely
    spaced pulses.

    Earlier versions required every IPI in a run to fall below the threshold.
    In practice, real buzzes often contain a small irregularity at the start,
    so this version allows a single over-threshold gap within an otherwise
    buzz-like run.
    The configured buzz IPI threshold is interpreted in real bat time, so it is
    converted back into the slowed TE time domain before being compared with the
    peak-to-peak intervals measured in the waveform.
    """
    if len(regions) < buzz_min_run_length:
        return regions

    regions = sorted(regions, key=lambda r: r.peak_time_s)

    # Restrict buzz detection to the final portion of the sequence so that
    # earlier short-IPIs are not mistaken for a terminal buzz.
    tail_start_time = regions[-1].peak_time_s * (1.0 - buzz_search_tail_fraction)
    tail_indices = [i for i, r in enumerate(regions) if r.peak_time_s >= tail_start_time]

    if len(tail_indices) < buzz_min_run_length:
        tail_indices = list(range(len(regions)))

    # Peak times are measured on the slowed TE waveform, so convert the configured
    # real-time buzz threshold into expanded-time seconds before comparing IPIs.
    buzz_max_ipi_s = (buzz_max_ipi_ms / 1000.0) * expansion_factor
    allowed_gap_breaks = 1

    best_run: List[int] = []
    current_run: List[int] = []
    gap_breaks_used = 0

    for pos, idx in enumerate(tail_indices):
        if pos == 0:
            current_run = [idx]
            gap_breaks_used = 0
            continue

        prev_idx = tail_indices[pos - 1]
        ipi = regions[idx].peak_time_s - regions[prev_idx].peak_time_s

        if ipi <= buzz_max_ipi_s:
            current_run.append(idx)
            continue

        # Allow one slightly long interval inside an otherwise dense terminal run.
        if gap_breaks_used < allowed_gap_breaks:
            current_run.append(idx)
            gap_breaks_used += 1
            continue

        if len(current_run) > len(best_run):
            best_run = current_run[:]

        current_run = [idx]
        gap_breaks_used = 0

    if len(current_run) > len(best_run):
        best_run = current_run[:]

    # Only mark a run if it contains enough genuinely short IPIs to be
    # consistent with a feeding buzz.
    if len(best_run) >= buzz_min_run_length:
        short_ipi_count = 0
        for i in range(1, len(best_run)):
            prev_idx = best_run[i - 1]
            curr_idx = best_run[i]
            ipi = regions[curr_idx].peak_time_s - regions[prev_idx].peak_time_s
            if ipi <= buzz_max_ipi_s:
                short_ipi_count += 1

        if short_ipi_count >= max(1, buzz_min_run_length - 1):
            for idx in best_run:
                regions[idx].is_feeding_buzz = True

    return regions



def _recover_missing_buzz_pulses(
    samples: np.ndarray,
    envelope: np.ndarray,
    sr: int,
    regions: List[PingRegion],
    recovery_threshold_fraction: float,
    min_peak_distance_ms: float,
    region_ms: float,
    expansion_factor: float,
) -> List[PingRegion]:
    """
    Recover narrow missed buzz pulses with a second-pass detector in the buzz tail only.

    Purpose:
    the settings that work well for broad hunting pulses can miss very short buzz
    pulses. Rather than making the whole detector more aggressive, this function only
    searches the already-identified buzz tail and picks extra local peaks there. That
    keeps the earlier conical decays more stable while still improving terminal-buzz
    coverage.
    The minimum spacing between recovered peaks is configured in real bat time,
    so it is also converted back into expanded-time samples before peak picking
    on the slowed TE waveform.
    """
    if not regions:
        return regions

    buzz_regions = [r for r in regions if r.is_feeding_buzz]
    if not buzz_regions:
        return regions

    first_buzz_start = min(r.start_sample for r in buzz_regions)
    search_env = envelope[first_buzz_start:]
    if len(search_env) == 0:
        return regions

    local_peak = float(np.max(search_env))
    if local_peak <= 0:
        return regions

    threshold = local_peak * recovery_threshold_fraction
    min_peak_distance = max(
        1, int(round(sr * (min_peak_distance_ms / 1000.0) * expansion_factor))
    )
    half_region = max(
        1, int(round(sr * (region_ms / 1000.0) * expansion_factor / 2.0))
    )

    candidate_peaks: List[int] = []
    last_peak = -min_peak_distance

    for i in range(1, len(search_env) - 1):
        if search_env[i] < threshold:
            continue

        is_peak = search_env[i] >= search_env[i - 1] and search_env[i] > search_env[i + 1]
        if not is_peak:
            continue

        abs_i = first_buzz_start + i
        if abs_i - last_peak >= min_peak_distance:
            candidate_peaks.append(abs_i)
            last_peak = abs_i

    if not candidate_peaks:
        return regions

    recovered: List[PingRegion] = []
    for peak in candidate_peaks:
        start = max(0, peak - half_region)
        end = min(len(samples), peak + half_region)

        if end <= start:
            continue

        peak_amp = float(np.max(np.abs(samples[start:end])))
        recovered.append(
            PingRegion(
                start_sample=start,
                end_sample=end,
                start_time_s=start / sr,
                end_time_s=end / sr,
                peak_time_s=peak / sr,
                peak_amplitude=peak_amp,
                is_feeding_buzz=True,
            )
        )

    combined = regions + recovered
    combined = _merge_overlaps(combined, sr)

    # Re-run the buzz labelling so the final result is internally consistent after
    # adding the recovered pulses back into the pulse train.
    combined = _mark_feeding_buzz(
        regions=combined,
        buzz_max_ipi_ms=float(get_call_analysis_property("buzz_max_ipi_ms")),
        buzz_min_run_length=int(get_call_analysis_property("buzz_min_run_length")),
        buzz_search_tail_fraction=float(get_call_analysis_property("buzz_search_tail_fraction")),
        expansion_factor=expansion_factor,
    )

    return combined



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



def _compute_amplitude_metrics(
    samples: np.ndarray,
    envelope: np.ndarray,
    sr: int,
    region: PingRegion,
) -> Dict[str, Any]:
    """
    Compute amplitude and envelope-shape metrics for one detected pulse.

    Purpose:
    the waveform envelope carries much of the structural information that matters for
    TE pulse shape: attack length, decay length, overall energy, and how quickly the
    pulse falls away after its peak. These values provide a compact numerical summary
    of the pulse shape for later analysis.
    """
    s = region.start_sample
    e = region.end_sample
    pulse = samples[s:e]
    pulse_env = envelope[s:e]

    if len(pulse) == 0 or len(pulse_env) == 0:
        return {
            "peak_amplitude": None,
            "rms_amplitude": None,
            "attack_ms": None,
            "decay_ms": None,
            "attack_slope": None,
            "decay_slope": None,
            "decay_tau_ms": None,
            "decay_fit_r2": None,
        }

    peak_idx = int(np.argmax(pulse_env))
    peak_amp = float(np.max(np.abs(pulse)))
    rms_amp = float(np.sqrt(np.mean(np.square(pulse))))

    attack_ms = peak_idx * 1000.0 / sr
    decay_ms = max(0.0, (len(pulse_env) - 1 - peak_idx) * 1000.0 / sr)

    attack_slope = None
    if peak_idx > 0:
        attack_slope = float((pulse_env[peak_idx] - pulse_env[0]) / peak_idx)

    decay_slope = None
    if peak_idx < len(pulse_env) - 1:
        denom = len(pulse_env) - 1 - peak_idx
        decay_slope = float((pulse_env[-1] - pulse_env[peak_idx]) / denom)

    decay_tau_ms, decay_fit_r2 = _fit_decay_exponential(pulse_env[peak_idx:], sr)

    return {
        "peak_amplitude": peak_amp,
        "rms_amplitude": rms_amp,
        "attack_ms": attack_ms,
        "decay_ms": decay_ms,
        "attack_slope": attack_slope,
        "decay_slope": decay_slope,
        "decay_tau_ms": decay_tau_ms,
        "decay_fit_r2": decay_fit_r2,
    }



def _fit_decay_exponential(decay_env: np.ndarray, sr: int) -> Tuple[float | None, float | None]:
    """
    Fit a simple exponential decay model to the post-peak envelope tail.

    Purpose:
    many TE pulse tails are well described, at least approximately, by a decaying
    exponential. The fitted time constant gives you a compact measure of how quickly
    the pulse fades, while the R² value tells you how believable that simple model is
    for the pulse in question.
    """
    if len(decay_env) < 8:
        return None, None

    y = np.asarray(decay_env, dtype=np.float64)
    y = y[y > 0]
    if len(y) < 8:
        return None, None

    t = np.arange(len(y), dtype=np.float64) / sr

    # Taking logs turns an exponential decay into a straight line, which lets us use
    # a simple linear fit to estimate the decay constant.
    log_y = np.log(y)
    coeffs = np.polyfit(t, log_y, 1)
    b, a = coeffs[0], coeffs[1]

    if b >= 0:
        return None, None

    fitted = a + b * t
    ss_res = float(np.sum((log_y - fitted) ** 2))
    ss_tot = float(np.sum((log_y - np.mean(log_y)) ** 2))

    r2 = None
    if ss_tot > 0:
        r2 = 1.0 - (ss_res / ss_tot)

    tau_ms = (-1.0 / b) * 1000.0
    return float(tau_ms), r2



def _stft_magnitude(samples: np.ndarray, n_fft: int, hop_length: int) -> np.ndarray:
    """
    Compute a simple magnitude STFT for a short pulse waveform.

    Purpose:
    the spectral metrics only need a lightweight frame-by-frame frequency view, so a
    small internal STFT keeps the analysis self-contained and transparent. The function
    returns magnitudes only because phase is not used anywhere in the current pipeline.
    """
    if len(samples) < n_fft:
        return np.empty((0, 0), dtype=np.float64)

    window = np.hanning(n_fft)
    frames = []

    for start in range(0, len(samples) - n_fft + 1, hop_length):
        frame = samples[start:start + n_fft] * window
        spectrum = np.fft.rfft(frame)
        frames.append(np.abs(spectrum))

    if not frames:
        return np.empty((0, 0), dtype=np.float64)

    return np.stack(frames, axis=1)



def _compute_spectral_metrics(
    samples: np.ndarray,
    sr: int,
    region: PingRegion,
    expansion_factor: float,
) -> Dict[str, Any]:
    """
    Compute coarse spectral summaries for one detected pulse.

    Purpose:
    timing and amplitude describe only part of a bat call. This function adds a simple
    spectral view: dominant frequency, centroid, bandwidth, and a crude start/mid/end
    dominant-frequency trace. For TE recordings, the measured audio-band frequencies
    are also converted back to estimated real bat frequencies by multiplying by the
    time-expansion factor.
    """
    s = region.start_sample
    e = region.end_sample
    pulse = samples[s:e]

    if len(pulse) < 32:
        return _empty_spectral_metrics()

    n_fft = int(get_call_analysis_property("spectral_n_fft"))
    hop_length = int(get_call_analysis_property("spectral_hop_length"))

    # If the pulse is shorter than the configured FFT size, shrink the FFT to the
    # largest practical power of two so short pulses can still yield some metrics.
    if len(pulse) < n_fft:
        n_fft = max(64, 2 ** int(np.floor(np.log2(len(pulse)))))
        if n_fft < 32:
            return _empty_spectral_metrics()

    stft_mag = _stft_magnitude(pulse, n_fft=n_fft, hop_length=hop_length)
    if stft_mag.size == 0:
        return _empty_spectral_metrics()

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    power = stft_mag ** 2

    total_power = float(np.sum(power))
    if total_power <= 0:
        return _empty_spectral_metrics()

    peak_bin = int(np.argmax(np.sum(power, axis=1)))
    peak_freq_audio = float(freqs[peak_bin])

    mean_spectrum = np.sum(power, axis=1)
    centroid_audio = float(np.sum(freqs * mean_spectrum) / np.sum(mean_spectrum))
    bandwidth_audio = float(
        np.sqrt(np.sum(((freqs - centroid_audio) ** 2) * mean_spectrum) / np.sum(mean_spectrum))
    )

    dominant_trace = []
    for frame_idx in range(power.shape[1]):
        frame = power[:, frame_idx]
        if np.sum(frame) <= 0:
            dominant_trace.append(np.nan)
            continue
        dominant_trace.append(float(freqs[int(np.argmax(frame))]))

    dominant_trace = np.asarray(dominant_trace, dtype=np.float64)
    valid = np.isfinite(dominant_trace)

    if np.sum(valid) >= max(3, int(get_call_analysis_property("spectral_min_valid_bins"))):
        valid_trace = dominant_trace[valid]
        start_freq_audio = float(valid_trace[0])
        mid_freq_audio = float(valid_trace[len(valid_trace) // 2])
        end_freq_audio = float(valid_trace[-1])

        x = np.arange(len(valid_trace), dtype=np.float64)
        slope = np.polyfit(x, valid_trace, 1)[0]
        frame_duration_ms = (hop_length / sr) * 1000.0
        slope_audio_hz_per_ms = float(slope / frame_duration_ms)
    else:
        start_freq_audio = None
        mid_freq_audio = None
        end_freq_audio = None
        slope_audio_hz_per_ms = None

    return {
        "peak_frequency_hz_audio": peak_freq_audio,
        "peak_frequency_hz_real": peak_freq_audio * expansion_factor,
        "centroid_hz_audio": centroid_audio,
        "centroid_hz_real": centroid_audio * expansion_factor,
        "bandwidth_hz_audio": bandwidth_audio,
        "bandwidth_hz_real": bandwidth_audio * expansion_factor,
        "dominant_frequency_start_hz_audio": start_freq_audio,
        "dominant_frequency_mid_hz_audio": mid_freq_audio,
        "dominant_frequency_end_hz_audio": end_freq_audio,
        "dominant_frequency_start_hz_real": None if start_freq_audio is None else start_freq_audio * expansion_factor,
        "dominant_frequency_mid_hz_real": None if mid_freq_audio is None else mid_freq_audio * expansion_factor,
        "dominant_frequency_end_hz_real": None if end_freq_audio is None else end_freq_audio * expansion_factor,
        "frequency_slope_hz_per_ms_audio": slope_audio_hz_per_ms,
        "frequency_slope_hz_per_ms_real": None if slope_audio_hz_per_ms is None else slope_audio_hz_per_ms * expansion_factor,
    }



def _empty_spectral_metrics() -> Dict[str, Any]:
    """
    Return a spectral-metrics dictionary populated with null values.

    Purpose:
    some pulses are too short or too weak for a meaningful spectral estimate. Returning
    a complete dictionary of None values keeps the JSON schema stable and easier to
    consume in notebooks or later processing code.
    """
    return {
        "peak_frequency_hz_audio": None,
        "peak_frequency_hz_real": None,
        "centroid_hz_audio": None,
        "centroid_hz_real": None,
        "bandwidth_hz_audio": None,
        "bandwidth_hz_real": None,
        "dominant_frequency_start_hz_audio": None,
        "dominant_frequency_mid_hz_audio": None,
        "dominant_frequency_end_hz_audio": None,
        "dominant_frequency_start_hz_real": None,
        "dominant_frequency_mid_hz_real": None,
        "dominant_frequency_end_hz_real": None,
        "frequency_slope_hz_per_ms_audio": None,
        "frequency_slope_hz_per_ms_real": None,
    }



def _build_pulse_summaries(
    samples: np.ndarray,
    envelope: np.ndarray,
    sr: int,
    regions: List[PingRegion],
    expansion_factor: float,
) -> List[Dict[str, Any]]:
    """
    Build the final pulse-level summary objects written to the JSON output.

    Purpose:
    this is the point where the region detector becomes a dataset generator. It takes
    the final ordered pulse regions and enriches each one with timing, amplitude-shape,
    and spectral metrics, producing a stable per-pulse record that can be analysed in
    notebooks or aggregated across recordings.
    """
    summaries: List[Dict[str, Any]] = []

    ordered = sorted(regions, key=lambda r: r.peak_time_s)

    for i, region in enumerate(ordered):
        prev_region = ordered[i - 1] if i > 0 else None
        next_region = ordered[i + 1] if i < len(ordered) - 1 else None

        time_metrics = _compute_time_metrics(region, prev_region, next_region, expansion_factor)
        amplitude_metrics = _compute_amplitude_metrics(samples, envelope, sr, region)
        spectral_metrics = _compute_spectral_metrics(
            samples=samples,
            sr=sr,
            region=region,
            expansion_factor=expansion_factor,
        )

        summary = {
            "index": i + 1,
            "is_terminal_buzz": region.is_feeding_buzz,
            **time_metrics,
            **amplitude_metrics,
            "spectral": spectral_metrics,
        }
        summaries.append(summary)

    return summaries



def _write_analysis_json(
    input_path: str,
    sample_rate: int,
    duration_s: float,
    expansion_factor: float,
    pulses: List[Dict[str, Any]],
    output_folder: str
) -> Path:
    """
    Write the full analysis result to a JSON sidecar file.

    Purpose:
    the waveform plot is useful for visual checking, but the JSON file is the real data
    product. Writing it as a sidecar next to the source recording makes it easy to keep
    derived measurements tied to the original WAV and easy to batch-process later.
    """
    input_path = Path(input_path)
    output_path = Path(output_folder) / f"{input_path.stem}-analysis.json"
    print(f"Writing call analysis JSON to {output_path}")

    payload = {
        "input": input_path.name,
        "sample_rate": sample_rate,
        "expansion_factor": expansion_factor,
        "duration_s": duration_s,
        "real_time_duration_s": duration_s / expansion_factor,
        "pulse_count": len(pulses),
        "pulses": pulses,
    }

    indent = int(get_call_analysis_property("json_indent"))

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=indent)

    return output_path


def _plot_waveform_with_regions(
    samples: np.ndarray,
    sr: int,
    regions: List[PingRegion],
    input_path: str,
    expansion_factor: float,
    output_folder: str
) -> Path:
    """
    Create a diagnostic waveform plot with detected pulse regions shaded.

    Purpose:
    the plot is a quick visual audit of what the detector did. It lets you see whether
    the earlier hunting pulses, the decays, and the terminal buzz have been captured in
    a way that makes sense before trusting the numeric JSON output.
    """
    times = np.arange(len(samples)) / sr
    input_path = Path(input_path)
    output_path = Path(output_folder) / f"{input_path.stem}-analysis.png"
    print(f"Writing call analysis chart to {output_path}")

    fig, ax = plt.subplots(figsize=(14, 4.8))
    ax.plot(times, samples, linewidth=0.8)

    for region in regions:
        if region.is_feeding_buzz:
            ax.axvspan(region.start_time_s, region.end_time_s, alpha=0.28)
        else:
            ax.axvspan(region.start_time_s, region.end_time_s, alpha=0.18)

    ax.set_title(
        f"Call analysis for {input_path.name} "
        f"(TE x{expansion_factor:g}, real-time {len(samples)/sr/expansion_factor:.3f}s)"
    )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_xlim(0, times[-1] if len(times) else 1.0)
    ax.grid(True, alpha=0.25)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

    return output_path
