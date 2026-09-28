"""Edit decision list -> frame-exact cut list + output-timeline words.

An EDL is JSON like:
{
  "hook": "He turned down *$10 million*",   # headline for the first seconds; *x* = accent colour
  "hook_seconds": 3.0,
  "segments": [                            # played in THIS order (a later punchline first = cold open)
    {"start": 412.3, "end": 416.8},
    {"start": 371.0, "end": 409.5}
  ],
  "trim_silence": true, "max_pause": 0.35,  # jump-cut out pauses longer than this
  "emphasis": ["million", "never"],         # caption words drawn bigger and in the accent colour
  "punch_zoom": 1.12,                       # alternate zoom on jump cuts (1 = off)
  "layout": [{"start": 380, "end": 386, "mode": "split"}]   # optional source-time overrides
}
"""
import json
import re
from dataclasses import dataclass

import numpy as np

LEAD = 0.12        # keep this much air before the first word of a segment
TAIL = 0.30        # ...and after the last word
PAD_AFTER = 0.10   # around a trimmed pause: breathing room after a word
PAD_BEFORE = 0.07  # ...and before the next one
MIN_PIECE = 0.40   # never leave a sliver shorter than this between two cuts


@dataclass
class Cut:
    seg: int        # EDL segment index
    src_f0: int     # first source frame (inclusive)
    src_f1: int     # end source frame (exclusive)
    out_f0: int     # first output frame
    jump: bool      # True when a pause was removed right before this piece
    zoom: float = 1.0

    @property
    def n(self):
        return self.src_f1 - self.src_f0


def load_edl(path):
    with open(path) as f:
        edl = json.load(f)
    if not edl.get("segments"):
        raise ValueError("EDL needs at least one segment")
    for s in edl["segments"]:
        if float(s["end"]) <= float(s["start"]):
            raise ValueError(f"segment end <= start: {s}")
    return edl


def norm_word(w: str) -> str:
    return re.sub(r"[^\w$%']", "", w.lower())


def _loud_gap(audio16, seg_t0, a, b, speech_rms):
    """Is there non-speech sound worth keeping (laugh, music hit, gasp) in [a, b)?"""
    if audio16 is None or speech_rms <= 0:
        return False
    i0, i1 = int((a - seg_t0) * 16000), int((b - seg_t0) * 16000)
    chunk = audio16[max(i0, 0):max(i1, 0)]
    if len(chunk) < 800:
        return False
    win = 800  # 50 ms windows; one loud window is enough (a laugh burst)
    n = len(chunk) // win
    rms = np.sqrt((chunk[:n * win].reshape(n, win) ** 2).mean(axis=1))
    return bool(np.percentile(rms, 90) > 0.45 * speech_rms)


def build_cuts(edl, words, info, audio_loader=None, log=print):
    fps = info.fps_f
    trim = edl.get("trim_silence", True)
    max_pause = float(edl.get("max_pause", 0.35))
    punch = float(edl.get("punch_zoom", 1.12))
    cuts, out_f = [], 0
    for si, seg in enumerate(edl["segments"]):
        s = max(0.0, float(seg["start"]))
        e = min(info.duration, float(seg["end"]))
        sw = [w for w in words if w["e"] > s and w["s"] < e]
        if sw:
            first, last = sw[0], sw[-1]
            s = max(0.0, first["s"] - 0.04) if first["s"] < s else max(s, first["s"] - LEAD)
            e = min(info.duration, last["e"] + 0.06) if last["e"] > e else min(e, last["e"] + TAIL)
        pieces = [(s, e)]
        if trim and seg.get("trim_silence", True) and len(sw) > 1:
            audio16 = audio_loader(s, e) if audio_loader else None
            speech_rms = 0.0
            if audio16 is not None and len(audio16):
                parts = [audio16[int((w["s"] - s) * 16000):int((w["e"] - s) * 16000)] for w in sw]
                parts = [p for p in parts if len(p)]
                if parts:
                    speech_rms = float(np.sqrt(np.mean(np.concatenate(parts) ** 2)))
            pieces, cur = [], s
            for a, b in zip(sw, sw[1:]):
                if b["s"] - a["e"] <= max_pause:
                    continue
                c0, c1 = a["e"] + PAD_AFTER, b["s"] - PAD_BEFORE
                if c1 - c0 < 0.12 or _loud_gap(audio16, s, a["e"], b["s"], speech_rms):
                    continue
                pieces.append((cur, c0))
                cur = c1
            pieces.append((cur, e))
            merged = [list(pieces[0])]  # bridge slivers instead of flashing them
            for p in pieces[1:]:
                if merged[-1][1] - merged[-1][0] < MIN_PIECE or p[1] - p[0] < MIN_PIECE:
                    merged[-1][1] = p[1]
                else:
                    merged.append(list(p))
            pieces = [tuple(p) for p in merged]
        prev_f1 = -1
        for j, (a, b) in enumerate(pieces):
            f0, f1 = int(round(a * fps)), int(round(b * fps))
            f0 = max(f0, prev_f1)
            f1 = min(f1, info.n_frames)
            if f1 - f0 < 2:
                continue
            jump = j > 0 and f0 > prev_f1
            cuts.append(Cut(si, f0, f1, out_f, jump))
            out_f += f1 - f0
            prev_f1 = f1
    # Alternate punch-in on consecutive jump cuts so each cut reads as intentional.
    level = 0
    for c in cuts:
        level = (level + 1) % 2 if c.jump else 0
        c.zoom = punch if level else 1.0
    total = out_f / fps
    removed = sum(float(s["end"]) - float(s["start"]) for s in edl["segments"]) - total
    log(f"  edit: {len(cuts)} pieces, {total:.1f}s out ({max(removed, 0):.1f}s of dead air removed)")
    if total > 60:
        log("  note: over 60s. Shorts allows up to 3 min, but <60s usually retains better")
    return cuts


def out_words(cuts, words, fps, emphasis=()):
    emph = {norm_word(w) for w in emphasis}
    res = []
    for c in cuts:
        t0, t1, o0 = c.src_f0 / fps, c.src_f1 / fps, c.out_f0 / fps
        for w in words:
            if w["e"] <= t0 or w["s"] >= t1:
                continue
            mid = (w["s"] + w["e"]) / 2
            if not (t0 <= mid < t1):
                continue
            s = o0 + max(w["s"], t0) - t0
            e = o0 + min(w["e"], t1) - t0
            nw = norm_word(w["w"])
            auto = bool(re.search(r"\d|\$|%", w["w"]))
            res.append({"w": w["w"], "s": s, "e": e, "emph": nw in emph or auto})
    res.sort(key=lambda w: w["s"])
    return res


def src_to_out(cuts, fps):
    """Map a source frame -> output frame for frames that survive the edit."""
    m = {}
    for c in cuts:
        for k in range(c.n):
            m[c.src_f0 + k] = c.out_f0 + k
    return m
