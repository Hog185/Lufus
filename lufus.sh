#!/usr/bin/env bash

set -euo pipefail

VENV_DIR=".venv"

# Ensure python exists
if ! command -v python3 &> /dev/null; then
    echo "python3 not found"
    exit 1
fi

echo "Setting up virtual environment..."

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install Briefcase if not installed
if ! pip show briefcase > /dev/null 2>&1; then
    echo "Installing Briefcase..."
    pip install --upgrade pip
    pip install briefcase
fi

# Check system dependencies
REQUIRED_CMDS=(
    parted mkfs.vfat mkfs.ntfs mkfs.exfat mkfs.ext4
    badblocks blockdev wimmountrw chntpw
)

MISSING=()

for cmd in "${REQUIRED_CMDS[@]}"; do
    if ! command -v "$cmd" &> /dev/null; then
        MISSING+=("$cmd")
    fi
done
# Print missing dependencies
if [ ${#MISSING[@]} -ne 0 ]; then
    echo "Missing system tools:"
    printf ' - %s\n' "${MISSING[@]}"
    echo "Install them before continuing."
fi


echo "Running app..."

# Run the app
briefcase dev
