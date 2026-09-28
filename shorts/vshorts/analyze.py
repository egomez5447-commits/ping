"""Look at the source the way an editor would before reframing it.

For a source frame range this finds:
  * shot cuts (every frame, HSV content delta with an adaptive threshold),
  * face tracks (YuNet at ~15 fps, greedy IoU/centre association per shot),
  * a mouth-aperture signal per face (MediaPipe landmarks) plus the speech
    loudness envelope, so the planner can match lips to voice (who is talking),
  * a saliency profile (spectral residual + motion) for shots with no faces.
"""
import json
import os
from pathlib import Path

import cv2
import numpy as np

from . import config
from .media import read_audio, read_frames

SAL_W, SAL_H = 160, 90


def analysis_size(info, max_w=960):
    if info.width <= max_w:
        return info.width, info.height
    return max_w, int(round(info.height * max_w / info.width / 2)) * 2


class MouthMeter:
    """Lip aperture / face height from MediaPipe Face Landmarker, NaN if unsure."""

    def __init__(self):
        os.environ.setdefault("GLOG_minloglevel", "2")
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        import mediapipe as mp

        self.mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(config.FACE_LANDMARKER)),
            running_mode=vision.RunningMode.IMAGE, num_faces=1)
        self.lm = vision.FaceLandmarker.create_from_options(opts)

    def __call__(self, img, box):
        x, y, w, h = box
        side = max(w, h) * 1.8
        cx, cy = x + w / 2, y + h / 2
        x0, y0 = int(max(cx - side / 2, 0)), int(max(cy - side / 2, 0))
        x1, y1 = int(min(cx + side / 2, img.shape[1])), int(min(cy + side / 2, img.shape[0]))
        if min(x1 - x0, y1 - y0) < 28:
            return float("nan")
        crop = cv2.resize(img[y0:y1, x0:x1], (256, 256), interpolation=cv2.INTER_CUBIC)
        rgb = np.ascontiguousarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        res = self.lm.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb))
        if not res.face_landmarks:
            return float("nan")
        p = res.face_landmarks[0]
        face_h = np.hypot(p[10].x - p[152].x, p[10].y - p[152].y)
        return float(np.hypot(p[13].x - p[14].x, p[13].y - p[14].y) / max(face_h, 1e-6))

    def close(self):
        self.lm.close()


def _spectral_residual(g):
    F = np.fft.fft2(g)
    la = np.log(np.abs(F) + 1e-6)
    sr = la - cv2.blur(la, (3, 3))
    s = np.abs(np.fft.ifft2(np.exp(sr + 1j * np.angle(F)))) ** 2
    s = cv2.GaussianBlur(s.astype(np.float32), (0, 0), 2.5)
    return s / (s.max() + 1e-9)


def _detect_cuts(scores, fps, min_shot=0.5):
    s = np.asarray(scores, float)
    cuts = []
    for i in range(1, len(s)):
        nb = np.r_[s[max(1, i - 4):i], s[i + 1:i + 5]]
        base = nb.mean() if len(nb) else 0.0
        if s[i] >= 30 or (s[i] >= 12 and s[i] >= 3.0 * base + 2):
            if not cuts or i - cuts[-1] >= min_shot * fps:
                cuts.append(i)
    return cuts


def _iou(a, b):
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax1, bx1) - max(a[0], b[0]))
    ih = max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter + 1e-9)


def _track(samples, shots, fps, max_gap_s=0.7):
    tracks, next_id = [], 0
    for si, (a, b) in enumerate(shots):
        live = []
        for smp in samples:
            if not (a <= smp["f"] < b):
                continue
            live = [t for t in live if smp["f"] - t["f"][-1] <= max_gap_s * fps]
            used = set()
            pairs = []
            for di, d in enumerate(smp["faces"]):
                for ti, t in enumerate(live):
                    lb = t["box"][-1]
                    dist = np.hypot(d["box"][0] + d["box"][2] / 2 - lb[0] - lb[2] / 2,
                                    d["box"][1] + d["box"][3] / 2 - lb[1] - lb[3] / 2) / max(lb[2], 1)
                    ratio = d["box"][3] / max(lb[3], 1)
                    if (dist < 0.8 or _iou(d["box"], lb) > 0.2) and 0.6 < ratio < 1.65:
                        pairs.append((dist - _iou(d["box"], lb), di, ti))
            taken_t = set()
            for _, di, ti in sorted(pairs):
                if di in used or ti in taken_t:
                    continue
                t = live[ti]
                d = smp["faces"][di]
                t["f"].append(smp["f"]); t["box"].append(d["box"]); t["mouth"].append(d["mouth"])
                t["score"].append(d["score"])
                used.add(di); taken_t.add(ti)
            for di, d in enumerate(smp["faces"]):
                if di in used:
                    continue
                t = {"id": next_id, "shot": si, "f": [smp["f"]], "box": [d["box"]],
                     "mouth": [d["mouth"]], "score": [d["score"]]}
                next_id += 1
                tracks.append(t)
                live.append(t)
    return tracks


