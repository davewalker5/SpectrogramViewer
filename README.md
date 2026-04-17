[![GitHub issues](https://img.shields.io/github/issues/davewalker5/SpectrogramViewer)](https://github.com/davewalker5/SpectrogramViewer/issues)
[![Releases](https://img.shields.io/github/v/release/davewalker5/SpectrogramViewer.svg?include_prereleases)](https://github.com/davewalker5/SpectrogramViewer/releases)
[![License: MIT](https://img.shields.io/badge/License-mit-blue.svg)](https://github.com/davewalker5/SpectrogramViewer/blob/main/LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org)
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/davewalker5/SpectrogramViewer)](https://github.com/davewalker5/SpectrogramViewer/)

# Spectrogram Viewer, Audio Processor and Bat Call Analyser

A command-line tool for analysing and visualising bat recordings, combining a simple noise-reduction pipeline with waveform, spectrogram, and pulse-level call analysis.

It is designed to explore the structure of bat calls in time-expansion and heterodyne recordings, showing how signal energy varies over time and frequency, and identifying individual pulses within a call sequence. The output combines waveform and time–frequency views with structured analysis, making it easy to interpret timing, frequency content, and overall signal shape.

The tool includes automated detection of call pulses and feeding buzzes, along with per-pulse measurements of timing, amplitude, decay behaviour, and frequency characteristics. Results can be exported as JSON for further analysis.

While primarily intended for bat recordings, the visualisation and processing components can be used with any suitable WAV audio.

---

# Running the Application

## Workflow

<img src="https://github.com/davewalker5/SpectrogramViewer/blob/main/diagrams/call-analysis-workflow.png" alt="Call Analysis Workflow" width="600">

The above is the recommended workflow for analysing a recording, assuming the goal is to go from a raw recording through to completion of the call analysis.

## Virtual Environment

To run the application, first create and activate a virtual environment by running the following at the root of the project:

```bash
python -m venv venv
source ./venv/bin/activate
```

Then, install the project dependencies:

```bash
pip install --upgrade pip
pip install -e .
```

This assumes a Mac or Linux-based setup and should be modified if running on Windows.

## Viewing a Waveform

<img src="https://github.com/davewalker5/SpectrogramViewer/blob/main/diagrams/BD-A-99-001-Waveform.png" alt="Example Waveform" width="600">

Open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --input /path/to/audio/file.wav --output /path/to/chart/file.png --waveform
```

The waveform chart will be written to the specified output file.

## Viewing a Spectrogram

<img src="https://github.com/davewalker5/SpectrogramViewer/blob/main/diagrams/BD-A-99-001-Spectrogram.png" alt="Example Spectrogram" width="600">

Open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --input /path/to/audio/file.wav --output /path/to/chart/file.png --spectrogram
```

The spectrogram chart will be written to the specified output file.

## Viewing a Noise Detection Profile

<img src="https://github.com/davewalker5/SpectrogramViewer/blob/main/diagrams/BD-A-99-001-Noise-Detection.png" alt="Example Noise Detection Chart" width="600">

Open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --input /path/to/audio/file.wav --output /path/to/chart/file.png --noise-detection
```

The noise detection chart will be written to the specified output file.

## Processing an Audio File

To run an audio file through the noise reduction pipeline (see below), open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --input /path/to/audio/file.wav --output /path/to/output/file.wav --process
```

## Running Call Detection on a Time Expansion Audio File

> [!NOTE]
> Call detection will work best with audio that's been run through the audio processing pipeline first.

To run an audio file through the call detection pipeline (see below), open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --input /path/to/audio/file.wav --output /path/to/output/folder --analyse --mode "time-expansion"
```

Two files will be written to the output folder:

| Output    | Description                                                                                         |
| --------- | --------------------------------------------------------------------------------------------------- |
| _file_-analysis.png  | A waveform view with detected pulse regions shaded, making it easy to visually verify the detection |
| _file_-analysis.json | A structured file containing one entry per detected pulse, including all measured properties        |

The file stem for both will be taken from the input file.

---

# Audio Processing Pipeline

The tool includes a simple, repeatable audio-processing pipeline designed to make recordings clearer and easier to interpret.

It follows the same general approach as a manual workflow in tools like Audacity, but applies it consistently and automatically.

## Overview

Each input recording is processed in the following stages:

| #   | Summary                             | Description                                                                                                                                                                                                |
| --- | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Detect noise regions                | The recording is scanned to find short sections that are likely to contain background noise only (quiet and low in signal-band energy) - the noise detection algorithm is documented in more detail, below |
| 2   | Build a noise profile               | These regions are combined into a single sample, representing the background noise in the recording                                                                                                        |
| 3   | Reduce noise (spectral subtraction) | The recording is transformed into the frequency domain, and the estimated noise profile is subtracted from each time slice. A small floor is retained to avoid introducing artefacts                       |
| 4   | High-pass filter                    | Low-frequency rumble and handling noise are removed, focusing the signal on the frequency range where bat calls occur (after time expansion)                                                               |
| 5   | Normalise                           | The result is scaled to a consistent peak level, making quiet recordings easier to inspect and listen to                                                                                                   |
| 6   | Output                              | The processed audio is written to disk for further inspection or visualisation                                                                                                                             |

## Design goals

The pipeline is intentionally simple and transparent:

- Repeatable — removes the need for manual selection of noise regions
- Interpretable — each step is easy to understand and adjust
- Non-destructive in spirit — preserves timing and structure of the original signal
- Practical — tuned for real-world field recordings rather than ideal conditions

_*Notes:*_

- This is a heuristic workflow, not a studio-grade restoration process
- It works best where recordings contain at least some gaps between calls
- The aim is clarity and consistency, not perfect noise removal

---

## Noise Detection

To reduce background noise automatically, the pipeline includes a simple noise-region detection step. This replaces the manual process of selecting a “quiet” section of audio (as you might do in Audacity).

### How It Works

The recording is divided into short, overlapping windows (typically 50 ms). For each window, two measurements are taken:

- Loudness (RMS amplitude) &rarr; Quieter windows are more likely to contain background noise only.
- Band energy ratio &rarr; The fraction of spectral energy within the expected signal band (for bat recordings, typically ~3.5–6.5 kHz after time expansion).

The band energy ratio is then used to identify the type of signal in the window:

- Low ratio &rarr; broadband noise / hiss
- High ratio &rarr; structured signal (e.g. bat calls)

A window is considered likely noise if it is both:

- Relatively quiet compared to the rest of the recording, and
- Relatively low in energy within the target band

Thresholds are determined using percentiles, so the detection adapts to each recording rather than relying on fixed values.

### From Windows to Regions

Neighbouring “noise” windows are merged into longer regions, and only regions above a minimum duration are kept. These regions are then used as the noise profile for subsequent noise reduction.

### Notes and Limitations

- This is a heuristic approach, not a guaranteed classification
- It works best when recordings contain genuine gaps between calls
- On dense or noisy recordings, it will tend to select the least signal-like sections rather than perfectly clean noise
- The goal is consistency and practicality, not perfect isolation

---

# Call Analysis (Time-Expansion Bat Recordings)

The tool includes a call analysis stage designed to identify individual bat pulses in a recording and extract simple measurements describing their timing, shape, and frequency content.

This is intended as a practical, repeatable way to turn recordings into structured data for further exploration, rather than a formal classification system.

## Overview

For suitable recordings (particularly cleaned time-expansion recordings), the analysis works in three main stages:

| #   | Summary               | Description                                                                                        |
| --- | --------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | Detect pulse regions  | The waveform is analysed to identify individual call pulses based on amplitude over time           |
| 2   | Identify feeding buzz | A cluster of closely spaced pulses at the end of a sequence is detected as a terminal feeding buzz |
| 3   | Extract pulse metrics | Each detected pulse is measured (timing, amplitude, decay shape, and frequency characteristics)    |
| 4   | Output                | Results are written as a JSON file alongside a waveform plot with detected regions highlighted     |

The result is a structured description of each pulse in the recording, suitable for further analysis or visualisation.

## How It Works

### Pulse Detection

The waveform is first converted into a smoothed amplitude envelope. This makes it easier to identify the overall shape of each call (a sharp attack followed by a decaying tail).

A dynamic threshold is then applied to this envelope to identify regions of activity:

- Thresholds are based on the noise floor and overall signal variation
- Short gaps within a pulse are bridged
- Very short regions are discarded

These steps produce a set of candidate pulse regions.

Each region is then refined so that it captures:

- The initial attack (onset of the call)
- The full decay tail (the “conical” shape typical of bat calls)

The aim is to preserve the natural structure of each pulse rather than to isolate only the loudest peak.

### Feeding Buzz Detection

Bat calls often end in a feeding buzz — a rapid sequence of closely spaced pulses as the bat approaches prey.

The analysis identifies this by:

- Examining the timing between successive pulses (inter-pulse interval)
- Searching for a cluster of pulses with consistently short spacing
- Focusing on the final portion of the recording

Pulses within this cluster are marked as part of the terminal buzz.

Because these pulses are shorter and more densely packed than earlier calls, a second-pass peak detector is applied within the buzz region to recover pulses that may not have been fully captured by the main detector.

### Pulse Measurements

For each detected pulse, a set of simple measurements is calculated.

#### Timing

- Start, peak, and end time within the recording
- Pulse duration
- Inter-pulse interval (IPI) to neighbouring pulses

For time-expansion recordings, these are also reported in estimated real time by applying the expansion factor.

#### Amplitude and Shape

- Peak amplitude
- RMS amplitude
- Attack duration (onset to peak)
- Decay duration (peak to end)
- Approximate decay slope
- Exponential decay fit (time constant and goodness of fit)

These describe the overall shape of the pulse in the time domain.

#### Frequency Content

A short-time Fourier transform (STFT) is applied within each pulse to estimate:

- Dominant (peak) frequency
- Spectral centroid (overall “centre of energy”)
- Bandwidth
- A simple frequency trace across the pulse (start, middle, end)
- Approximate frequency slope

For time-expansion recordings, these frequencies are scaled back to estimated real bat frequencies using the expansion factor.

### Output

The analysis produces two outputs:

| Output        | Description                                                                                         |
| ------------- | --------------------------------------------------------------------------------------------------- |
| Waveform plot | A waveform view with detected pulse regions shaded, making it easy to visually verify the detection |
| JSON file     | A structured file containing one entry per detected pulse, including all measured properties        |

This JSON output is intended as a starting point for:

- Exploratory analysis (e.g. plotting pulse timing or frequency trends)
- Comparing recordings
- Building simple call “signatures”
- Integrating into other workflows or reporting tools

## Notes and Limitations

- The analysis assumes reasonably clean recordings (noise-reduced beforehand)
- It is currently tuned for time-expansion recordings, not heterodyne
- Pulse boundaries are approximate and depend on thresholding and smoothing parameters
- Frequency estimates are derived from short windows and should be interpreted as approximations
- Very dense or noisy recordings may produce merged or missed pulses

The goal is to provide a consistent and useful representation of the signal, rather than perfect segmentation.

---

# Configuration File

The _config.json_ file in the root of the project contains configuration properties for the spectrogram viewer and processing pipeline.

## Named Profiles

The file has the following structure:

```json
{
    "default": {

    },
    "heterodyne": {

    }
}
```

It's a dictionary of dictionaries, each one representing a named set of parameters. On the command line, the profile to use is specified using:

```bash
--profile "<name>"
```

This can be specified for the spectrogram plotting, noise detection and audio processing options, documented above. If no profile is specified, the _default_ profile is used. For example, to process a file using the heterodyne processing parameters, the command line would be:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --profile "heterodyne" --input /path/to/audio/file.wav --output /path/to/output/file.wav --process
```

The remainder of this section describes each of the parameters.

## Spectrogram Viewer

| Section     | Property   | Purpose          |
| ----------- | ---------- | ---------------- |
| spectrogram | n_fft      | STFT window size |
| spectrogram | hop_length | STFT hop length  |

## Noise Detection

These parameters control how the tool identifies likely noise-only regions within a recording:

| Section                  | Property              | Purpose                                                                                                   |
| ------------------------ | --------------------- | --------------------------------------------------------------------------------------------------------- |
| noise_detection          | window_ms             | Length of each analysis window used to evaluate the signal (larger = smoother, smaller = more responsive) |
| noise_detection          | hop_ms                | Distance between successive windows (smaller values increase overlap and detection precision)             |
| noise_detection          | rms_percentile        | Selects the quietest windows based on loudness (percentage of windows treated as “quiet”)                 |
| noise_detection          | band_ratio_percentile | Selects windows with the least energy in the expected signal band (helps exclude faint calls)             |
| noise_detection          | min_region_ms         | Minimum duration required for a region to be considered valid noise (removes short gaps between calls)    |
| noise_detection          | band_low_hz           | Lower frequency bound of the expected signal band (used to detect bat-like energy)                        |
| noise_detection          | band_high_hz          | Upper frequency bound of the expected signal band (used to detect bat-like energy)                        |
| spectral_noise_reduction | n_fft                 | Size of the FFT window used for time–frequency analysis (controls frequency resolution)                   |

## Spectral Noise Reduction

These parameters control the spectral noise reduction stage, where an estimated noise profile is subtracted from the signal in the frequency domain.

| Section                  | Property           | Purpose                                                                                                             |
| ------------------------ | ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| spectral_noise_reduction | n_fft              | Length of each FFT window used to analyse the signal (larger = better frequency detail, lower = better time detail) |
| spectral_noise_reduction | hop_length         | Distance between successive FFT windows (smaller values increase overlap and smoothness)                            |
| spectral_noise_reduction | reduction_strength | Scales how much of the noise profile is removed from the signal (too high may introduce artefacts)                  |
| spectral_noise_reduction | floor_fraction     | Sets a minimum retained signal level to avoid “holes” or unnatural distortion after noise subtraction               |

## High Pass Filter

These parameters control the high-pass filtering stage, which removes low-frequency noise and focuses the signal on the frequency range of interest.

| Section          | Property  | Purpose                                                                                          |
| ---------------- | --------- | ------------------------------------------------------------------------------------------------ |
| high_pass_filter | cutoff_hz | Cutoff frequency of the filter; frequencies below this are reduced to remove low-frequency noise |
| high_pass_filter | order     | Determines how steeply the filter rolls off below the cutoff (higher = sharper transition)       |

## Normalisation

These parameters control the final normalisation step, which adjusts the overall signal level for consistency.

| Section       | Property    | Purpose                                                                                     |
| ------------- | ----------- | ------------------------------------------------------------------------------------------- |
| normalisation | peak_target | Maximum amplitude to scale the signal to (ensures consistent output level without clipping) |

## Call Analysis

| Section  | Property                           | Purpose                                                                                                              |
| -------- | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| analysis | envelope_smooth_ms                 | Smoothing applied to the waveform envelope (larger = smoother pulses, smaller = more sensitivity to short events)    |
| analysis | noise_floor_percentile             | Percentile used to estimate the noise floor of the recording (lower = more sensitive detection)                      |
| analysis | threshold_sigma                    | Controls how far above the noise floor a signal must be to be considered a pulse (higher = stricter detection)       |
| analysis | min_threshold                      | Absolute minimum amplitude threshold to avoid detecting very low-level noise                                         |
| analysis | max_gap_ms                         | Maximum gap allowed within a pulse before it is split into separate regions (helps keep decay tails intact)          |
| analysis | min_region_ms                      | Minimum duration for a detected pulse (filters out very short noise spikes)                                          |
| analysis | pre_padding_ms                     | Amount of time added before each detected region to capture the initial attack                                       |
| analysis | post_padding_ms                    | Amount of time added after each detected region to capture the full decay                                            |
| analysis | attack_threshold_fraction          | Fraction of peak amplitude used to define the start of the pulse (attack point)                                      |
| analysis | decay_threshold_fraction           | Fraction of peak amplitude used to define the end of the pulse (decay tail)                                          |
| analysis | buzz_max_ipi_ms                    | Maximum inter-pulse interval (IPI) for pulses to be considered part of a feeding buzz                                |
| analysis | buzz_min_run_length                | Minimum number of consecutive pulses required to classify a sequence as a feeding buzz                               |
| analysis | buzz_search_tail_fraction          | Fraction of the recording (from the end) searched for a feeding buzz (limits detection to the terminal portion)      |
| analysis | buzz_recovery_enabled              | Enables a second-pass detection to recover closely spaced buzz pulses that may have been missed                      |
| analysis | buzz_recovery_threshold_fraction   | Threshold (relative to local peak) used to detect additional buzz pulses (higher = stricter, lower = more sensitive) |
| analysis | buzz_recovery_min_peak_distance_ms | Minimum spacing between recovered buzz peaks (prevents over-detection of noise)                                      |
| analysis | buzz_recovery_region_ms            | Width of regions created around recovered buzz peaks (controls how tightly pulses are separated)                     |
| analysis | spectral_n_fft                     | FFT window size used for spectral analysis within each pulse (larger = better frequency resolution)                  |
| analysis | spectral_hop_length                | Step size between successive FFT windows (smaller = smoother time resolution)                                        |
| analysis | spectral_window                    | Window function applied during spectral analysis (e.g. “hann”)                                                       |
| analysis | spectral_min_valid_bins            | Minimum number of valid spectral frames required to produce frequency measurements                                   |
| analysis | json_indent                        | Indentation level used when writing the output JSON file (purely for readability)                                    |

# Authors

- **Dave Walker** - _Initial work_

# Feedback

To file issues or suggestions, please use the [Issues](https://github.com/davewalker5/SpectrogramViewer/issues) page for this project on GitHub.

# License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details
