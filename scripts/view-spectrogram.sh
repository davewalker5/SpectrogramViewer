#!/usr/bin/env bash

if [[ $# != 1 ]]; then
    echo "Usage: $0 WAV-FILE"
    exit 1
fi

# Activate the virtual environment
export PROJECT_ROOT=$( cd "$( dirname "$0" )/.." && pwd )
source "$PROJECT_ROOT/venv/bin/activate"

# Run the analyser
python -m spectrogram --config "$PROJECT_ROOT/config.json" --input "$1" --spectrogram