def analyze_range(info, f0, f1, log=print, cache_dir=None):
    """Analyse source frames [f0, f1). Results are in source pixel coordinates."""
    if cache_dir:
        cp = Path(cache_dir) / f"analysis_{f0}_{f1}.json"
        if cp.exists():
            return json.loads(cp.read_text())
    aw, ah = analysis_size(info)
    sx, sy = info.width / aw, info.height / ah
    step = max(1, int(round(info.fps_f / 15)))
    det = cv2.FaceDetectorYN.create(str(config.YUNET), "", (aw, ah), 0.6, 0.3, 50)
    mouth = MouthMeter()
    scores, samples, sal_f, sal_prof = [], [], [], []
    prev_hsv = prev_g = None
    col_prior = np.exp(-0.5 * ((np.arange(SAL_W) - SAL_W / 2) / (SAL_W * 0.35)) ** 2)
    n = f1 - f0
    for i, fr in enumerate(read_frames(info, f0, n, aw, ah)):
        small = cv2.resize(fr, (128, 72), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.int16)
        scores.append(0.0 if prev_hsv is None else float(np.abs(hsv - prev_hsv).mean(axis=(0, 1)).mean()))
        prev_hsv = hsv
        if i % step:
            continue
        f = f0 + i
        _, raw = det.detect(fr)
        faces = []
        for r in (raw if raw is not None else []):
            box = [float(r[0] * sx), float(r[1] * sy), float(r[2] * sx), float(r[3] * sy)]
            if box[3] < 0.035 * info.height:
                continue
            faces.append({"box": box, "score": float(r[14]), "abox": r[:4].tolist(), "mouth": None})
        if len(faces) >= 2:
            for fc in faces:
                m = mouth(fr, fc["abox"])
                fc["mouth"] = None if np.isnan(m) else m
        for fc in faces:
            fc.pop("abox")
        samples.append({"f": f, "faces": faces})
        g = cv2.cvtColor(cv2.resize(fr, (SAL_W, SAL_H), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_BGR2GRAY).astype(np.float32)
        sal = _spectral_residual(g)
        if prev_g is not None:
            mot = cv2.GaussianBlur(np.abs(g - prev_g), (0, 0), 3)
            sal = sal + 1.5 * np.clip(mot / 25.0, 0, 1)
        prev_g = g
        prof = sal.sum(axis=0) * (0.75 + 0.25 * col_prior)
        sal_f.append(f)
        sal_prof.append(np.round(prof, 3).tolist())
        if log and len(samples) % 150 == 0:
            log(f"    analysed {i + 1}/{n} frames")
    mouth.close()
    # Speech loudness at each sample, for audio-visual speaker matching: a talker's
    # lip aperture rises and falls with their own voice; a nodding listener's doesn't.
    fps = info.fps_f
    audio = read_audio(info, f0 / fps, (f1 - f0) / fps, 16000, 1)[:, 0]
    half = int(16000 / 15)
    env = []
    for f in sal_f:
        c = int((f - f0) / fps * 16000)
        seg = audio[max(0, c - half):c + half]
        env.append(round(float(np.log1p(100 * np.sqrt(np.mean(seg ** 2)))) if len(seg) else 0.0, 4))
    cut_idx = _detect_cuts(scores, info.fps_f)
    bounds = [0] + cut_idx + [n]
    shots = [[f0 + a, f0 + b] for a, b in zip(bounds, bounds[1:]) if b > a]
    tracks = _track(samples, shots, info.fps_f)
    res = {"f0": f0, "f1": f1, "step": step, "W": info.width, "H": info.height,
           "fps": info.fps_f, "shots": shots, "tracks": tracks,
           "saliency": {"f": sal_f, "profile": sal_prof}, "env": env}
    log(f"  analysis: {len(shots)} shot(s), {len(tracks)} raw face track(s)")
    if cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(res))
    return res
