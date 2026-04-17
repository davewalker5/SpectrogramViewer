#!/usr/bin/env bash

if [[ $# < 3 ]]; then
    echo "Usage: $0 INPUT-WAV-FILE OUTPUT-FOLDER-PATH TE-FACTOR [PROFILE]"
    exit 1
fi

# Activate the virtual environment
export PROJECT_ROOT=$( cd "$( dirname "$0" )/.." && pwd )
source "$PROJECT_ROOT/venv/bin/activate"

# Run the analyser
profile="${4:-te}"
python -m spectrogram \
    --config "$PROJECT_ROOT/config.json" \
    --profile "$profile" \
    --input "$1" \
    --output "$2" \
    --expansion-factor "$3" \
    --analyse \
    --mode "time-expansion"
