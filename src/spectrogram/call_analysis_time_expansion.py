from __future__ import annotations

from pathlib import Path
import json
from typing import List, Tuple, Dict, Any

import matplotlib.pyplot as plt
import numpy as np

from spectrogram.config_reader import get_call_analysis_property
from spectrogram.pulse_core import (
    PingRegion,
    _load_audio_mono,
    _build_envelope,
    _detect_active_regions,
    _mask_to_regions,
    _refine_regions,
    _compute_time_metrics,
    _merge_overlaps
)


def analyse_time_expansion_file(input: str, expansion_factor: float, output_folder: str):
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


def _mark_feeding_buzz(
    regions: List[PingRegion],
    buzz_max_ipi_ms: float,
    buzz_min_run_length: int,
    buzz_search_tail_fraction: float,
    expansion_factor: float,
) -> List[PingRegion]:
    """
    Identify terminal feeding-buzz runs in one or more pulse sequences.

    Purpose:
    a single recording may contain more than one pass. Earlier versions only looked
    for the single best buzz run in the final tail of the whole recording, which meant
    duplicated or multi-pass recordings could only ever end up with the last buzz
    labelled. This version first breaks the pulse train into coarse sequence groups
    using large IPI gaps, then looks for a late-stage dense run inside each group.

    Behaviour:
    - the configured buzz IPI threshold is interpreted in real bat time and converted
      into slowed TE time before comparison
    - one over-threshold gap is allowed inside an otherwise buzz-like run
    - every qualifying late-stage run is marked, not just the final one in the file
    """
    if len(regions) < buzz_min_run_length:
        return regions

    regions = sorted(regions, key=lambda r: r.peak_time_s)

    # Peak times are measured on the slowed TE waveform, so convert the configured
    # real-time buzz threshold into expanded-time seconds before comparing IPIs.
    buzz_max_ipi_s = (buzz_max_ipi_ms / 1000.0) * expansion_factor
    allowed_gap_breaks = 1

    # Use a generous multiple of the buzz threshold to split the full pulse train into
    # coarse groups. This is not formal pass segmentation; it is just enough to stop
    # separate sequences in one file from competing for a single buzz label.
    # grouping_gap_s = buzz_max_ipi_s * 3.0
    grouping_gap_s = buzz_max_ipi_s * 7.0

    grouped_indices: List[List[int]] = []
    current_group: List[int] = [0]

    for idx in range(1, len(regions)):
        ipi = regions[idx].peak_time_s - regions[idx - 1].peak_time_s
        if ipi > grouping_gap_s:
            grouped_indices.append(current_group)
            current_group = [idx]
        else:
            current_group.append(idx)

    if current_group:
        grouped_indices.append(current_group)

    def _find_best_run(indices: List[int]) -> List[int]:
        """Find the best buzz-like run within one late-stage group of pulses."""
        if len(indices) < buzz_min_run_length:
            return []

        group_start_time = regions[indices[0]].peak_time_s
        group_end_time = regions[indices[-1]].peak_time_s
        group_duration = group_end_time - group_start_time

        if group_duration <= 0:
            tail_indices = indices[:]
        else:
            tail_start_time = group_end_time - (group_duration * buzz_search_tail_fraction)
            tail_indices = [i for i in indices if regions[i].peak_time_s >= tail_start_time]
            if len(tail_indices) < buzz_min_run_length:
                tail_indices = indices[:]

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

            # Allow one slightly long interval inside an otherwise dense run.
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

        if len(best_run) < buzz_min_run_length:
            return []

        short_ipi_count = 0
        for i in range(1, len(best_run)):
            prev_idx = best_run[i - 1]
            curr_idx = best_run[i]
            ipi = regions[curr_idx].peak_time_s - regions[prev_idx].peak_time_s
            if ipi <= buzz_max_ipi_s:
                short_ipi_count += 1

        if short_ipi_count < max(1, buzz_min_run_length - 1):
            return []

        return best_run

    for group in grouped_indices:
        best_run = _find_best_run(group)
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
    Recover narrow missed buzz pulses with a second-pass detector in already-labelled
    buzz regions only.

    Purpose:
    the main detector is tuned to preserve broader hunting pulses and their decays, so
    it can miss very short pulses inside a terminal buzz. Earlier versions searched
    from the first buzz pulse to the end of the recording, which worked for single-pass
    files but caused later passes in duplicated or multi-pass recordings to be swept
    up into the same recovery window. This version groups existing buzz labels into
    separate late-stage clusters and runs recovery independently inside each one.

    The minimum spacing between recovered peaks is configured in real bat time, so it
    is converted back into expanded-time samples before peak picking on the slowed TE
    waveform.
    """
    if not regions:
        return regions

    ordered = sorted(regions, key=lambda r: r.peak_time_s)
    buzz_regions = [r for r in ordered if r.is_feeding_buzz]
    if not buzz_regions:
        return regions

    min_peak_distance = max(
        1, int(round(sr * (min_peak_distance_ms / 1000.0) * expansion_factor))
    )
    half_region = max(
        1, int(round(sr * (region_ms / 1000.0) * expansion_factor / 2.0))
    )

    buzz_max_ipi_s = (
        float(get_call_analysis_property("buzz_max_ipi_ms")) / 1000.0
    ) * expansion_factor
    grouping_gap_s = buzz_max_ipi_s * 7.0

    # Split existing buzz labels into separate clusters so each pass is recovered
    # independently rather than treating the rest of the file as one giant buzz tail.
    buzz_groups: List[List[PingRegion]] = []
    current_group: List[PingRegion] = [buzz_regions[0]]

    for region in buzz_regions[1:]:
        ipi = region.peak_time_s - current_group[-1].peak_time_s
        if ipi > grouping_gap_s:
            buzz_groups.append(current_group)
            current_group = [region]
        else:
            current_group.append(region)

    if current_group:
        buzz_groups.append(current_group)

    recovered: List[PingRegion] = []

    for group in buzz_groups:
        group_start = max(0, min(r.start_sample for r in group) - half_region)
        group_end = min(len(samples), max(r.end_sample for r in group) + half_region)

        search_env = envelope[group_start:group_end]
        if len(search_env) == 0:
            continue

        local_peak = float(np.max(search_env))
        if local_peak <= 0:
            continue

        threshold = local_peak * recovery_threshold_fraction
        candidate_peaks: List[int] = []
        last_peak = group_start - min_peak_distance

        for i in range(1, len(search_env) - 1):
            if search_env[i] < threshold:
                continue

            is_peak = search_env[i] >= search_env[i - 1] and search_env[i] > search_env[i + 1]
            if not is_peak:
                continue

            abs_i = group_start + i
            if abs_i - last_peak >= min_peak_distance:
                candidate_peaks.append(abs_i)
                last_peak = abs_i

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

    if not recovered:
        return regions

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
        "analysis_mode": "time-expansion",
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
            ax.axvspan(
                region.start_time_s,
                region.end_time_s,
                color="#f6c28b",
                alpha=0.45,
            )
        else:
            ax.axvspan(
                region.start_time_s,
                region.end_time_s,
                color="#b7d4ea",
                alpha=0.30,
            )

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
