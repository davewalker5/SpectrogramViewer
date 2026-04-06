#!/usr/bin/env bash

# Capture the current folder and change to the project root
CWD=`pwd`
export PROJECT_ROOT=$( cd "$( dirname "$0" )/.." && pwd )
cd "$PROJECT_ROOT"

# Deactivate and remove the old virtual environment, if present
echo "Removing existing Virtual Environment, if present ..."
deactivate 2> /dev/null || true
rm -fr venv

# Create a new environment and activate it
echo "Creating new Virtual Environment ..."
python -m venv venv
. venv/bin/activate

# Make sure pip is up to date
pip install --upgrade pip

# Install the requirements
pip install -e .

# Restore the current folder
cd "$CWD"
