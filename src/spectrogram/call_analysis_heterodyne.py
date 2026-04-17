from __future__ import annotations

from pathlib import Path
import json
from typing import List, Dict, Any

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
)


def analyse_heterodyne_file(input: str, output_folder: str):
    """
    Run a heterodyne pulse-structure analysis pipeline for one WAV file.

    Purpose:
    heterodyne recordings do not preserve the original ultrasonic frequency content in
    a form that supports the TE spectral measurements, but they can still support useful
    timing analysis. This pipeline therefore focuses on pulse detection, sequence
    grouping, inter-pulse timing, and conservative identification of dense terminal runs.

    Parameters
    ----------
    input:
        Path to the WAV file.
    output_folder:
        Folder where output files are written.

    Returns
    -------
    dict
        Summary including detected regions, grouped sequences, output plot path, JSON
        path, and the pulse- and sequence-level summaries written to disk.
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

    sequence_groups = _group_regions_into_sequences(
        regions=refined_regions,
        grouping_gap_ms=float(get_call_analysis_property("sequence_gap_ms")),
    )

    refined_regions = _mark_terminal_dense_runs(
        regions=refined_regions,
        sequence_groups=sequence_groups,
        dense_ipi_ms=float(get_call_analysis_property("dense_ipi_ms")),
        min_run_length=int(get_call_analysis_property("dense_min_run_length")),
        search_tail_fraction=float(get_call_analysis_property("dense_search_tail_fraction")),
    )

    pulse_summaries = _build_pulse_summaries(
        samples=samples,
        envelope=envelope,
        sr=sr,
        regions=refined_regions,
        sequence_groups=sequence_groups,
    )

    sequence_summaries = _build_sequence_summaries(
        regions=refined_regions,
        sequence_groups=sequence_groups,
    )

    plot_path = _plot_waveform_with_regions(
        samples=samples,
        sr=sr,
        regions=refined_regions,
        input_path=input,
        output_folder=output_folder,
    )

    json_path = _write_analysis_json(
        input_path=input,
        sample_rate=sr,
        duration_s=duration_s,
        pulses=pulse_summaries,
        sequences=sequence_summaries,
        output_folder=output_folder,
    )

    return {
        "input": str(input),
        "sample_rate": sr,
        "duration_s": duration_s,
        "analysis_mode": "heterodyne",
        "region_count": len(refined_regions),
        "sequence_count": len(sequence_groups),
        "plot_path": str(plot_path),
        "json_path": str(json_path),
        "pulses": pulse_summaries,
        "sequences": sequence_summaries,
    }


def _group_regions_into_sequences(
    regions: List[PingRegion],
    grouping_gap_ms: float,
) -> List[List[int]]:
    """
    Split detected pulse regions into coarse sequences using large peak-to-peak gaps.

    Purpose:
    a single heterodyne file may contain more than one pass or bout of activity. This
    function groups nearby pulses into coarse sequences so downstream summaries can work
    at both pulse and pass level.
    """
    if not regions:
        return []

    ordered = sorted(enumerate(regions), key=lambda x: x[1].peak_time_s)
    grouping_gap_s = grouping_gap_ms / 1000.0

    groups: List[List[int]] = []
    current_group: List[int] = [ordered[0][0]]

    for pos in range(1, len(ordered)):
        prev_idx, prev_region = ordered[pos - 1]
        curr_idx, curr_region = ordered[pos]

        ipi_s = curr_region.peak_time_s - prev_region.peak_time_s
        if ipi_s > grouping_gap_s:
            groups.append(current_group)
            current_group = [curr_idx]
        else:
            current_group.append(curr_idx)

    if current_group:
        groups.append(current_group)

    return groups


def _mark_terminal_dense_runs(
    regions: List[PingRegion],
    sequence_groups: List[List[int]],
    dense_ipi_ms: float,
    min_run_length: int,
    search_tail_fraction: float,
) -> List[PingRegion]:
    """
    Mark dense late-stage pulse runs inside each sequence.

    Purpose:
    in heterodyne recordings we can still look for terminal timing compression, but
    should be more cautious than with TE recordings. This function therefore marks
    candidate dense terminal runs without making a stronger frequency-based claim.

    Note:
    the PingRegion field is still called 'is_feeding_buzz' for compatibility with the
    existing data model, but in the heterodyne module it should be interpreted as a
    conservative 'terminal dense run candidate' label.
    """
    if not regions:
        return regions

    dense_ipi_s = dense_ipi_ms / 1000.0

    for group in sequence_groups:
        if len(group) < min_run_length:
            continue

        ordered = sorted(group, key=lambda i: regions[i].peak_time_s)

        start_t = regions[ordered[0]].peak_time_s
        end_t = regions[ordered[-1]].peak_time_s
        duration = end_t - start_t

        if duration > 0:
            tail_start = end_t - (duration * search_tail_fraction)
            candidates = [i for i in ordered if regions[i].peak_time_s >= tail_start]
            if len(candidates) < min_run_length:
                candidates = ordered[:]
        else:
            candidates = ordered[:]

        best_run: List[int] = []
        current_run: List[int] = []

        for pos, idx in enumerate(candidates):
            if pos == 0:
                current_run = [idx]
                continue

            prev_idx = candidates[pos - 1]
            ipi_s = regions[idx].peak_time_s - regions[prev_idx].peak_time_s

            if ipi_s <= dense_ipi_s:
                current_run.append(idx)
            else:
                if len(current_run) > len(best_run):
                    best_run = current_run[:]
                current_run = [idx]

        if len(current_run) > len(best_run):
            best_run = current_run[:]

        if len(best_run) >= min_run_length:
            for idx in best_run:
                regions[idx].is_feeding_buzz = True

    return regions


def _compute_heterodyne_shape_metrics(
    samples: np.ndarray,
    envelope: np.ndarray,
    sr: int,
    region: PingRegion,
) -> Dict[str, Any]:
    """
    Compute simple detector-output shape metrics for one pulse.

    Purpose:
    these are retained as descriptive measurements of the detector output waveform, not
    as direct estimates of the original ultrasonic call structure. They can still be
    useful for within-pipeline comparisons when interpreted cautiously.
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
        }

    peak_idx = int(np.argmax(pulse_env))
    peak_amp = float(np.max(np.abs(pulse)))
    rms_amp = float(np.sqrt(np.mean(np.square(pulse))))

    attack_ms = peak_idx * 1000.0 / sr
    decay_ms = max(0.0, (len(pulse_env) - 1 - peak_idx) * 1000.0 / sr)

    return {
        "peak_amplitude": peak_amp,
        "rms_amplitude": rms_amp,
        "attack_ms": attack_ms,
        "decay_ms": decay_ms,
    }


