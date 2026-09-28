"""Burned-in captions and hook headline as an ASS script for libass.

Captions: 1-3 word pages in a heavy sans, uppercase, thick outline; the word being
spoken lights up in the accent colour; emphasis words (numbers, money, EDL list)
get their own page, bigger and green. Each page pops in (scale 80% -> 104% -> 100%).
Hook: a boxed headline at the top for the first seconds; *starred* words in yellow.
Placement follows the layout: single frame -> lower-middle (clear of the platform UI);
split screen -> on the seam between the two panels.
"""
import re

from .config import OUT_W, OUT_H, SAFE_TOP

YELLOW = "&H0000D5FF&"   # ASS colours are &HAABBGGRR
GREEN = "&H0047F53B&"
WHITE = "&H00FFFFFF&"

# libass sizes by line height; these tall-metric fonts render caps at ~0.40x (Poppins)
# and ~0.49x (Anton) of the size, so 170 -> ~68px caps, 136 -> ~67px caps on 1920.
CAP_FONT, CAP_SIZE = "Poppins Black", 170
HOOK_FONT, HOOK_SIZE = "Anton", 136
Y_SINGLE = 1235          # caption centre on a single-frame layout (~64% down)
Y_SEAM = OUT_H // 2      # split layout: centred on the panel seam
MAX_WORDS, MAX_CHARS = 3, 14


def _t(sec):
    sec = max(sec, 0)
    cs = int(round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(w):
    w = w.upper().replace("’", "'")
    w = re.sub(r"[^\w'$%?!&@#.,-]", "", w)
    w = re.sub(r"[.,]+$", "", w)          # drop trailing full stops/commas, keep ?!
    return w.replace("{", "").replace("}", "").replace("\\", "")


def paginate(words, max_words=MAX_WORDS, max_chars=MAX_CHARS):
    pages, cur = [], []
    for w in words:
        txt = _clean(w["w"])
        if not txt:
            continue
        item = dict(w, txt=txt)
        if cur:
            gap = w["s"] - cur[-1]["e"]
            chars = sum(len(c["txt"]) for c in cur) + len(cur) + len(txt)
            brk = (len(cur) >= max_words or chars > max_chars or gap > 0.45
                   or re.search(r"[.?!,;:]$", cur[-1]["w"]) or item["emph"] or cur[-1]["emph"])
            if brk:
                pages.append(cur)
                cur = []
        cur.append(item)
    if cur:
        pages.append(cur)
    return pages


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{CF},{CS},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,1,0,1,9,5,5,60,60,0,1
Style: Hook,{HF},{HS},&H00FFFFFF,&H000000FF,&H1A000000,&H00000000,0,0,0,0,100,100,1,0,3,22,0,8,50,50,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _hook_lines(text, max_chars=22):
    toks = []
    for part in re.split(r"(\*[^*]+\*)", text.strip()):
        accent = part.startswith("*") and part.endswith("*")
        for w in part.strip("*").split():
            toks.append((w.upper(), accent))
    lines, cur, n = [], [], 0
    for w, acc in toks:
        if cur and n + 1 + len(w) > max_chars:
            lines.append(cur)
            cur, n = [], 0
        cur.append((w, acc))
        n += len(w) + (1 if n else 0)
    if cur:
        lines.append(cur)
    out = []
    for line in lines:
        out.append(" ".join(f"{{\\c{YELLOW}}}{w}{{\\c{WHITE}}}" if acc else w for w, acc in line))
    return "\\N".join(out)


def build_ass(words, duration, mode_at, hook=None, hook_seconds=3.0):
    """words: output-timeline words with 'emph'; mode_at(t) -> 'single'|'split'|'fit'."""
    ev = []
    hook_end = 0.0
    if hook:
        hook_end = min(hook_seconds, duration)
        # Single frame: top of frame, over headroom. Split: bottom-anchored just above
        # the seam so it sits on the top person's chest, not their face.
        pos = f"\\an2\\pos({OUT_W // 2},{Y_SEAM - 32})" if mode_at(0.05) == "split" \
            else f"\\an8\\pos({OUT_W // 2},{SAFE_TOP + 20})"
        ev.append(f"Dialogue: 5,{_t(0)},{_t(hook_end)},Hook,,0,0,0,,"
                  f"{{{pos}\\fad(0,180)\\fscx94\\fscy94"
                  f"\\t(0,110,\\fscx104\\fscy104)\\t(110,220,\\fscx100\\fscy100)}}{_hook_lines(hook)}")
    pages = paginate(words)
    for pi, page in enumerate(pages):
        p_start = max(page[0]["s"] - 0.04, 0)
        nxt = pages[pi + 1][0]["s"] - 0.04 if pi + 1 < len(pages) else duration
        p_end = min(nxt, page[-1]["e"] + 0.55, duration)
        if p_end - p_start < 0.08:
            p_end = min(p_start + 0.08, duration)
        mid = (p_start + p_end) / 2
        split = mode_at(mid) == "split"
        pos = f"\\an5\\pos({OUT_W // 2},{Y_SEAM if split else Y_SINGLE})"
        if split and hook and p_start < hook_end:
            pos = f"\\an8\\pos({OUT_W // 2},{Y_SEAM + 24})"  # below the seam, under the hook
        for i, w in enumerate(page):
            s = p_start if i == 0 else w["s"]
            e = page[i + 1]["s"] if i + 1 < len(page) else p_end
            if e <= s:
                continue
            parts = []
            for j, x in enumerate(page):
                if x["emph"]:
                    col = YELLOW if j == i else GREEN
                    parts.append(f"{{\\c{col}\\fs{int(CAP_SIZE * 1.22)}}}{x['txt']}{{\\c{WHITE}\\fs{CAP_SIZE}}}")
                elif j == i:
                    parts.append(f"{{\\c{YELLOW}}}{x['txt']}{{\\c{WHITE}}}")
                else:
                    parts.append(x["txt"])
            pop = "\\fscx80\\fscy80\\t(0,70,\\fscx104\\fscy104)\\t(70,140,\\fscx100\\fscy100)" if i == 0 else ""
            ev.append(f"Dialogue: 1,{_t(s)},{_t(e)},Cap,,0,0,0,,"
                      f"{{{pos}{pop}}}{' '.join(parts)}")
    return HEADER.format(W=OUT_W, H=OUT_H, CF=CAP_FONT, CS=CAP_SIZE, HF=HOOK_FONT, HS=HOOK_SIZE) + "\n".join(ev) + "\n"
