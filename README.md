[![GitHub issues](https://img.shields.io/github/issues/davewalker5/SpectrogramViewer)](https://github.com/davewalker5/SpectrogramViewer/issues)
[![Releases](https://img.shields.io/github/v/release/davewalker5/SpectrogramViewer.svg?include_prereleases)](https://github.com/davewalker5/SpectrogramViewer/releases)
[![License: MIT](https://img.shields.io/badge/License-mit-blue.svg)](https://github.com/davewalker5/SpectrogramViewer/blob/main/LICENSE)
[![Language](https://img.shields.io/badge/language-python-blue.svg)](https://www.python.org)
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/davewalker5/SpectrogramViewer)](https://github.com/davewalker5/SpectrogramViewer/)

# Spectrogram Viewer

A small command-line tool for viewing audio recordings as a waveform and spectrogram.

It is designed for simple inspection of recordings, showing how signal energy varies over time and frequency. The output combines a waveform view with a time–frequency spectrogram, making it easy to see structure, timing, and frequency content at a glance.

The tool was originally developed for exploring bat recordings (time expansion and heterodyne), but it can be used with any WAV audio file.

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

Open a terminal window and run the following:

```bash
python -m spectrogram --file /path/to/audio/file.wav --title "Chart Title"
```

A window should be displayed showing the charts:

![Example Spectrogram](https://github.com/davewalker5/SpectrogramViewer/blob/main/diagrams/example.png)

# Authors

- **Dave Walker** - _Initial work_

# Feedback

To file issues or suggestions, please use the [Issues](https://github.com/davewalker5/SpectrogramViewer/issues) page for this project on GitHub.

# License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details