def _compute_local_ipi_metrics(
    ordered_regions: List[PingRegion],
    pos: int,
) -> Dict[str, Any]:
    """
    Compute small-window local IPI context for one pulse in the time-ordered list.
    """
    peak_times = [r.peak_time_s for r in ordered_regions]
    local_ipis_ms: List[float] = []

    for i in range(max(1, pos - 2), min(len(peak_times), pos + 3)):
        ipi_ms = (peak_times[i] - peak_times[i - 1]) * 1000.0
        local_ipis_ms.append(float(ipi_ms))

    if not local_ipis_ms:
        return {
            "local_ipi_median_ms": None,
            "local_ipi_min_ms": None,
        }

    return {
        "local_ipi_median_ms": float(np.median(local_ipis_ms)),
        "local_ipi_min_ms": float(np.min(local_ipis_ms)),
    }


def _build_pulse_summaries(
    samples: np.ndarray,
    envelope: np.ndarray,
    sr: int,
    regions: List[PingRegion],
    sequence_groups: List[List[int]],
) -> List[Dict[str, Any]]:
    """
    Build pulse-level summary dictionaries for heterodyne analysis output.
    """
    ordered = sorted(enumerate(regions), key=lambda x: x[1].peak_time_s)

    seq_lookup: Dict[int, tuple[int, int]] = {}
    for seq_id, group in enumerate(sequence_groups, start=1):
        ordered_group = sorted(group, key=lambda i: regions[i].peak_time_s)
        for pulse_in_sequence, idx in enumerate(ordered_group, start=1):
            seq_lookup[idx] = (seq_id, pulse_in_sequence)

    ordered_regions_only = [region for _, region in ordered]
    summaries: List[Dict[str, Any]] = []

    for pos, (idx, region) in enumerate(ordered):
        prev_region = ordered[pos - 1][1] if pos > 0 else None
        next_region = ordered[pos + 1][1] if pos < len(ordered) - 1 else None

        time_metrics = _compute_time_metrics(
            region=region,
            prev_region=prev_region,
            next_region=next_region,
            expansion_factor=1.0,
        )

        shape_metrics = _compute_heterodyne_shape_metrics(
            samples=samples,
            envelope=envelope,
            sr=sr,
            region=region,
        )

        local_ipi_metrics = _compute_local_ipi_metrics(
            ordered_regions=ordered_regions_only,
            pos=pos,
        )

        sequence_id, pulse_in_sequence = seq_lookup.get(idx, (None, None))

        summary = {
            "index": pos + 1,
            "sequence_id": sequence_id,
            "pulse_in_sequence": pulse_in_sequence,
            "is_terminal_dense_run": bool(region.is_feeding_buzz),
            **time_metrics,
            **local_ipi_metrics,
            **shape_metrics,
        }

        summaries.append(summary)

    return summaries


