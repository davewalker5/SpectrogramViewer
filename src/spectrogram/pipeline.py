# --------------------------------------------------------------------------------
# Audio processing pipeline for bat recordings
#
# This module implements a simple, repeatable workflow for turning raw
# time-expansion recordings into cleaner, more interpretable audio.
#
# The focus is on transparency and consistency rather than studio-grade DSP.
# --------------------------------------------------------------------------------
from __future__ import annotations
import librosa
import numpy as np
import soundfile as sf
import scipy.signal as signal
from pathlib import Path
from typing import List, Tuple
from spectrogram.config_reader import get_spectral_noise_reduction_property, \
    get_high_pass_filter_property, get_normalisation_property

# Noise-region detection is handled separately
from spectrogram.noise_detection import find_noise_regions


def extract_noise_audio(y: np.ndarray, noise_regions: List[Tuple[int, int]]) -> np.ndarray:
    """
    Concatenate all detected noise regions into a single 1D noise sample.

    This mirrors the manual workflow in tools like Audacity, where a user
    selects several quiet sections and builds a combined "noise profile".

    Args:
        y: Full waveform.
        noise_regions: List of (start, end) sample indices identified as noise.

    Returns:
        A single array containing all noise segments stitched together.
        Returns an empty array if no usable regions are found.
    """
    if not noise_regions:
        return np.array([], dtype=y.dtype)

    # Extract each region and concatenate into one continuous sample
    chunks = [y[start:end] for start, end in noise_regions if end > start]
    if not chunks:
        return np.array([], dtype=y.dtype)

    return np.concatenate(chunks)


def spectral_noise_reduce(y: np.ndarray, noise_audio: np.ndarray) -> np.ndarray:
    """
    Apply simple spectral subtraction / floor-gating noise reduction.

    Conceptually:
    - Transform audio into time-frequency space (STFT)
    - Estimate the average noise spectrum from noise-only audio
    - Subtract that noise profile from every frame
    - Prevent over-subtraction by enforcing a small "floor"
    - Reconstruct the signal using the original phase

    Why this approach:
    - Easy to understand and debug
    - Works well for steady hiss / broadband noise
    - Avoids heavy "black box" processing

    Args:
        y: Input waveform.
        noise_audio: Concatenated noise-only sample.

    Returns:
        Noise-reduced waveform.
    """

    # Load configuration properties
    n_fft = get_spectral_noise_reduction_property("n_fft")
    hop_length = get_spectral_noise_reduction_property("hop_length")
    reduction_strength = get_spectral_noise_reduction_property("reduction_strength")
    floor_fraction = get_spectral_noise_reduction_property("floor_fraction")

    if len(noise_audio) < n_fft:
        # Not enough noise to estimate a reliable profile
        return y.copy()

    # STFT of full signal
    D = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, window="hann")
    magnitude = np.abs(D)
    phase = np.angle(D)

    # STFT of noise-only sample
    D_noise = librosa.stft(noise_audio, n_fft=n_fft, hop_length=hop_length, window="hann")
    noise_magnitude = np.abs(D_noise)

    # Average noise profile (per frequency bin)
    noise_profile = np.mean(noise_magnitude, axis=1, keepdims=True)

    # Subtract noise profile from every frame
    reduced_magnitude = magnitude - (reduction_strength * noise_profile)

    # Prevent "holes" by enforcing a minimum floor
    floor = floor_fraction * magnitude
    reduced_magnitude = np.maximum(reduced_magnitude, floor)

    # Recombine magnitude with original phase
    D_reduced = reduced_magnitude * np.exp(1j * phase)

    # Convert back to time domain
    y_reduced = librosa.istft(
        D_reduced,
        hop_length=hop_length,
        window="hann",
        length=len(y),
    )

    return y_reduced


def high_pass_filter(y: np.ndarray, sr: int) -> np.ndarray:
    """
    Apply a Butterworth high-pass filter.

    Purpose:
    - Remove low-frequency rumble and handling noise
    - Focus the signal on the frequency range where bat calls occur
      (after time expansion)

    A zero-phase filter (filtfilt) is used to avoid introducing phase distortion.

    Args:
        y: Input waveform.
        sr: Sample rate.

    Returns:
        Filtered waveform.
    """
    order = get_high_pass_filter_property("order")
    cutoff_hz = get_high_pass_filter_property("cutoff_hz")
    b, a = signal.butter(order, cutoff_hz, btype="highpass", fs=sr)
    return signal.filtfilt(b, a, y)


def normalize_audio(y: np.ndarray) -> np.ndarray:
    """
    Normalize audio to a target peak level.

    Purpose:
    - Make quiet recordings easier to inspect and listen to
    - Preserve relative dynamics (this is peak normalization, not compression)

    Args:
        y: Input waveform.

    Returns:
        Scaled waveform.
    """
    peak = float(np.max(np.abs(y)))
    if peak <= 0:
        return y.copy()

    peak_target = get_normalisation_property("peak_target")
    return peak_target * (y / peak)


def process_audio_file(input_file: str | Path, output_file: str | Path) -> dict:
    """
    End-to-end processing pipeline for a single audio file.

    Pipeline overview:
    1. Load audio
    2. Detect likely noise-only regions
    3. Build a noise profile from those regions
    4. Apply spectral noise reduction
    5. Apply high-pass filtering
    6. Normalize signal
    7. Save processed audio

    Design goals:
    - Replace manual Audacity workflow with a repeatable process
    - Preserve structure and timing of bat calls
    - Improve clarity without over-processing

    Returns:
        A small diagnostics dictionary summarizing the run.
    """
    input_file = Path(input_file)
    output_file = Path(output_file)

    # Load audio at original sample rate (no resampling)
    y, sr = librosa.load(str(input_file), sr=None, mono=True)

    # Step 1: Identify likely noise-only regions
    noise_regions = find_noise_regions(y, sr)

    # Step 2: Build a noise sample from those regions
    noise_audio = extract_noise_audio(y, noise_regions)

    # Step 3: Reduce noise using spectral subtraction
    y_processed = spectral_noise_reduce(y, noise_audio)

    # Step 4: Remove low-frequency rumble
    y_processed = high_pass_filter(y_processed, sr)

    # Step 5: Normalize for consistent output level
    y_processed = normalize_audio(y_processed)

    # Step 6: Save processed audio
    sf.write(str(output_file), y_processed, sr)

    # Diagnostics (useful for logging / inspection)
    total_noise_samples = sum(end - start for start, end in noise_regions)
    total_noise_seconds = total_noise_samples / sr if sr > 0 else 0.0

    return {
        "input_file": str(input_file),
        "output_file": str(output_file),
        "sample_rate": sr,
        "duration_seconds": len(y) / sr,
        "noise_region_count": len(noise_regions),
        "noise_seconds": total_noise_seconds,
    }