#!/usr/bin/env python3
"""Assemble the final video from per-shot assets.

Folders (file name = shot code from shots.json):
  assets/B8-1.mp4   Google Flow clip   (preferred)
  assets/B8-1.png   ChatGPT image      (used if there is no clip; gets a slow zoom)
  audio/B8-1.wav    narration          (any format ffmpeg reads)

Per shot: the narration length sets the shot length (--pace audio, default) or the
time slot from shots.json is used (--pace spec, pads with silence). If a clip is shorter
than the shot, its last frame is held with a slow zoom. The first shot of each countdown
item gets a big number + title; the rest of the item keeps a small badge.

  python assemble.py --placeholders --only I-1,B8-1     # quick preview with stand-in cards
  python assemble.py --res 1920x1080 --out final.mp4    # full video
Also writes <out>.srt with subtitles timed to the real audio.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
FF = "ffmpeg"
try:
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    pass

KIND_COLOR = {"bebida": (46, 125, 160), "alimento": (86, 140, 60), "intro": (140, 100, 60),
              "transicion": (120, 90, 140), "cierre": (160, 110, 60)}


def sec(ts: str) -> float:
    m, s = ts.split(":")
    return int(m) * 60 + int(s)


def run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffmpeg failed:\n{' '.join(cmd)}\n{r.stderr[-1500:]}")
    return r.stderr


def duration(path: Path) -> float:
    r = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        sys.exit(f"cannot read duration of {path}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def find(folder: Path, code: str, exts: tuple[str, ...]) -> Path | None:
    for e in exts:
        p = folder / f"{code}{e}"
        if p.exists():
            return p
    return None


# ----------------------------------------------------------------------------- text
FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def font(size: int, path: str | None):
    """Pick a bold TrueType font that has Spanish accents (é, ñ, ¿, ¡)."""
    for cand in ([path] if path else FONT_CANDIDATES):
        if cand and Path(cand).exists():
            return ImageFont.truetype(cand, size)
    sys.exit("No bold .ttf font found. Pass --font /path/to/Font-Bold.ttf "
             "(the default Pillow font has no accented characters).")


def overlay_png(item: dict, big: bool, res: tuple[int, int], font_path, out: Path) -> Path:
    w, h = res
    img = Image.new("RGBA", res, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    num = str(item["number"])
    if big:
        fn, ft, fl = font(int(h * 0.42), font_path), font(int(h * 0.075), font_path), font(int(h * 0.04), font_path)
        d.rectangle([0, int(h * 0.62), w, h], fill=(0, 0, 0, 120))
        d.text((int(w * 0.05), int(h * 0.80)), num, font=fn, fill="white", anchor="ls",
               stroke_width=int(h * 0.01), stroke_fill=(0, 0, 0, 255))
        d.text((int(w * 0.30), int(h * 0.74)), item["label"].split()[0].upper(), font=fl,
               fill=(255, 214, 102, 255), anchor="ls")
        d.text((int(w * 0.30), int(h * 0.85)), item["title"], font=ft, fill="white", anchor="ls",
               stroke_width=3, stroke_fill=(0, 0, 0, 255))
    else:
        fn, ft = font(int(h * 0.09), font_path), font(int(h * 0.04), font_path)
        pad = int(h * 0.03)
        label = f"{num}  {item['title']}"
        box = d.textbbox((0, 0), label, font=ft)
        bw = box[2] + int(h * 0.12)
        d.rounded_rectangle([pad, pad, pad + bw, pad + int(h * 0.09)], radius=14, fill=(0, 0, 0, 150))
        d.text((pad + int(h * 0.03), pad + int(h * 0.045)), label, font=ft, fill="white", anchor="lm")
    img.save(out)
    return out


def placeholder(shot: dict, kind: str, res: tuple[int, int], font_path, out: Path) -> Path:
    w, h = res
    img = Image.new("RGB", res, KIND_COLOR.get(kind, (80, 80, 80)))
    d = ImageDraw.Draw(img)
    d.text((w // 2, int(h * 0.38)), shot["code"], font=font(int(h * 0.2), font_path),
           fill="white", anchor="mm")
    words, lines, line = shot["image"].split(), [], ""
    for wd in words:
        if len(line) + len(wd) > 60:
            lines.append(line)
            line = ""
        line += wd + " "
    lines.append(line)
    for i, l in enumerate(lines[:5]):
        d.text((w // 2, int(h * 0.62) + i * int(h * 0.055)), l.strip(),
               font=font(int(h * 0.04), font_path), fill=(255, 255, 255), anchor="mm")
    img.save(out)
    return out


# ----------------------------------------------------------------------------- video
def zoom_segment(img: Path, dur: float, res, fps, out: Path, start_zoom=1.0) -> None:
    w, h = res
    frames = max(1, round(dur * fps))
    rate = 0.12 / frames  # ~12% total zoom over the shot
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{start_zoom}+{rate:.6f}*on':d={frames}:x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},format=yuv420p")
    run([FF, "-y", "-i", str(img), "-vf", vf, "-frames:v", str(frames), "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])


def normalize_clip(clip: Path, res, fps, dur: float, out: Path) -> None:
    w, h = res
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"fps={fps},format=yuv420p")
    run([FF, "-y", "-i", str(clip), "-t", f"{dur:.3f}", "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])


def concat(files: list[Path], out: Path, reencode=False) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{f.resolve()}'\n" for f in files))
    cmd = [FF, "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    cmd += (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"] if reencode else ["-c", "copy"])
    run(cmd + [str(out)])


def build_shot(shot, item, args, res, tmp: Path) -> tuple[Path, float]:
    code = shot["code"]
    audio = find(Path(args.audio), code, (".wav", ".mp3", ".m4a", ".flac", ".ogg"))
    spec = sec(shot["end"]) - sec(shot["start"])
    dur = duration(audio) + args.gap if (audio and args.pace == "audio") else float(spec)

    clip = find(Path(args.assets), code, (".mp4", ".mov", ".webm"))
    img = find(Path(args.assets), code, (".png", ".jpg", ".jpeg", ".webp"))
    parts: list[Path] = []
    if clip:
        cd = min(duration(clip), dur)
        seg = tmp / f"{code}_clip.mp4"
        normalize_clip(clip, res, args.fps, cd, seg)
        parts.append(seg)
        if dur - cd > 0.05:  # hold last frame with slow zoom
            last = tmp / f"{code}_last.png"
            run([FF, "-y", "-sseof", "-0.1", "-i", str(seg), "-frames:v", "1", "-update", "1", str(last)])
            hold = tmp / f"{code}_hold.mp4"
            zoom_segment(last, dur - cd, res, args.fps, hold)
            parts.append(hold)
    else:
        if not img:
            if not args.placeholders:
                sys.exit(f"missing asset for {code} (use --placeholders to preview)")
            img = placeholder(shot, item["kind"], res, args.font, tmp / f"{code}_ph.png")
        seg = tmp / f"{code}_zoom.mp4"
        zoom_segment(img, dur, res, args.fps, seg)
        parts.append(seg)

    video = tmp / f"{code}_v.mp4"
    concat(parts, video) if len(parts) > 1 else video.write_bytes(parts[0].read_bytes())

    # overlays: big number for the first 5 s of the item's first shot, small badge otherwise
    cmd = [FF, "-y", "-i", str(video)]
    first = shot["code"].endswith("-1")
    graph, n = "[0:v]", 1
    if item["number"] is not None:
        if first:
            big = overlay_png(item, True, res, args.font, tmp / f"{code}_big.png")
            cmd += ["-loop", "1", "-i", str(big)]
            graph += f"[{n}:v]overlay=0:0:enable='lt(t,5)'[o{n}];[o{n}]"
            n += 1
        badge = overlay_png(item, False, res, args.font, tmp / f"{code}_badge.png")
        cmd += ["-loop", "1", "-i", str(badge)]
        start = 5 if first else 0
        graph += f"[{n}:v]overlay=0:0:enable='gte(t,{start})'[o{n}];[o{n}]"
        n += 1
    graph += "format=yuv420p[vout]"
    # audio
    if audio:
        cmd += ["-i", str(audio)]
        a_idx = n
        afilter = f"[{a_idx}:a]aresample=44100,apad=pad_dur={args.gap},atrim=0:{dur:.3f}[aout]"
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        a_idx = n
        afilter = f"[{a_idx}:a]atrim=0:{dur:.3f}[aout]"
    out = tmp / f"{code}.mp4"
    cmd += ["-filter_complex", f"{graph};{afilter}", "-map", "[vout]", "-map", "[aout]",
            "-t", f"{dur:.3f}", "-r", str(args.fps), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out)]
    run(cmd)
    return out, dur


def srt_time(t: float) -> str:
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(t % 1 * 1000):03d}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", default="assets")
    ap.add_argument("--audio", default="audio")
    ap.add_argument("--out", default="final.mp4")
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--pace", choices=["audio", "spec"], default="audio")
    ap.add_argument("--gap", type=float, default=0.4, help="seconds of silence after each shot")
    ap.add_argument("--only", default="", help="comma-separated shot codes")
    ap.add_argument("--placeholders", action="store_true", help="stand-in cards for missing assets")
    ap.add_argument("--font", default=None, help="path to a .ttf (e.g. Montserrat-Bold.ttf)")
    args = ap.parse_args()

    res = tuple(int(x) for x in args.res.split("x"))
    data = json.loads((HERE / "shots.json").read_text(encoding="utf-8"))
    only = {c.strip() for c in args.only.split(",") if c.strip()}
    shots = [s for s in data["shots"] if not only or s["code"] in only]

    tmp = Path(tempfile.mkdtemp(prefix="assemble_"))
    done, srt, t = [], [], 0.0
    for i, s in enumerate(shots, 1):
        item = data["items"][s["item"]]
        print(f"[{i}/{len(shots)}] {s['code']}", flush=True)
        f, d = build_shot(s, item, args, res, tmp)
        done.append(f)
        sentences = re.split(r"(?<=[.!?¡¿:])\s+", s["text"])
        total = sum(len(x) for x in sentences) or 1
        cue = t
        for sent in sentences:
            span = (d - args.gap) * len(sent) / total
            srt.append((cue, cue + span, sent))
            cue += span
        t += d

    concat(done, Path(args.out).with_suffix(".tmp.mp4"))
    Path(args.out).with_suffix(".tmp.mp4").replace(args.out)
    Path(args.out).with_suffix(".tmp.txt").unlink(missing_ok=True)
    Path(args.out).with_suffix(".srt").write_text(
        "\n".join(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{x}\n" for n, (a, b, x) in enumerate(srt, 1)),
        encoding="utf-8")
    print(f"done: {args.out} ({int(t // 60)}:{int(t % 60):02d})")


if __name__ == "__main__":
    main()
