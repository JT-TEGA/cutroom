#!/usr/bin/env bash
# Install / repair everything the pipeline needs (safe to re-run).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh"; exit 1; }
command -v ffmpeg >/dev/null || brew install ffmpeg
command -v node >/dev/null || brew install node

[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dev]"

npm install --no-audit --no-fund

mkdir -p briefs raw music voiceover assets/fonts assets/sfx output work workspace scripts/models
M=scripts/models/face_detection_yunet_2023mar.onnx
[ -s "$M" ] || curl -sSL -o "$M" "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
F="assets/fonts/Montserrat[wght].ttf"
[ -s "$F" ] || curl -sSL -o "$F" "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf"
[ -s assets/fonts/Anton-Regular.ttf ] || curl -sSL -o assets/fonts/Anton-Regular.ttf "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"
[ -s "assets/fonts/Inter[opsz,wght].ttf" ] || curl -sSL -o "assets/fonts/Inter[opsz,wght].ttf" "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf"
for s in Regular Italic; do
  [ -s "assets/fonts/InstrumentSerif-$s.ttf" ] || curl -sSL -o "assets/fonts/InstrumentSerif-$s.ttf" "https://github.com/google/fonts/raw/main/ofl/instrumentserif/InstrumentSerif-$s.ttf"
done
PYTHONPATH=. .venv/bin/python -m engine.make_sfx
chmod +x scripts/ve
scripts/ve doctor
