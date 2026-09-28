"""QA video: source with the chosen crop windows drawn, next to the final short."""
import subprocess

import cv2
import numpy as np

from .media import FF, probe, read_frames
from .reframe import A_PANEL, A_SINGLE, FIT, SPLIT

DH = 540


def _rect(img, crop, aspect, s, color):
    cx, cy, h = crop
    w = h * aspect
    p0 = (int((cx - w / 2) * s), int((cy - h / 2) * s))
    p1 = (int((cx + w / 2) * s), int((cy + h / 2) * s))
    cv2.rectangle(img, p0, p1, color, 2)


def debug_video(info, cuts, plans, short_path, out_path, log=print):
    sw = int(round(info.width * DH / info.height / 2)) * 2
    s = DH / info.height
    ow = int(round(1080 * DH / 1920 / 2)) * 2
    sinfo = probe(short_path)
    total = sum(c.n for c in cuts)
    enc = subprocess.Popen([FF, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{sw + ow}x{DH}", "-r", str(info.fps), "-i", "-",
                            "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                            str(out_path)], stdin=subprocess.PIPE)
    outs = read_frames(sinfo, 0, total, ow, DH)
    for c in cuts:
        plan = plans[c.seg]
        for j, fr in enumerate(read_frames(info, c.src_f0, c.n, sw, DH)):
            f = c.src_f0 + j
            i = plan.idx(f)
            img = fr.copy()
            mode = plan.mode[i]
            if mode == SPLIT:
                _rect(img, plan.a[i], A_PANEL, s, (0, 220, 255))
                _rect(img, plan.b[i], A_PANEL, s, (255, 160, 0))
            elif mode != FIT:
                _rect(img, plan.a[i], A_SINGLE, s, (0, 255, 0))
                ax, ay = plan.anchor[i]
                cv2.circle(img, (int(ax * s), int(ay * s)), 4, (0, 0, 255), -1)
            label = ["single", "split", "fit"][mode] + f"  src {f / info.fps_f:.2f}s  zoom {c.zoom:.2f}"
            cv2.putText(img, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
            cv2.putText(img, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            enc.stdin.write(np.hstack([img, next(outs)]).tobytes())
    enc.stdin.close()
    enc.wait()
    log(f"  debug video: {out_path}")
