#!/usr/bin/env bash
# Fetch the models and caption fonts used by make_short.py (~700 MB, mostly ASR).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p models fonts
dl() { [ -s "$1" ] || { echo "fetching $1"; curl -fsSL --retry 3 -o "$1.part" "$2" && mv "$1.part" "$1"; }; }
dl models/yunet.onnx https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
dl models/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
dl models/silero_vad.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
P=sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8
if [ ! -d "models/$P" ]; then
  dl models/$P.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$P.tar.bz2
  tar -xjf models/$P.tar.bz2 -C models && rm models/$P.tar.bz2
fi
G=https://raw.githubusercontent.com/google/fonts/main/ofl
dl fonts/Poppins-Black.ttf $G/poppins/Poppins-Black.ttf
dl fonts/Anton-Regular.ttf $G/anton/Anton-Regular.ttf
echo "models and fonts ready"
