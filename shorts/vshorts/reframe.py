"""Virtual camera operator: analysis -> per-frame 9:16 layout.

Layouts
  SINGLE  one 9:16 window that follows a face, a group that fits, or saliency
  SPLIT   two stacked 1080x960 panels, one per person (two-shots too wide to crop)
  FIT     the full frame over a blurred fill (only when asked for via EDL override)

Camera moves are planned offline, like an operator who has seen the take: a dead
zone keeps the frame locked while the subject sways, and a zero-phase Gaussian
turns each reposition into an eased move that starts a beat early. Real shot cuts
and speaker switches are hard cuts; a face entering an empty frame is a pan.
"""
import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

from .analyze import SAL_W

SINGLE, SPLIT, FIT = 0, 1, 2
A_SINGLE = 9 / 16
A_PANEL = 9 / 8
FACE_FRAC = 0.20        # face height / crop height for a single close framing
PANEL_FACE_FRAC = 0.34  # ...and inside a split panel
EYE_LINE = 0.40         # face centre sits 40% down a single frame
PANEL_EYE_LINE = 0.44
MAX_UPSCALE = 2.6       # never enlarge source pixels more than this


class Plan:
    def __init__(self, f0, f1):
        n = f1 - f0
        self.f0, self.f1 = f0, f1
        self.mode = np.zeros(n, np.int8)
        self.a = np.zeros((n, 3), np.float32)       # cx, cy, h of the single / top crop
        self.b = np.zeros((n, 3), np.float32)       # cx, cy, h of the bottom panel crop
        self.anchor = np.zeros((n, 2), np.float32)  # punch-in zoom centre (the face)
        self.notes = []

    def idx(self, f):
        return int(min(max(f - self.f0, 0), len(self.mode) - 1))


def smooth_path(target, fps, dz, sigma_s):
    target = np.asarray(target, float)
    n = len(target)
    if n == 0:
        return target
    k = max(1, int(0.35 * fps)) | 1
    t = median_filter(target, size=k, mode="nearest")
    r = float(np.median(t[:max(1, int(0.5 * fps))]))
    rest = np.empty(n)
    for i, v in enumerate(t):
        if v - r > dz:
            r = v - 0.3 * dz
        elif r - v > dz:
            r = v + 0.3 * dz
        rest[i] = r
    return gaussian_filter1d(rest, sigma=max(sigma_s * fps, 0.5), mode="nearest")


def clamp_crop(cx, cy, h, aspect, W, H):
    h = np.minimum(h, H)
    h = np.minimum(h, W / aspect)
    w = h * aspect
    return np.clip(cx, w / 2, W - w / 2), np.clip(cy, h / 2, H - h / 2), h


def _av_sync(mouth, env, k, min_valid=6):
    """Rolling lip/voice correlation per sample (NaN where unknown, 0 when still)."""
    out = np.full(len(mouth), np.nan)
    for i in range(len(mouth)):
        m = mouth[max(0, i - k):i + k + 1]
        e = env[max(0, i - k):i + k + 1]
        ok = ~np.isnan(m)
        if ok.sum() < min_valid:
            continue
        m, e = m[ok], e[ok]
        if m.std() < 0.004 or e.std() < 1e-3:
            out[i] = 0.0  # lips still, or no voice to match against
            continue
        best = -1.0
        for lag in (-1, 0, 1):  # lips lead the voice by up to one sample (~70 ms)
            mm, ee = (m[:len(m) - lag], e[lag:]) if lag >= 0 else (m[-lag:], e[:len(e) + lag])
            if len(mm) >= min_valid and mm.std() > 0 and ee.std() > 0:
                best = max(best, float(np.corrcoef(mm, ee)[0, 1]))
        out[i] = max(best, 0.0)
    return out


