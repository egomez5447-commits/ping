#!/usr/bin/env python3
"""Generate one WAV per shot with Kokoro (Spanish voice em_alex).

  pip install kokoro soundfile      # also needs espeak-ng installed on your system
  python tts_kokoro.py --out audio
  python tts_kokoro.py --out audio --only I-1,B8-1 --speed 0.95

Existing files are skipped, so you can re-run safely.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="audio")
ap.add_argument("--voice", default="em_alex")
ap.add_argument("--speed", type=float, default=1.0,
                help="<1 slower. Slower speech also makes the video longer.")
ap.add_argument("--only", default="", help="comma-separated shot codes")
args = ap.parse_args()

data = json.loads((Path(__file__).parent / "shots.json").read_text(encoding="utf-8"))
only = {c.strip() for c in args.only.split(",") if c.strip()}
out = Path(args.out)
out.mkdir(exist_ok=True)

pipe = KPipeline(lang_code="e")  # 'e' = Spanish
for s in data["shots"]:
    if only and s["code"] not in only:
        continue
    target = out / f"{s['code']}.wav"
    if target.exists():
        continue
    chunks = [np.asarray(a) for _, _, a in pipe(s["text"], voice=args.voice, speed=args.speed)]
    sf.write(target, np.concatenate(chunks), 24000)
    print("wrote", target, flush=True)
