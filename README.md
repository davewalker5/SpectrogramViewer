[![GitHub issues](https://img.shields.io/github/issues/davewalker5/SpectrogramViewer)](https://github.com/davewalker5/SpectrogramViewer/issues)
[![Releases](https://img.shields.io/github/v/release/davewalker5/SpectrogramViewer.svg?include_prereleases)](https://github.com/davewalker5/SpectrogramViewer/releases)
[![License: MIT](https://img.shields.io/badge/License-mit-blue.svg)](https://github.com/davewalker5/SpectrogramViewer/blob/main/LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org)
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/davewalker5/SpectrogramViewer)](https://github.com/davewalker5/SpectrogramViewer/)

# Spectrogram Viewer and Audio Processor

A small command-line tool for processing and visualising audio recordings, combining a simple noise-reduction pipeline with waveform and spectrogram views.

It is designed for exploring the structure of recordings, showing how signal energy varies over time and frequency. The output combines a waveform view with a time–frequency spectrogram, making it easy to interpret timing, frequency content, and overall signal shape at a glance.

The tool is primarily intended for wildlife recordings, particularly bat recordings (time expansion and heterodyne), but can be used with any suitable WAV audio.

## Running the Application

### Virtual Environment

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

### Viewing a Spectrogram

Open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --input /path/to/audio/file.wav --spectrogram
```

A window should be displayed showing the chart:

![Example Spectrogram](https://github.com/davewalker5/SpectrogramViewer/blob/main/diagrams/spectrogram.png)

### Viewing a Noise Detection Profile

Open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --input /path/to/audio/file.wav --noise-detection
```
A window should be displayed showing the chart:

![Example Noise Detection Profile](https://github.com/davewalker5/SpectrogramViewer/blob/main/diagrams/noise-detection.png)

### Processing an Audio File

To run an audio file through the noise reduction pipeline (see below), open a terminal window and run the following from the project folder:

```bash
source ./venv/bin/activate
python -m spectrogram --config config.json --input /path/to/audio/file.wav --output /path/to/output/file.wav --process
```

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

# Configuration File

The _config.json_ file in the root of the project contains configuration properties for the spectrogram viewer and processing pipeline.

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


# Authors

- **Dave Walker** - _Initial work_

# Feedback

To file issues or suggestions, please use the [Issues](https://github.com/davewalker5/SpectrogramViewer/issues) page for this project on GitHub.

# License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details