class _Track:
    def __init__(self, t, fps, H):
        self.id = t["id"]
        self.shot = t["shot"]
        self.f = np.asarray(t["f"], float)
        self.box = np.asarray(t["box"], float)
        self.cx = self.box[:, 0] + self.box[:, 2] / 2
        self.cy = self.box[:, 1] + self.box[:, 3] / 2
        self.fh = float(np.median(self.box[:, 3]))
        self.fw = float(np.median(self.box[:, 2]))
        self.mouth = np.array([np.nan if m is None else m for m in t["mouth"]], float)
        self.score = float(np.mean(t["score"]))
        self.fps = fps

    def present(self, f, max_gap):
        if f < self.f[0] - max_gap or f > self.f[-1] + max_gap:
            return False
        return np.min(np.abs(self.f - f)) <= max_gap

    def at(self, frames):
        return np.interp(frames, self.f, self.cx), np.interp(frames, self.f, self.cy)


def _good_tracks(an, H):
    fps = an["fps"]
    out = []
    for t in an["tracks"]:
        if len(t["f"]) < 3 or (t["f"][-1] - t["f"][0]) / fps < 0.3:
            continue
        tr = _Track(t, fps, H)
        if tr.fh < 0.045 * H or tr.score < 0.62:
            continue
        out.append(tr)
    return out


def _speech_mask(frames, fps, words):
    if not words:
        return np.zeros(len(frames), bool)
    t = np.asarray(frames, float) / fps
    s = np.array([w["s"] for w in words]) - 0.1
    e = np.array([w["e"] for w in words]) + 0.1
    idx = np.searchsorted(s, t, side="right") - 1
    return (idx >= 0) & (t <= e[np.clip(idx, 0, None)])


def _speaker_timeline(tracks, sframes, fps, step, speech, env_f, env, force=False):
    """Who is talking at each sample -> (track id per sample, confident?, score).

    Uses audio-visual sync (lip aperture vs. speech loudness), not raw mouth motion,
    so head turns and nods of a listener don't read as talking. Deliberately
    conservative: without clear evidence the caller falls back to a split screen.
    """
    k = max(4, int(round(0.8 * fps / step)))
    sync = []
    for tr in tracks:
        e = np.interp(tr.f, env_f, env) if len(env_f) else np.zeros(len(tr.f))
        a = _av_sync(tr.mouth, e, k)
        ok = ~np.isnan(a)
        v = np.interp(sframes, tr.f[ok], a[ok]) if ok.sum() >= 2 else np.full(len(sframes), np.nan)
        v[(sframes < tr.f[0] - fps * 0.5) | (sframes > tr.f[-1] + fps * 0.5)] = np.nan
        sync.append(v)
    sync = np.array(sync)
    thr, margin = 0.30, 0.12
    winners = np.full(len(sframes), -1)
    overlap = 0
    for i in range(len(sframes)):
        if not speech[i]:
            continue
        col = np.where(np.isnan(sync[:, i]), -1, sync[:, i])
        order = np.argsort(-col)
        best = col[order[0]]
        second = col[order[1]] if len(order) > 1 else -1
        if best > thr and best - max(second, 0) >= margin:
            winners[i] = order[0]
        if best > thr and second > thr:
            overlap += 1
    n_speech = int(speech.sum())
    conf = (winners >= 0).sum() / max(n_speech, 1)
    enough = n_speech * step / fps >= 1.5
    confident = force or (enough and conf >= 0.5 and overlap / max(n_speech, 1) < 0.3)
    hold = int(round(1.4 * fps / step))
    persist = max(1, int(round(0.25 * fps / step)))
    cur, last_switch = None, -10 ** 9
    tl = np.full(len(sframes), -1)
    for i in range(len(sframes)):
        w = winners[i]
        if w >= 0 and w != cur:
            j = i
            while j < len(sframes) and winners[j] in (w, -1) and j - i < persist:
                j += 1
            if cur is None or (j - i >= persist and i - last_switch >= hold):
                start = i if cur is None else max(i, last_switch + hold)
                tl[start:] = w
                cur, last_switch = w, start
        if cur is not None and tl[i] < 0:
            tl[i] = cur
    if cur is not None:
        first = int(np.argmax(tl >= 0))
        tl[:first] = tl[first]
    ids = np.array([tr.id for tr in tracks])
    return np.where(tl >= 0, ids[np.clip(tl, 0, None)], -1), confident, conf


