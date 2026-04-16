#!/usr/bin/env bash

if [[ $# != 2 ]]; then
    echo "Usage: $0 WAV-FILE CHART-FILE-PATH"
    exit 1
fi

# Activate the virtual environment
export PROJECT_ROOT=$( cd "$( dirname "$0" )/.." && pwd )
source "$PROJECT_ROOT/venv/bin/activate"

# Run the analyser
python -m spectrogram --input "$1" --output "$2" --waveform
