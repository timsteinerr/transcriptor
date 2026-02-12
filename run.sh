#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Prefer Homebrew Python 3.12 over system Python
if [ -x /opt/homebrew/bin/python3.12 ]; then
    PYTHON=/opt/homebrew/bin/python3.12
elif command -v python3.12 &>/dev/null; then
    PYTHON=python3.12
elif command -v python3 &>/dev/null; then
    PYTHON=python3
else
    echo "Error: python3 is required. Install it with: brew install python@3.12"
    exit 1
fi
echo "Using Python: $($PYTHON --version)"

# Check for ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "Error: ffmpeg is required."
    echo "  macOS:   brew install ffmpeg"
    echo "  Ubuntu:  sudo apt install ffmpeg"
    echo "  Windows: https://ffmpeg.org/download.html"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies (first run may download the Whisper model)..."
pip install -q -r requirements.txt

# Check for yt-dlp
if ! command -v yt-dlp &>/dev/null; then
    echo "Installing yt-dlp..."
    pip install -q yt-dlp
fi

echo ""
echo "============================================"
echo "  Transcriptor is starting..."
echo "  Open http://localhost:${PORT:-5000} in your browser"
echo "============================================"
echo ""

# Set model size (options: tiny, base, small, medium, large)
# 'base' is a good balance of speed and accuracy
export WHISPER_MODEL="${WHISPER_MODEL:-base}"

python3 app.py