def _sal_x(an, frames, crop_w):
    """Best horizontal crop centre per frame from the saliency column profile."""
    sf = np.asarray(an["saliency"]["f"], float)
    if len(sf) == 0:
        return np.full(len(frames), an["W"] / 2)
    W = an["W"]
    prof = np.asarray(an["saliency"]["profile"], float)
    wc = max(1, min(SAL_W, int(round(crop_w / W * SAL_W))))
    cs = np.cumsum(np.pad(prof, ((0, 0), (1, 0))), axis=1)
    win = cs[:, wc:] - cs[:, :-wc]
    best = win.argmax(axis=1)
    peak = win.max(axis=1) / (win.mean(axis=1) + 1e-9)
    xs = (best + wc / 2) * W / SAL_W
    xs = np.where(peak < 1.06, W / 2, xs)  # flat saliency: stay centred
    return np.interp(frames, sf, xs)


def _override_at(overrides, t):
    for o in overrides or ():
        if float(o["start"]) <= t < float(o["end"]):
            return o
    return None


def _merge_short_runs(keys, locked, min_len):
    changed = True
    while changed:
        changed = False
        runs, s = [], 0
        for i in range(1, len(keys) + 1):
            if i == len(keys) or keys[i] != keys[s] or locked[i] != locked[s]:
                runs.append((s, i))
                s = i
        if len(runs) < 2:
            break
        for ri, (a, b) in enumerate(runs):
            if b - a < min_len and not locked[a]:
                src = runs[ri - 1] if ri > 0 else runs[ri + 1]
                if locked[src[0]] and keys[src[0]][0] == "fit":
                    continue
                for i in range(a, b):
                    keys[i] = keys[src[0]]
                changed = True
                break
    return keys


