from pathlib import Path
import soundfile as sf
import numpy as np


def make_duplicated_recording(input: str, output: str, gap_seconds: float, repetitions: int) -> None:
    """
    Generate a 'mock' recording for testing purposes

    The function reads a single source audio file specified by 'input', combines the specified
    number of repetitions of it with gaps between them, as specified, then writes the result to
    the output file specified by 'input'.

    This is useful for testing multi-pass processing where a multi-pass TE recording isn't available.
    """
    # Read the input file
    input_path = Path(input)
    samples, sr = sf.read(input_path)

    # Generate a gap segment
    gap = np.zeros((int(sr * gap_seconds),) if samples.ndim == 1 else (int(sr * gap_seconds), samples.shape[1]))

    # Initialise combined with the first copy
    combined = samples.copy()

    # Append additional repetitions with gaps
    for _ in range(1, repetitions):
        combined = np.concatenate([combined, gap, samples], axis=0)

    # Write the output file
    output_path = Path(output)
    sf.write(output_path, combined, sr)
    print(f"Combined {repetitions} copies of {input_path.name} into {output_path.name}")
