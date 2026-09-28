"""Paths and constants shared by the vertical-shorts pipeline."""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = Path(os.environ.get("VSHORTS_MODELS", ROOT / "models"))
FONTS = Path(os.environ.get("VSHORTS_FONTS", ROOT / "fonts"))

YUNET = MODELS / "yunet.onnx"
FACE_LANDMARKER = MODELS / "face_landmarker.task"
SILERO_VAD = MODELS / "silero_vad.onnx"
PARAKEET = MODELS / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"

# Output canvas: 9:16 at 1080p, the native size for Shorts / Reels / TikTok.
OUT_W, OUT_H = 1080, 1920

# Platform UI safe zones on a 1080x1920 canvas (TikTok is the most crowded):
# top ~160px holds the tab bar, bottom ~400px the caption/handle/music row,
# right ~150px the like/comment/share rail.
SAFE_TOP = 170
SAFE_BOTTOM = 1920 - 420
SAFE_RIGHT = 1080 - 150


def ffmpeg_bin() -> str:
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover
        raise RuntimeError("ffmpeg not found; install it or `pip install imageio-ffmpeg`") from e
