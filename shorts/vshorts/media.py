"""Thin ffmpeg wrappers: probe, frame-accurate decode to numpy, audio I/O."""
import re
import subprocess
import wave
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from .config import ffmpeg_bin

FF = ffmpeg_bin()


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: Fraction
    duration: float
    n_frames: int
    has_audio: bool

    @property
    def fps_f(self) -> float:
        return float(self.fps)

    def t2f(self, t: float) -> int:
        """Seconds -> nearest frame index."""
        return int(round(t * self.fps_f))

    def f2t(self, f: int) -> float:
        return f / self.fps_f


def _nice_fps(x: float) -> Fraction:
    for cand in (Fraction(24000, 1001), Fraction(30000, 1001), Fraction(60000, 1001)):
        if abs(float(cand) - x) < 0.002:
            return cand
    return Fraction(x).limit_denominator(1001)


def probe(path) -> VideoInfo:
    path = str(path)
    if not Path(path).exists():
        raise FileNotFoundError(path)
    err = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    cap = cv2.VideoCapture(path)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else n / fps
    m = re.search(r"Video: .*? (\d+(?:\.\d+)?) fps", err)
    if m:
        fps = float(m.group(1))
    fr = _nice_fps(fps)
    if n <= 0:
        n = int(dur * float(fr))
    return VideoInfo(path, w, h, fr, dur, n, bool(re.search(r"Stream #.*Audio:", err)))


def read_frames(info: VideoInfo, f0: int, count: int, width: int = None, height: int = None):
    """Yield `count` consecutive BGR frames starting at source frame f0.

    Input-side -ss with a re-decode is frame accurate in ffmpeg >= 2.1. If the
    stream ends early the last frame is repeated so callers stay in sync.
    """
    width = width or info.width
    height = height or info.height
    cmd = [FF, "-v", "error", "-nostdin", "-ss", f"{f0 / info.fps_f:.6f}", "-i", info.path,
           "-map", "0:v:0", "-frames:v", str(count), "-fps_mode", "passthrough"]
    if (width, height) != (info.width, info.height):
        cmd += ["-vf", f"scale={width}:{height}:flags=area"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=width * height * 3 * 4)
    nbytes = width * height * 3
    last = None
    try:
        for _ in range(count):
            buf = proc.stdout.read(nbytes)
            if len(buf) == nbytes:
                last = np.frombuffer(buf, np.uint8).reshape(height, width, 3)
            elif last is None:
                last = np.zeros((height, width, 3), np.uint8)
            yield last
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def read_audio(info: VideoInfo, t0: float, dur: float, sr: int = 48000, channels: int = 2) -> np.ndarray:
    """Decode [t0, t0+dur) to float32 (samples, channels); silence if no audio."""
    n = int(round(dur * sr))
    if not info.has_audio or n <= 0:
        return np.zeros((max(n, 0), channels), np.float32)
    cmd = [FF, "-v", "error", "-nostdin", "-ss", f"{t0:.6f}", "-t", f"{dur:.6f}", "-i", info.path,
           "-map", "0:a:0", "-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    a = np.frombuffer(out, np.float32).reshape(-1, channels)
    if len(a) < n:
        a = np.vstack([a, np.zeros((n - len(a), channels), np.float32)])
    return a[:n].copy()


def write_wav(path, audio: np.ndarray, sr: int = 48000):
    a = np.clip(audio, -1, 1)
    pcm = (a * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(a.shape[1] if a.ndim > 1 else 1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
