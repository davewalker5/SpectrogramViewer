import argparse
import numpy as np
import tomllib
import librosa
import librosa.display
import matplotlib.pyplot as plt
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


PROJECT_FOLDER = Path(__file__).parent.parent.parent
PACKAGE_NAME = "spectrogram"
PROGRAM_NAME = "Spectrogram Viewer"
PROGRAM_DESCRIPTION = "Spectrogram and waveform viewer for audio recordings"


def get_application_version(package_name: str, project_folder: str) -> str:
    """
    Return the application version.

    Priority:
    1. Installed package metadata (works in wheel/container installs)
    2. pyproject.toml fallback (works in local development)
    """

    try:
        return version(package_name)
    except PackageNotFoundError:
        pass

    # Fallback to using pyproject.toml
    file_path = Path(project_folder) / "pyproject.toml"
    if file_path.exists():
        with file_path.resolve().open("rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]

    return "0+unknown"


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments
    """
    version = get_application_version(PACKAGE_NAME, PROJECT_FOLDER)
    parser = argparse.ArgumentParser(
        prog=f"{PROGRAM_NAME} v{version}",
        description=PROGRAM_DESCRIPTION
    )

    # Parse the command line arguments
    parser.add_argument("-f", "--file", help="Input audio file path")
    parser.add_argument("-t", "--title", help="Chart title")
    parser.add_argument("-w", "--window-size", type=int, default=2048, help="STFT window size")
    parser.add_argument("-hl", "--hop-length", type=int, default=256, help="STFT hop length")
    return parser.parse_args()


def show_spectrogram(file_path: str, title: str, n_fft: int, hop_length: int) -> None:
    """
    Chart the waveform and spectrogram derived from that waveform
    """

    # Load the waveform and determine the sample rate. The result is a 1D array of
    # amplitude values over time and the number of samples per second. Time is implied
    # by index position in the array divided by sample rate
    y, sr = librosa.load(file_path, sr=None)

    # Compute Short-Time Fourier Transform: break audio into overlapping time windows and
    # extract frequency content for each moment. If the input audio has a sample rate of
    # 11025, then n_fft = 2048 splits the audio into 2048/11025 s frames i.e. ~0.186 s.
    # As a general rule:
    #
    # Higher n_fft gives better frequency resolution, worse time resolution
    # Lower n_fft gives better time resolution, worse frequency resolution
    #
    # Hop length controls spacing between frames and a 256 the hop is 256/11025 s i.e. ~23 ms
    # This is, effectively, the sampling frequency for producing the spectrogram
    D = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, window="hann")

    # This converts the results of the transform from amplitude to decibels (log scale).
    # This yields a 2D array of [frequency × time] in decibels with each point in that array
    # answering the question "How string is this frequency at this moment in time?"
    S = librosa.amplitude_to_db(np.abs(D), ref=np.max)

    # Create the figure
    fig = plt.figure(figsize=(12, 6))
    fig.suptitle(title, fontsize=14, y=0.93)
    gs = fig.add_gridspec(
        2, 2,
        width_ratios=[20, 1],
        height_ratios=[1, 3],
        hspace=0.01,
        wspace=0.15
    )

    # Add the charts for the waveform and spectrogram
    ax_wave = fig.add_subplot(gs[0, 0])
    ax_spec = fig.add_subplot(gs[1, 0], sharex=ax_wave)
    cax = fig.add_subplot(gs[1, 1])
    fig.add_subplot(gs[0, 1]).axis("off")

    # Chart the waveform
    librosa.display.waveshow(y, sr=sr, ax=ax_wave)

    # Chart the spectrogram
    img = librosa.display.specshow(
        S,
        sr=sr,
        hop_length=hop_length,
        x_axis="time",
        y_axis="hz",
        cmap="magma",
        vmin=-95,
        vmax=-35,
        ax=ax_spec
    )

    # Force both panels to the real duration
    duration = len(y) / sr
    ax_wave.set_xlim(0, duration)
    ax_spec.set_xlim(0, duration)
    ax_wave.margins(x=0)
    ax_spec.margins(x=0)

    # Add the colour bar
    fig.colorbar(img, cax=cax, format="%+2.0f dB")

    # Set labels
    ax_spec.set_xlabel("Time")
    ax_spec.set_ylabel("Hz")
    ax_wave.tick_params(axis='x', which='both', bottom=False, top=False, labelbottom=False)
    plt.show()


def main():
    args = parse_args()
    try:
        show_spectrogram(args.file, args.title, args.window_size, args.hop_length)
    except KeyboardInterrupt:
        pass
