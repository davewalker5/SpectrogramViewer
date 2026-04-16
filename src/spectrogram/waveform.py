import numpy as np
import matplotlib.pyplot as plt
import librosa
from pathlib import Path


def show_waveform(file_path: str, title: str, output_path: str) -> None:
    """
    Plot the waveform loaded from a WAV file
    """

    # Set a default title if one isn't set
    if not title:
        title = f"Waveform for {Path(file_path).name.upper()}"

    # Load the waveform and determine the sample rate. The result is a 1D array of
    # amplitude values over time and the number of samples per second. Time is implied
    # by index position in the array divided by sample rate
    y, sr = librosa.load(file_path, sr=None)

    # Construct the time axis
    t = np.arange(len(y)) / sr

    # Create the chart
    _, ax = plt.subplots(figsize=(12, 4))
    ax.plot(t, y, linewidth=0.8)

    ax.set_title(title)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.margins(x=0)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
