import numpy as np
import librosa
import matplotlib.pyplot as plt
from typing import List, Tuple
from pathlib import Path
from spectrogram.config_reader import get_noise_detection_property


def _window_rms(window: np.ndarray) -> float:
    """
    Return the root-mean-square (RMS) amplitude for a single window of audio.

    RMS is used here as a simple measure of overall loudness. For noise detection,
    quieter windows are more likely to contain background noise only, while louder
    windows are more likely to contain bat calls or other transient signal.

    Args:
        window: One short slice of the waveform.

    Returns:
        RMS amplitude as a float.
    """
    return float(np.sqrt(np.mean(window**2)))


def _window_band_ratio(
    window: np.ndarray,
    sr: int,
    band_low_hz: float,
    band_high_hz: float,
) -> float:
    """
    Return the fraction of spectral energy that lies in the target frequency band.

    This is used as a simple "is there likely bat signal here?" test.

    The window is tapered with a Hann window before taking the FFT to reduce
    edge artefacts and spectral leakage. A real FFT is then used to estimate
    the power spectrum of the window.

    The result is the ratio:

        energy inside target band / total spectral energy

    Interpretation:
    - Low ratio:
        likely broadband hiss / background / non-bat noise
    - High ratio:
        likely structured signal concentrated in the expected bat-call band

    Args:
        window: One short slice of the waveform.
        sr: Sample rate of the recording in Hz.
        band_low_hz: Lower bound of the expected signal band.
        band_high_hz: Upper bound of the expected signal band.

    Returns:
        Fraction of total spectral energy contained in the target band.
        Returns 0.0 for empty or silent windows.
    """
    if len(window) == 0:
        return 0.0

    # Apply a Hann taper before the FFT so the window edges do not introduce
    # unnecessary spectral artefacts.
    tapered = window * np.hanning(len(window))

    # Real FFT is sufficient here because the input is a real-valued waveform.
    spectrum = np.fft.rfft(tapered)

    # Convert complex FFT output to power spectrum.
    power = np.abs(spectrum) ** 2

    # Frequency axis corresponding to the FFT bins.
    freqs = np.fft.rfftfreq(len(window), d=1.0 / sr)

    total_energy = np.sum(power)
    if total_energy <= 0:
        return 0.0

    # Select FFT bins that fall within the expected signal band.
    band_mask = (freqs >= band_low_hz) & (freqs <= band_high_hz)
    band_energy = np.sum(power[band_mask])

    return float(band_energy / total_energy)


def find_noise_regions(y: np.ndarray, sr: int) -> List[Tuple[int, int]]:
    """
    Find likely noise-only regions using both loudness and spectral content.

    This is a heuristic detector intended to replace the manual "pick a quiet
    section" step often used in audio tools such as Audacity.

    Approach:
    1. Split the recording into short overlapping windows.
    2. For each window, measure:
       - RMS amplitude (overall loudness)
       - Fraction of spectral energy in the expected bat-call band
    3. Mark a window as a candidate noise window if it is:
       - relatively quiet compared with the rest of the recording, and
       - relatively low in target-band energy
    4. Merge neighbouring candidate windows into longer continuous regions.
    5. Discard very short fragments, keeping only regions large enough to be
       useful as a noise sample.

    The thresholds are percentile-based rather than absolute, so the detector
    adapts to the recording it is given. In other words, it looks for the
    quieter / less bat-like parts of this recording, not for a fixed amplitude
    or energy threshold.

    Args:
        y: Input waveform.
        sr: Sample rate in Hz

    Returns:
        A list of (start_sample, end_sample) tuples identifying regions that
        are likely to contain background noise rather than bat signal.

    Notes:
        - This is a heuristic, not a guarantee of pure noise.
        - It works best when the recording contains at least some genuine gaps
          between calls.
        - On very dense or very noisy recordings, it may return the "least
          signal-like" regions rather than truly signal-free ones.
    """

    # Load configuration properties
    window_ms = get_noise_detection_property("window_ms")
    hop_ms = get_noise_detection_property("hop_ms")
    rms_percentile = get_noise_detection_property("rms_percentile")
    band_ratio_percentile = get_noise_detection_property("band_ratio_percentile")
    min_region_ms = get_noise_detection_property("min_region_ms")
    band_low_hz = get_noise_detection_property("band_low_hz")
    band_high_hz = get_noise_detection_property("band_high_hz")

    # Convert window, hop, and minimum region length from milliseconds to samples.
    window_length = max(1, int(sr * window_ms / 1000.0))
    hop_length = max(1, int(sr * hop_ms / 1000.0))
    min_region_samples = int(sr * min_region_ms / 1000.0)

    if len(y) < window_length:
        return []

    starts = []
    rms_values = []
    band_ratios = []

    # Slide a short analysis window across the recording and measure, for each
    # position, both overall loudness and how much energy sits in the target band.
    for start in range(0, len(y) - window_length + 1, hop_length):
        window = y[start:start + window_length]

        starts.append(start)
        rms_values.append(_window_rms(window))
        band_ratios.append(
            _window_band_ratio(
                window,
                sr=sr,
                band_low_hz=band_low_hz,
                band_high_hz=band_high_hz,
            )
        )

    starts = np.array(starts)
    rms_values = np.array(rms_values)
    band_ratios = np.array(band_ratios)

    # Use percentile thresholds so the decision is relative to this recording.
    # A candidate noise window must be both:
    # - quieter than much of the recording
    # - lower in target-band energy than much of the recording
    rms_threshold = np.percentile(rms_values, rms_percentile)
    band_ratio_threshold = np.percentile(band_ratios, band_ratio_percentile)

    is_noise_window = (rms_values <= rms_threshold) & (band_ratios <= band_ratio_threshold)

    regions: List[Tuple[int, int]] = []
    region_start = None
    region_end = None

    # Merge adjacent candidate windows into longer continuous regions.
    for i, flag in enumerate(is_noise_window):
        start = int(starts[i])
        end = start + window_length

        if flag:
            if region_start is None:
                region_start = start
            region_end = end
        else:
            if region_start is not None and region_end is not None:
                # Keep only regions long enough to be useful as a noise sample.
                if region_end - region_start >= min_region_samples:
                    regions.append((region_start, region_end))
                region_start = None
                region_end = None

    # Finalise a region if the recording ends while still inside one.
    if region_start is not None and region_end is not None:
        if region_end - region_start >= min_region_samples:
            regions.append((region_start, region_end))

    return regions


def plot_waveform_with_noise_regions(
    y: np.ndarray,
    sr: int,
    noise_regions: List[Tuple[int, int]],
    title: str
) -> None:
    """
    Plot waveform and shade detected noise regions.
    """

    t = np.arange(len(y)) / sr

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(t, y, linewidth=0.8)

    for start, end in noise_regions:
        ax.axvspan(start / sr, end / sr, alpha=0.25)

    ax.set_title(title)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.margins(x=0)
    plt.tight_layout()
    plt.show()


def inspect_noise_detection(file_path: str, title: str) -> List[Tuple[int, int]]:
    """
    Load an audio file, detect likely noise-only regions, plot them, and return them.
    """
    y, sr = librosa.load(file_path, sr=None, mono=True)

    noise_regions = find_noise_regions(y=y, sr=sr)

    # Set a default title if one isn't set
    if not title:
        title = f"Detected Noise Regions for {Path(file_path).name.upper()}"

    plot_waveform_with_noise_regions(y, sr, noise_regions, title=title)

    return noise_regions