def plan_range(an, info, words, overrides=None, two_person="auto", log=print):
    fps, W, H, step = an["fps"], an["W"], an["H"], an["step"]
    f0, f1 = an["f0"], an["f1"]
    plan = Plan(f0, f1)
    zmax = max(1.0, min(2.2, H / (1920 / MAX_UPSCALE)))
    crop_w1 = min(H * A_SINGLE, W)
    tracks = _good_tracks(an, H)
    all_sf = np.asarray(an["saliency"]["f"], int)
    max_gap = 0.7 * fps
    for si, (sa, sb) in enumerate(an["shots"]):
        st = [t for t in tracks if t.shot == si]
        sf = all_sf[(all_sf >= sa) & (all_sf < sb)]
        if len(sf) == 0:
            sf = np.array([sa])
        speech = _speech_mask(sf, fps, words)
        multi = [t for t in st if sum(t.present(f, max_gap) for f in sf) >= 2]
        force = any((o := _override_at(overrides, f / fps)) and o.get("mode") == "speaker" for f in sf)
        spk_tl, spk_ok, spk_conf = (np.full(len(sf), -1), False, 0.0)
        if len(multi) >= 2 and two_person != "split":
            spk_tl, spk_ok, spk_conf = _speaker_timeline(
                multi, sf.astype(float), fps, step, speech, np.asarray(an["saliency"]["f"], float),
                np.asarray(an.get("env", []), float), force or two_person == "speaker")
        keys, locked = [], []
        for i, f in enumerate(sf):
            pres = [t for t in st if t.present(f, max_gap)]
            o = _override_at(overrides, f / fps)
            key = None
            if o:
                m = o.get("mode")
                if m == "fit":
                    key = ("fit",)
                elif m == "split" and len(pres) >= 2:
                    two = sorted(sorted(pres, key=lambda t: -t.fh)[:2], key=lambda t: t.at(f)[0])
                    key = ("split", two[0].id, two[1].id)
                elif m == "single":
                    tgt = o.get("target", "largest")
                    if pres:
                        if isinstance(tgt, int):
                            cand = [t for t in pres if t.id == tgt] or pres
                            pick = cand[0]
                        elif tgt == "left":
                            pick = min(pres, key=lambda t: t.at(f)[0])
                        elif tgt == "right":
                            pick = max(pres, key=lambda t: t.at(f)[0])
                        elif tgt == "center":
                            pick = min(pres, key=lambda t: abs(t.at(f)[0] - W / 2))
                        else:
                            pick = max(pres, key=lambda t: t.fh)
                        key = ("face", pick.id)
                    else:
                        key = ("sal",)
            locked.append(key is not None)
            if key is None:
                if not pres:
                    key = ("sal",)
                elif len(pres) == 1:
                    key = ("face", pres[0].id)
                else:
                    ranked = sorted(pres, key=lambda t: -t.fh)
                    group = None
                    for kk in (3, 2):
                        cand = ranked[:kk]
                        if len(cand) < kk:
                            continue
                        xs = [t.at(f)[0] for t in cand]
                        x0 = min(x - 0.85 * t.fw for x, t in zip(xs, cand))
                        x1 = max(x + 0.85 * t.fw for x, t in zip(xs, cand))
                        if x1 - x0 <= 0.95 * crop_w1:
                            group = tuple(sorted(t.id for t in cand))
                            break
                    spk = spk_tl[i]
                    if group:
                        key = ("group", group)
                    elif spk_ok and spk in [t.id for t in pres]:
                        key = ("face", int(spk))
                    elif len(pres) == 2 or two_person == "split":
                        two = sorted(ranked[:2], key=lambda t: t.at(f)[0])
                        key = ("split", two[0].id, two[1].id)
                    else:
                        key = ("face", ranked[0].id)
            keys.append(key)
        keys = _merge_short_runs(keys, locked, max(1, int(round(1.0 * fps / step))))
        # Expand sample decisions to frame runs.
        runs, s = [], 0
        for i in range(1, len(keys) + 1):
            if i == len(keys) or keys[i] != keys[s]:
                fa = sa if s == 0 else int(sf[s])
                fb = sb if i == len(keys) else int(sf[i])
                runs.append((keys[s], fa, fb))
                s = i
        desc = ", ".join(f"{(a) / fps:.1f}-{b / fps:.1f}s {k[0]}"
                         + (f"#{k[1]}" if k[0] == "face" else "") for k, a, b in runs)
        extra = f" (speaker-detect conf {spk_conf:.2f}{', on' if spk_ok else ''})" if len(multi) >= 2 else ""
        plan.notes.append(f"shot {si} [{sa / fps:.1f}-{sb / fps:.1f}s]: {desc}{extra}")
        byid = {t.id: t for t in st}
        # Chain soft-connected single runs; speaker switches / layout changes are hard cuts.
        chains = []
        for key, fa, fb in runs:
            if chains and key[0] in ("face", "group", "sal") and chains[-1]["kind"] == "single":
                prev = chains[-1]["keys"][-1]
                hard = (prev[0] == "face" and key[0] == "face" and prev[1] != key[1]
                        and byid[prev[1]].present(fa, max_gap) and byid[key[1]].present(fa, max_gap))
                if not hard:
                    chains[-1]["keys"].append(key)
                    chains[-1]["spans"].append((fa, fb))
                    continue
            kind = "single" if key[0] in ("face", "group", "sal") else key[0]
            chains.append({"kind": kind, "keys": [key], "spans": [(fa, fb)]})
        for ch in chains:
            fa, fb = ch["spans"][0][0], ch["spans"][-1][1]
            frames = np.arange(fa, fb, dtype=float)
            sl = slice(fa - f0, fb - f0)
            if ch["kind"] == "fit":
                plan.mode[sl] = FIT
                continue
            if ch["kind"] == "split":
                _, lid, rid = ch["keys"][0]
                plan.mode[sl] = SPLIT
                for tid, nid, dst in ((lid, rid, plan.a), (rid, lid, plan.b)):
                    tr, nb = byid[tid], byid[nid]
                    cx, cy = tr.at(frames)
                    h = float(np.clip(tr.fh / PANEL_FACE_FRAC, max(0.35 * H, 960 / MAX_UPSCALE), H))
                    w = h * A_PANEL
                    ty = cy + (0.5 - PANEL_EYE_LINE) * h
                    px = smooth_path(cx, fps, 0.10 * w, 0.3)
                    py = smooth_path(ty, fps, 0.06 * h, 0.4)
                    # Slide each panel away from the other person so their face doesn't
                    # peek into the edge, as long as this panel's own face stays framed.
                    ncx = gaussian_filter1d(nb.at(frames)[0], max(0.5 * fps, 0.5), mode="nearest")
                    own = gaussian_filter1d(cx, max(0.5 * fps, 0.5), mode="nearest")
                    keep = 0.5 * tr.fw + 0.12 * w
                    if tid == lid:
                        px = np.maximum(np.minimum(px, ncx - 0.75 * nb.fw - w / 2), own + keep - w / 2)
                    else:
                        px = np.minimum(np.maximum(px, ncx + 0.75 * nb.fw + w / 2), own - keep + w / 2)
                    px, py, hh = clamp_crop(px, py, np.full(len(frames), h), A_PANEL, W, H)
                    dst[sl] = np.stack([px, py, hh], 1)
                plan.anchor[sl] = plan.a[sl, :2]
                continue
            tx, ty, th, ax, ay = (np.empty(len(frames)) for _ in range(5))
            only_sal = all(k[0] == "sal" for k in ch["keys"])
            for key, (ra, rb) in zip(ch["keys"], ch["spans"]):
                fr = np.arange(ra, rb, dtype=float)
                j = slice(ra - fa, rb - fa)
                if key[0] == "sal":
                    tx[j] = _sal_x(an, fr, crop_w1)
                    ty[j], th[j] = H / 2, H
                    ax[j], ay[j] = tx[j], H / 2
                    continue
                ids = [key[1]] if key[0] == "face" else list(key[1])
                trs = [byid[t] for t in ids]
                xy = [t.at(fr) for t in trs]
                if key[0] == "face":
                    cx, cy = xy[0]
                    z = np.clip(FACE_FRAC / (trs[0].fh / H), 1.0, zmax)
                else:
                    lo = np.min([x - 0.85 * t.fw for (x, _), t in zip(xy, trs)], axis=0)
                    hi = np.max([x + 0.85 * t.fw for (x, _), t in zip(xy, trs)], axis=0)
                    cx, cy = (lo + hi) / 2, np.mean([y for _, y in xy], axis=0)
                    zf = FACE_FRAC / (max(t.fh for t in trs) / H)
                    zw = 0.95 * crop_w1 / max(float(np.median(hi - lo)), 1.0)
                    z = np.clip(min(zf, zw), 1.0, zmax)
                h = H / z
                tx[j], ty[j], th[j] = cx, cy + (0.5 - EYE_LINE) * h, h
                ax[j], ay[j] = cx, cy
            cw = float(np.median(th)) * A_SINGLE
            if only_sal:
                px = smooth_path(tx, fps, 0.18 * cw, 0.7)
            else:
                px = smooth_path(tx, fps, 0.12 * cw, 0.3)
            py = smooth_path(ty, fps, 0.06 * H, 0.4)
            ph = gaussian_filter1d(th, sigma=max(0.6 * fps, 0.5), mode="nearest")
            px, py, ph = clamp_crop(px, py, ph, A_SINGLE, W, H)
            plan.mode[sl] = SINGLE
            plan.a[sl] = np.stack([px, py, ph], 1)
            plan.anchor[sl] = np.stack([gaussian_filter1d(ax, max(0.3 * fps, 0.5), mode="nearest"),
                                        gaussian_filter1d(ay, max(0.3 * fps, 0.5), mode="nearest")], 1)
    for n in plan.notes:
        log("    " + n)
    return plan