def _build_sequence_summaries(
    regions: List[PingRegion],
    sequence_groups: List[List[int]],
) -> List[Dict[str, Any]]:
    """
    Build pass/sequence-level summaries for heterodyne analysis output.
    """
    summaries: List[Dict[str, Any]] = []

    for seq_id, group in enumerate(sequence_groups, start=1):
        ordered = sorted(group, key=lambda i: regions[i].peak_time_s)
        seq_regions = [regions[i] for i in ordered]

        peak_times = [r.peak_time_s for r in seq_regions]
        ipis_ms = [
            (peak_times[i] - peak_times[i - 1]) * 1000.0
            for i in range(1, len(peak_times))
        ]

        terminal_dense_count = sum(1 for r in seq_regions if r.is_feeding_buzz)

        summaries.append(
            {
                "sequence_id": seq_id,
                "start_time_s": seq_regions[0].start_time_s,
                "end_time_s": seq_regions[-1].end_time_s,
                "pulse_count": len(seq_regions),
                "duration_s": seq_regions[-1].end_time_s - seq_regions[0].start_time_s,
                "mean_ipi_ms": None if not ipis_ms else float(np.mean(ipis_ms)),
                "median_ipi_ms": None if not ipis_ms else float(np.median(ipis_ms)),
                "min_ipi_ms": None if not ipis_ms else float(np.min(ipis_ms)),
                "has_terminal_dense_run": terminal_dense_count > 0,
                "terminal_dense_pulse_count": terminal_dense_count,
            }
        )

    return summaries


def _plot_waveform_with_regions(
    samples: np.ndarray,
    sr: int,
    regions: List[PingRegion],
    input_path: str,
    output_folder: str,
) -> Path:
    """
    Write a simple diagnostic waveform plot with detected pulse regions shaded.

    Enhancement:
    terminal dense runs are highlighted with an orange background so they can be
    visually inspected.
    """
    t = np.arange(len(samples)) / sr
    output_dir = Path(output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{Path(input_path).stem}_analysis.png"
    print(f"Writing call analysis chart to {out_path}")

    plt.figure(figsize=(14, 4))
    plt.plot(t, samples, linewidth=0.8)

    for region in regions:
        if region.is_feeding_buzz:
            plt.axvspan(
                region.start_time_s,
                region.end_time_s,
                color="#f6c28b",
                alpha=0.45,
            )
        else:
            plt.axvspan(
                region.start_time_s,
                region.end_time_s,
                color="#b7d4ea",
                alpha=0.30,
            )

    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")
    plt.title(
        f"Call analysis for {Path(input_path).name} "
        f"(heterodyne, real-time {len(samples) / sr:.3f}s)"
    )
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()

    return out_path


def _write_analysis_json(
    input_path: str,
    sample_rate: int,
    duration_s: float,
    pulses: List[Dict[str, Any]],
    sequences: List[Dict[str, Any]],
    output_folder: str,
) -> Path:
    """
    Write heterodyne pulse-structure analysis results to JSON.
    """
    output_dir = Path(output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{Path(input_path).stem}_analysis.json"
    print(f"Writing call analysis JSON to {out_path}")

    payload = {
        "input_file": str(input_path),
        "analysis_mode": "heterodyne",
        "sample_rate": sample_rate,
        "duration_s": duration_s,
        "pulse_count": len(pulses),
        "sequence_count": len(sequences),
        "pulses": pulses,
        "sequences": sequences,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return out_path
