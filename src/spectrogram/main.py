# --------------------------------------------------------------------------------
# General imports
# --------------------------------------------------------------------------------
import argparse
from pathlib import Path
from pprint import pprint as pp

# --------------------------------------------------------------------------------
# Spectrogram application inports
# --------------------------------------------------------------------------------
from spectrogram.config_reader import get_application_version, load_config, ConfigurationError
from spectrogram.spectrogram import show_spectrogram
from spectrogram.noise_detection import inspect_noise_detection
from spectrogram.pipeline import process_audio_file
from spectrogram.waveform import show_waveform
from spectrogram.call_analysis_time_expansion import analyse_time_expansion_file
from spectrogram.call_analysis_heterodyne import analyse_heterodyne_file
from spectrogram.mock_audio import make_duplicated_recording

# --------------------------------------------------------------------------------
# Program properties
# --------------------------------------------------------------------------------
PROJECT_FOLDER = Path(__file__).parent.parent.parent
PACKAGE_NAME = "spectrogram"
PROGRAM_NAME = "Spectrogram Viewer"
PROGRAM_DESCRIPTION = "Spectrogram and waveform viewer for audio recordings"

# --------------------------------------------------------------------------------
# Analysis modes
# --------------------------------------------------------------------------------
TIME_EXPANSION = "time-expansion"
HETERODYNE = "heterodyne"


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
    parser.add_argument("-i", "--input", required=True, help="Input audio file path")
    parser.add_argument("-o", "--output", required=True, help="Output file or folder path")
    parser.add_argument("-c", "--config", help="Configuration file path")
    parser.add_argument("-pr", "--profile", default="default", help="Configuration profile name")
    parser.add_argument("-ef", "--expansion-factor", type=float, default=10.0, help="Time expansion factor")
    parser.add_argument("-mo", "--mode", choices=[TIME_EXPANSION, HETERODYNE], help="Analysis mode")
    parser.add_argument("-t", "--title", help="Chart title")
    parser.add_argument("-g", "--gap", type=float, default=0.5, help="Gap between copies in mocked audio files")
    parser.add_argument("-r", "--repetitions", type=int, default=2, help="Number of repetitions in mocked audio files")
    parser.add_argument("-w", "--waveform", action='store_true', help="Plot the waveform for the input file")
    parser.add_argument("-s", "--spectrogram", action='store_true', help="Plot the spectrogram for the input file")
    parser.add_argument("-nd", "--noise-detection", action='store_true', help="Identify and plot noise regions in the input file")
    parser.add_argument("-p", "--process", action='store_true', help="Process the input file and write the processed output to the output file")
    parser.add_argument("-a", "--analyse", action='store_true', help="Analyse the input WAV file for bat call structure")
    parser.add_argument("-m", "--mock", action='store_true', help="Mock up a WAV file with multiple copies of a given input file")

    # Parse the command line
    args = parser.parse_args()

    # Conditional requirement logic
    if args.analyse and not args.mode:
        parser.error("--mode is required when --analysis is specified")

    return args


def main():
    args = parse_args()

    # Load the configuration
    if args.config and args.profile:
        load_config(args.config, args.profile)

    try:
        if args.waveform:
            show_waveform(args.input, args.title, args.output)
        elif args.spectrogram:
            show_spectrogram(args.input, args.title, args.output)
        elif args.noise_detection:
            inspect_noise_detection(args.input, args.title, args.output)
        elif args.process:
            process_audio_file(args.input, args.output)
        elif args.analyse and args.mode == TIME_EXPANSION:
            analyse_time_expansion_file(args.input, args.expansion_factor, args.output)
        elif args.analyse and args.mode == HETERODYNE:
            analyse_heterodyne_file(args.input, args.output)
        elif args.mock:
            make_duplicated_recording(args.input, args.output, args.gap, args.repetitions)
    except ConfigurationError as e:
        print(e)
    except KeyboardInterrupt:
        pass
