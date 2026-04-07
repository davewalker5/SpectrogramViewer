#!/usr/bin/env bash

if [[ $# != 2 ]]; then
    echo "Usage: $0 INPUT-WAV-FILE OUTPUT-WAV-FILE"
    exit 1
fi

# Activate the virtual environment
CWD=`pwd`
export PROJECT_ROOT=$( cd "$( dirname "$0" )/.." && pwd )
cd "$PROJECT_ROOT"

# Run the analyser
python -m spectrogram --config "$PROJECT_ROOT/config.json" --input "$1" --output "$2" --process

# Restore the current folder
cd "$CWD"
