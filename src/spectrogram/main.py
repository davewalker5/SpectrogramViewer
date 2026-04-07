# --------------------------------------------------------------------------------
# General imports
# --------------------------------------------------------------------------------
import argparse
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# --------------------------------------------------------------------------------
# Spectrogram application inports
# --------------------------------------------------------------------------------
from spectrogram.spectrogram import show_spectrogram
from spectrogram.noise_detection import inspect_noise_detection
from spectrogram.pipeline import process_audio_file

# --------------------------------------------------------------------------------
# Program properties
# --------------------------------------------------------------------------------
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
    parser.add_argument("-i", "--input", help="Input audio file path")
    parser.add_argument("-o", "--output", help="Output audio file path")
    parser.add_argument("-t", "--title", help="Chart title")
    parser.add_argument("-w", "--window-size", type=int, default=2048, help="STFT window size")
    parser.add_argument("-hl", "--hop-length", type=int, default=256, help="STFT hop length")
    parser.add_argument("-s", "--spectrogram", action='store_true', help="Plot the spectrogram for the input file")
    parser.add_argument("-nd", "--noise-detection", action='store_true', help="Identify and plot noise regions in the input file")
    parser.add_argument("-p", "--process", action='store_true', help="Process the input file and write the processed output to the output file")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.spectrogram:
            show_spectrogram(args.input, args.title, args.window_size, args.hop_length)
        elif args.noise_detection:
            inspect_noise_detection(args.input, args.title)
        elif args.process:
            process_audio_file(args.input, args.output)
    except KeyboardInterrupt:
        pass
