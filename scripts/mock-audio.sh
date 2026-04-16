#!/usr/bin/env bash

if [[ $# < 2 ]]; then
    echo "Usage: $0 INPUT-WAV-FILE OUTPUT-WAV-FILE [COPIES]"
    exit 1
fi

# Activate the virtual environment
export PROJECT_ROOT=$( cd "$( dirname "$0" )/.." && pwd )
source "$PROJECT_ROOT/venv/bin/activate"

# Generate the mock audio file
repetitions="${3:-2}"
python -m spectrogram --input "$1" --output "$2" --repetitions "$repetitions" --mock
