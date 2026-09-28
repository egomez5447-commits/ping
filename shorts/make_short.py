#!/usr/bin/env python3
"""Turn a landscape video into a vertical (9:16) short that is framed for vertical.

  python make_short.py transcribe SRC.mp4                 # word-timed transcript (cached)
  python make_short.py suggest    SRC.mp4 [--min 20 --max 55]
  python make_short.py render     SRC.mp4 EDL.json -o short.mp4 [--debug]

See README.md for the EDL format and how each layout is chosen.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vshorts import captions, edit, media, reframe, render, suggest, transcribe  # noqa: E402
from vshorts.analyze import analyze_range  # noqa: E402


def log(msg):
    print(msg, flush=True)


def cmd_transcribe(a):
    words = transcribe.get_words(a.src, a.words, a.captions, log)
    for s in suggest.sentences(words):
        print(f"[{s[0]['s']:7.2f} - {s[-1]['e']:7.2f}] {' '.join(w['w'] for w in s)}")


def cmd_suggest(a):
    words = transcribe.get_words(a.src, a.words, a.captions, log)
    for i, c in enumerate(suggest.suggest(words, a.min, a.max, a.top)):
        print(f"#{i + 1} score {c['score']:5.1f}  {c['start']:.2f}-{c['end']:.2f}s "
              f"({c['end'] - c['start']:.0f}s)\n    {c['text']}\n")


def cmd_render(a):
    t0 = time.time()
    info = media.probe(a.src)
    log(f"source: {info.width}x{info.height} @ {float(info.fps):.3f} fps, {info.duration:.1f}s")
    edl = edit.load_edl(a.edl)
    out = Path(a.out)
    work = Path(a.workdir) if a.workdir else out.with_suffix(".work")
    work.mkdir(parents=True, exist_ok=True)
    words = transcribe.get_words(a.src, a.words, a.captions, log)
    log(f"transcript: {len(words)} words")

    def audio16(s, e):
        return transcribe._load_audio_16k(a.src, s, e)

    cuts = edit.build_cuts(edl, words, info, audio16 if info.has_audio else None, log)
    if not cuts:
        raise SystemExit("EDL produced no footage")
    fps = info.fps_f
    plans = {}
    for seg in sorted({c.seg for c in cuts}):
        sc = [c for c in cuts if c.seg == seg]
        f0, f1 = sc[0].src_f0, sc[-1].src_f1
        log(f"segment {seg}: {f0 / fps:.2f}-{f1 / fps:.2f}s")
        an = analyze_range(info, f0, f1, log, work)
        plans[seg] = reframe.plan_range(an, info, words, edl.get("layout"), a.two_person, log)
    # Layout per output frame, for caption placement.
    modes = []
    names = {reframe.SINGLE: "single", reframe.SPLIT: "split", reframe.FIT: "fit"}
    for c in cuts:
        p = plans[c.seg]
        modes += [names[int(p.mode[p.idx(f)])] for f in range(c.src_f0, c.src_f1)]

    def mode_at(t):
        return modes[min(max(int(t * fps), 0), len(modes) - 1)]

    ow = edit.out_words(cuts, words, fps, edl.get("emphasis", ()))
    dur = len(modes) / fps
    ass = captions.build_ass(ow, dur, mode_at, edl.get("hook"), float(edl.get("hook_seconds", 3.0)))
    (work / "captions.ass").write_text(ass)
    (work / "cuts.json").write_text(json.dumps([c.__dict__ for c in cuts], indent=1))
    (work / "plan_notes.txt").write_text("\n".join(n for p in plans.values() for n in p.notes))
    render.render(info, cuts, plans, work / "captions.ass", work, out, not a.no_grade, log)
    if a.debug:
        from vshorts.debug import debug_video
        debug_video(info, cuts, plans, out, work / "debug.mp4", log)
    log(f"done in {time.time() - t0:.0f}s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("transcribe", "suggest", "render"):
        p = sub.add_parser(name)
        p.add_argument("src")
        if name == "render":
            p.add_argument("edl")
            p.add_argument("-o", "--out", required=True)
            p.add_argument("--workdir")
            p.add_argument("--two-person", choices=["auto", "split", "speaker"], default="auto",
                           help="two people too far apart for one crop: cut to whoever talks, or split")
            p.add_argument("--no-grade", action="store_true", help="skip the light contrast/saturation lift")
            p.add_argument("--debug", action="store_true", help="also write a crop-overlay QA video")
        if name == "suggest":
            p.add_argument("--min", type=float, default=20)
            p.add_argument("--max", type=float, default=55)
            p.add_argument("--top", type=int, default=8)
        p.add_argument("--words", help="word-timestamp cache (default SRC.words.json)")
        p.add_argument("--captions", help="use an existing .srt/.vtt/.json3 instead of local ASR")
    a = ap.parse_args()
    {"transcribe": cmd_transcribe, "suggest": cmd_suggest, "render": cmd_render}[a.cmd](a)


if __name__ == "__main__":
    main()
