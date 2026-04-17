#!/usr/bin/env bash

if [[ $# < 2 ]]; then
    echo "Usage: $0 INPUT-WAV-FILE OUTPUT-FOLDER-PATH [PROFILE]"
    exit 1
fi

# Activate the virtual environment
export PROJECT_ROOT=$( cd "$( dirname "$0" )/.." && pwd )
source "$PROJECT_ROOT/venv/bin/activate"

# Run the analyser
profile="${3:-heterodyne}"
python -m spectrogram \
    --config "$PROJECT_ROOT/config.json" \
    --profile "$profile" \
    --input "$1" \
    --output "$2" \
    --analyse \
    --mode "heterodyne"
