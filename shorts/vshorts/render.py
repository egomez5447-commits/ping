"""Compose 1080x1920 frames from the plan and encode the final short."""
import json
import re
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from . import config
from .config import OUT_W, OUT_H
from .media import FF, read_audio, read_frames, write_wav
from .reframe import A_PANEL, A_SINGLE, FIT, SINGLE, SPLIT, clamp_crop

ACCENT_BGR = (0, 213, 255)
SR = 48000
PUSH_IN = 0.035   # slow push over each piece; keeps static talking heads alive


def _warp(src, cx, cy, h, aspect, ow, oh):
    w = h * aspect
    s = oh / h
    x0, y0 = cx - w / 2, cy - h / 2
    M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
    interp = cv2.INTER_CUBIC if s > 1.05 else cv2.INTER_AREA if s < 0.7 else cv2.INTER_LINEAR
    if interp == cv2.INTER_AREA:  # warpAffine has no area filter; pre-shrink instead
        small = cv2.resize(src, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        M = np.float32([[1, 0, -x0 * s], [0, 1, -y0 * s]])
        out = cv2.warpAffine(small, M, (ow, oh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    else:
        out = cv2.warpAffine(src, M, (ow, oh), flags=interp, borderMode=cv2.BORDER_REPLICATE)
    if s > 1.4:  # restore some bite lost to upscaling
        out = cv2.addWeighted(out, 1.3, cv2.GaussianBlur(out, (0, 0), 1.1), -0.3, 0)
    return out


def _punch(crop, anchor, p, aspect, W, H):
    cx, cy, h = crop
    ax, ay = anchor
    cx2, cy2, h2 = ax + (cx - ax) / p, ay + (cy - ay) / p, h / p
    cx2, cy2, h2 = clamp_crop(np.float64(cx2), np.float64(cy2), np.float64(h2), aspect, W, H)
    return float(cx2), float(cy2), float(h2)


def _fit(src):
    H, W = src.shape[:2]
    s_bg = max(OUT_W / W, OUT_H / H)
    bg = cv2.resize(src, (max(1, int(W * s_bg / 8)), max(1, int(H * s_bg / 8))), interpolation=cv2.INTER_AREA)
    bg = cv2.GaussianBlur(bg, (0, 0), 6)
    bg = cv2.resize(bg, (int(W * s_bg) + 2, int(H * s_bg) + 2), interpolation=cv2.INTER_LINEAR)
    y0, x0 = (bg.shape[0] - OUT_H) // 2, (bg.shape[1] - OUT_W) // 2
    out = (bg[y0:y0 + OUT_H, x0:x0 + OUT_W] * 0.55).astype(np.uint8)
    s = OUT_W / W
    fg = cv2.resize(src, (OUT_W, int(round(H * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    y = (OUT_H - fg.shape[0]) // 2
    out[y:y + fg.shape[0]] = fg
    return out


def compose(frame, plan, f, p):
    H, W = frame.shape[:2]
    i = plan.idx(f)
    mode = plan.mode[i]
    if mode == FIT:
        return _fit(frame)
    if mode == SPLIT:
        ps = 1 + (p - 1) * 0.6
        half = OUT_H // 2
        out = np.empty((OUT_H, OUT_W, 3), np.uint8)
        for crop, y in ((plan.a[i], 0), (plan.b[i], half)):
            c = _punch(crop, crop[:2], ps, A_PANEL, W, H)
            out[y:y + half] = _warp(frame, *c, A_PANEL, OUT_W, half)
        out[half - 3:half + 3] = 12
        return out
    c = _punch(plan.a[i], plan.anchor[i], p, A_SINGLE, W, H)
    return _warp(frame, *c, A_SINGLE, OUT_W, OUT_H)


def build_audio(info, cuts, fps, wav_path):
    pieces = []
    fade = int(0.006 * SR)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    for c in cuts:
        n = int(round((c.out_f0 + c.n) / fps * SR)) - int(round(c.out_f0 / fps * SR))
        a = read_audio(info, c.src_f0 / fps, n / SR, SR, 2)
        if len(a) > 2 * fade:
            a[:fade] *= ramp
            a[-fade:] *= ramp[::-1]
        pieces.append(a)
    audio = np.vstack(pieces) if pieces else np.zeros((1, 2), np.float32)
    write_wav(wav_path, audio, SR)
    return len(audio) / SR


def _loudnorm_filter(wav, target=-14.0, tp=-1.5, lra=11.0):
    base = f"loudnorm=I={target}:TP={tp}:LRA={lra}"
    err = subprocess.run([FF, "-hide_banner", "-nostdin", "-i", str(wav), "-af", base + ":print_format=json",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        return base
    j = json.loads(m.group(0))
    if j["input_i"] in ("-inf", "inf") or float(j["input_i"]) < -70:
        return "anull"  # silent track: nothing to normalise
    return (f"{base}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}"
            f":measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")


def render(info, cuts, plans, ass_path, workdir, out_path, grade=True, log=print):
    workdir = Path(workdir)
    fps = info.fps_f
    wav = workdir / "audio.wav"
    build_audio(info, cuts, fps, wav)
    af = _loudnorm_filter(wav)
    total = sum(c.n for c in cuts)
    vf = []
    if grade:
        vf.append("eq=contrast=1.04:saturation=1.10")
    vf.append(f"ass={Path(ass_path).name}:fontsdir={config.FONTS}")
    enc = [FF, "-y", "-v", "error", "-nostdin", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{OUT_W}x{OUT_H}", "-r", str(info.fps), "-i", "-", "-i", wav.name,
           "-filter:v", ",".join(vf), "-af", af,
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart",
           "-shortest", str(Path(out_path).resolve())]
    proc = subprocess.Popen(enc, stdin=subprocess.PIPE, cwd=workdir)
    k, t_start = 0, time.time()
    by_seg = {}
    for c in cuts:
        by_seg.setdefault(c.seg, []).append(c)
    order = []
    for c in cuts:  # decode each segment once, in output order
        if c.seg not in order:
            order.append(c.seg)
    try:
        for seg in order:
            sc = by_seg[seg]
            sf0, sf1 = sc[0].src_f0, sc[-1].src_f1
            plan = plans[seg]
            ci = 0
            for j, frame in enumerate(read_frames(info, sf0, sf1 - sf0)):
                f = sf0 + j
                while ci < len(sc) and f >= sc[ci].src_f1:
                    ci += 1
                if ci >= len(sc):
                    break
                c = sc[ci]
                if f < c.src_f0:
                    continue
                u = (f - c.src_f0) / max(c.n - 1, 1)
                out = compose(frame, plan, f, c.zoom * (1 + PUSH_IN * u))
                x = int(round(OUT_W * (k + 1) / total))
                out[:10, :x] = ACCENT_BGR
                proc.stdin.write(out.tobytes())
                k += 1
                if k % 150 == 0:
                    log(f"    rendered {k}/{total} frames ({k / (time.time() - t_start):.1f} fps)")
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg encode failed ({rc})")
    log(f"  wrote {out_path} ({k} frames, {k / fps:.1f}s)")
