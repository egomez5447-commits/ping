"""Shortlist self-contained, hook-first moments from a transcript.

This is a first pass for a human (or Claude) editor, not a replacement: it favours
windows that open on a strong line, move at a talking pace and end on a finished
sentence. Read the shortlist, then write the EDL by hand.
"""
import re

HOOK_WORDS = {
    "never", "nobody", "secret", "biggest", "mistake", "crazy", "insane", "truth", "wrong",
    "why", "how", "stop", "worst", "best", "money", "million", "billion", "died", "fired",
    "quit", "actually", "honestly", "lie", "lied", "scared", "shocked", "impossible", "hate",
    "love", "rich", "broke", "free", "everyone", "nothing", "everything", "first", "last",
    "only", "real", "problem", "wish", "regret", "hardest", "easiest", "fastest", "banned",
}
WEAK_OPENERS = {"and", "so", "but", "because", "or", "which", "that", "then", "also", "um", "uh", "like"}


def sentences(words, gap=0.8):
    out, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > gap):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.?!]$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _text(ws):
    return " ".join(w["w"] for w in ws)


def _norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def score_window(sents):
    ws = [w for s in sents for w in s]
    dur = ws[-1]["e"] - ws[0]["s"]
    first = sents[0]
    first_toks = [_norm(w["w"]) for w in first]
    sc = 0.0
    sc += 2.0 * sum(t in HOOK_WORDS for t in first_toks[:12])
    sc += 2.5 if first[-1]["w"].endswith("?") else 0
    sc += 1.5 if any(re.search(r"\d", w["w"]) for w in first) else 0
    sc += 1.0 if "you" in first_toks[:8] else 0
    sc -= 3.0 if first_toks and first_toks[0] in WEAK_OPENERS else 0
    sc += 0.3 * sum(_norm(w["w"]) in HOOK_WORDS for w in ws)
    wps = len(ws) / max(dur, 1e-6)
    sc -= 2.0 * max(0, 2.0 - wps) + 1.0 * max(0, wps - 3.6)
    sc += 1.0 if re.search(r"[.!?]$", ws[-1]["w"]) else -1.5
    pauses = sum(1 for a, b in zip(ws, ws[1:]) if b["s"] - a["e"] > 1.2)
    sc -= 0.5 * pauses
    return sc


def suggest(words, min_s=20, max_s=55, top=8):
    sents = sentences(words)
    cands = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            s, e = sents[i][0]["s"], sents[j][-1]["e"]
            if e - s > max_s:
                break
            if e - s >= min_s:
                cands.append((score_window(sents[i:j + 1]), s, e, i, j))
    cands.sort(key=lambda c: -c[0])
    picked = []
    for c in cands:
        if all(c[2] <= p[1] or c[1] >= p[2] for p in picked):
            picked.append(c)
        if len(picked) >= top:
            break
    return [{"score": round(c[0], 2), "start": round(c[1], 2), "end": round(c[2], 2),
             "opening": _text(sents[c[3]])[:160],
             "text": _text([w for s in sents[c[3]:c[4] + 1] for w in s])} for c in picked]
