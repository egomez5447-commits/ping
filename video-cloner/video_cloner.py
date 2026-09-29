#!/usr/bin/env python3
"""Analyze a whole YouTube video (visuals + audio) so its style can be cloned.

Pipeline:
  1. download   yt-dlp            -> video.mp4
  2. scenes     PySceneDetect     -> scenes.json + one keyframe per scene
  3. transcript faster-whisper    -> transcript.json / transcript.txt
  4. visuals    Claude (vision)   -> per-scene descriptions, style bible,
                                     image-generation prompts

Usage:
  python video_cloner.py "https://youtu.be/1GowFTjbUnk" --out out
  python video_cloner.py path/to/video.mp4 --out out --skip-vision

Each stage caches its output in --out, so re-running resumes where it stopped.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = os.environ.get("CLONER_MODEL", "claude-sonnet-5-5")


def log(msg: str) -> None:
    print(f"[cloner] {msg}", flush=True)


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# --------------------------------------------------------------------------- #
# 1. download
# --------------------------------------------------------------------------- #
def download(source: str, out: Path) -> Path:
    if Path(source).is_file():
        log(f"using local file {source}")
        return Path(source)

    target = out / "video.mp4"
    if target.exists():
        log("video.mp4 already downloaded")
        return target

    import yt_dlp

    log("downloading video (720p max is enough for analysis)...")
    opts = {
        "format": "bv*[height<=720]+ba/b[height<=720]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out / "video.%(ext)s"),
        "ffmpeg_location": ffmpeg_exe(),
        "quiet": True,
        "no_warnings": True,
        "writeinfojson": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([source])
    if not target.exists():
        found = list(out.glob("video.*"))
        found = [f for f in found if f.suffix in {".mp4", ".mkv", ".webm"}]
        if not found:
            sys.exit("download failed: no video file produced")
        return found[0]
    return target


# --------------------------------------------------------------------------- #
# 2. scenes + keyframes
# --------------------------------------------------------------------------- #
def detect_scenes(video: Path, out: Path, threshold: float, min_len: float,
                  max_scenes: int) -> list[dict]:
    scenes_path = out / "scenes.json"
    if scenes_path.exists():
        log("scenes.json cached")
        return json.loads(scenes_path.read_text())

    import cv2
    from scenedetect import ContentDetector, detect

    log("detecting scenes...")
    fps = cv2.VideoCapture(str(video)).get(cv2.CAP_PROP_FPS) or 30.0
    found = detect(str(video), ContentDetector(threshold=threshold,
                                                min_scene_len=int(min_len * fps)))
    cap = cv2.VideoCapture(str(video))
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    cap.release()

    if not found:  # no cuts detected -> treat as fixed-length chunks
        step = 10.0
        bounds = [(t, min(t + step, total)) for t in _frange(0, total, step)]
    else:
        bounds = [(_secs(s), _secs(e)) for s, e in found]

    bounds = _cap_scenes(bounds, max_scenes)
    frames = out / "frames"
    frames.mkdir(exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    scenes = []
    for i, (start, end) in enumerate(bounds, 1):
        mid = start + (end - start) / 2
        cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if w > 960:
            frame = cv2.resize(frame, (960, int(h * 960 / w)))
        name = f"scene_{i:03d}.jpg"
        cv2.imwrite(str(frames / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        scenes.append({"index": i, "start": round(start, 2), "end": round(end, 2),
                       "frame": f"frames/{name}"})
    cap.release()

    scenes_path.write_text(json.dumps(scenes, indent=2))
    log(f"{len(scenes)} scenes")
    return scenes


def _secs(t) -> float:
    return float(t.seconds) if hasattr(t, "seconds") else t.get_seconds()


def _frange(a: float, b: float, step: float):
    while a < b:
        yield a
        a += step


def _cap_scenes(bounds: list[tuple[float, float]], max_scenes: int):
    """Merge the shortest scenes into neighbours until at most max_scenes remain."""
    bounds = list(bounds)
    while len(bounds) > max_scenes:
        i = min(range(len(bounds)), key=lambda k: bounds[k][1] - bounds[k][0])
        j = i - 1 if i > 0 else i + 1
        lo, hi = sorted((i, j))
        bounds[lo] = (bounds[lo][0], bounds[hi][1])
        del bounds[hi]
    return bounds


# --------------------------------------------------------------------------- #
# 3. transcript
# --------------------------------------------------------------------------- #
def transcribe(video: Path, out: Path, model_size: str, language: str | None) -> list[dict]:
    path = out / "transcript.json"
    if path.exists():
        log("transcript.json cached")
        return json.loads(path.read_text())

    from faster_whisper import WhisperModel

    log(f"transcribing with whisper '{model_size}' (first run downloads the model)...")
    audio = out / "audio.wav"
    try:
        subprocess.run([ffmpeg_exe(), "-y", "-i", str(video), "-vn", "-ac", "1",
                        "-ar", "16000", str(audio)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        log("no audio track found; skipping transcript")
        return []
    model = WhisperModel(model_size, compute_type="int8")
    segments, info = model.transcribe(str(audio), language=language, vad_filter=True)
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments]
    audio.unlink(missing_ok=True)

    path.write_text(json.dumps(segs, ensure_ascii=False, indent=2))
    (out / "transcript.txt").write_text(
        "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs), encoding="utf-8")
    log(f"transcript: {len(segs)} segments, language={info.language}")
    return segs


def text_between(segs: list[dict], start: float, end: float) -> str:
    return " ".join(s["text"] for s in segs if start <= s["start"] < end).strip()


# --------------------------------------------------------------------------- #
# 4. vision (Claude)
# --------------------------------------------------------------------------- #
def _img_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": data}}


def _ask(client, model: str, content: list[dict], max_tokens: int = 4096) -> str:
    resp = client.messages.create(model=model, max_tokens=max_tokens,
                                  messages=[{"role": "user", "content": content}])
    return "".join(b.text for b in resp.content if b.type == "text")


def describe_scenes(scenes, segs, out: Path, model: str, batch: int) -> list[dict]:
    path = out / "scene_descriptions.json"
    cache = json.loads(path.read_text()) if path.exists() else {}

    import anthropic

    client = anthropic.Anthropic()
    todo = [s for s in scenes if str(s["index"]) not in cache]
    log(f"describing {len(todo)} scenes with {model} ({len(cache)} cached)...")

    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        content: list[dict] = [{"type": "text", "text": (
            "You are analyzing keyframes of an explainer video to reproduce its visual "
            "style. For EACH numbered frame below, describe precisely: the subject, "
            "characters/props and their drawing style, layout/composition, colors, any "
            "on-screen text (transcribe it exactly, keep original language), and "
            "typography (weight, outline, color). Also say what kind of shot it is "
            "(title card, item card, diagram, list, outro...). Be concrete and terse.\n"
            "Return ONLY a JSON object mapping the frame number (string) to a "
            "description string.")}]
        for s in chunk:
            spoken = text_between(segs, s["start"], s["end"])[:300]
            content.append({"type": "text",
                            "text": f"\nFrame {s['index']} ({fmt_ts(s['start'])}) "
                                    f"narration: {spoken or '(none)'}"})
            content.append(_img_block(out / s["frame"]))
        raw = _ask(client, model, content)
        cache.update(_parse_json(raw))
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
        log(f"  {min(i + batch, len(todo))}/{len(todo)}")

    return [{**s, "visual": cache.get(str(s["index"]), "")} for s in scenes]


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def style_bible(scenes: list[dict], out: Path, model: str) -> str:
    path = out / "style_bible.md"
    if path.exists():
        return path.read_text(encoding="utf-8")

    import anthropic

    client = anthropic.Anthropic()
    step = max(1, len(scenes) // 12)
    sample = scenes[::step][:12]
    notes = "\n".join(f"- {fmt_ts(s['start'])}: {s['visual']}" for s in scenes)
    content: list[dict] = [{"type": "text", "text": (
        "Below are 12 sample frames and per-scene notes from ONE explainer video. Write a "
        "STYLE BIBLE in Markdown that lets an illustrator/AI image tool reproduce the "
        "look exactly for a different topic. Sections: Character design; Line & fill "
        "style; Background; Color palette (hex codes); Typography (fonts to substitute, "
        "weights, outline, color hierarchy); Composition patterns; Recurring shot types "
        "and the video structure (hook -> items -> outro) with typical durations; "
        "Pacing; Thumbnail formula. Finish with one reusable ENGLISH 'style suffix' "
        "paragraph to append to every image-generation prompt.\n\nScene notes:\n" + notes)}]
    content += [_img_block(out / s["frame"]) for s in sample]
    text = _ask(client, model, content, max_tokens=4096)
    path.write_text(text, encoding="utf-8")
    return text


def scene_prompts(scenes: list[dict], bible: str, out: Path, model: str, topic: str,
                  target_lang: str, batch: int = 15) -> None:
    path = out / "prompts.md"
    if path.exists():
        log("prompts.md cached")
        return

    import anthropic

    client = anthropic.Anthropic()
    parts = ["# Scene-by-scene image prompts for the remake\n"]
    for i in range(0, len(scenes), batch):
        chunk = scenes[i:i + batch]
        listing = "\n".join(f"Scene {s['index']} ({fmt_ts(s['start'])}-{fmt_ts(s['end'])}): "
                            f"{s['visual']}" for s in chunk)
        prompt = (
            f"STYLE BIBLE:\n{bible}\n\nORIGINAL SCENES:\n{listing}\n\n"
            f"Write the equivalent scenes for a NEW video in {target_lang} about: {topic}.\n"
            "For each scene output Markdown:\n"
            "### Scene N (mm:ss)\n"
            f"- **On-screen text ({target_lang}):** ...\n"
            "- **Image prompt (English):** full prompt ending with the style suffix.\n"
            "Keep the same shot type, layout and pacing as the original scene, but adapt "
            "the content to the new topic. Do not copy the original's text verbatim.")
        parts.append(_ask(client, model, [{"type": "text", "text": prompt}], 4096))
    path.write_text("\n\n".join(parts), encoding="utf-8")


# --------------------------------------------------------------------------- #
def write_timeline(scenes: list[dict], segs: list[dict], out: Path) -> None:
    lines = ["# Scene timeline\n"]
    for s in scenes:
        lines.append(f"## Scene {s['index']} · {fmt_ts(s['start'])}–{fmt_ts(s['end'])}")
        lines.append(f"![]({s['frame']})\n")
        if s.get("visual"):
            lines.append(f"**Visual:** {s['visual']}\n")
        spoken = text_between(segs, s["start"], s["end"])
        if spoken:
            lines.append(f"**Narration:** {spoken}\n")
    (out / "timeline.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="YouTube URL or local video file")
    ap.add_argument("--out", default="out", help="output directory (default: out)")
    ap.add_argument("--topic", default="9 drinks that do NOT break a fast",
                    help="topic of YOUR remake, used for the prompts")
    ap.add_argument("--target-lang", default="Spanish", help="language of your channel")
    ap.add_argument("--whisper-model", default="small",
                    help="tiny/base/small/medium/large-v3 (default small)")
    ap.add_argument("--audio-lang", default=None,
                    help="force audio language code, e.g. es (default: auto-detect)")
    ap.add_argument("--threshold", type=float, default=27.0,
                    help="scene-cut sensitivity, lower = more scenes (default 27)")
    ap.add_argument("--min-scene", type=float, default=1.5, help="min scene seconds")
    ap.add_argument("--max-scenes", type=int, default=150,
                    help="merge shortest scenes down to this many (controls API cost)")
    ap.add_argument("--batch", type=int, default=8, help="frames per vision request")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Claude model for vision")
    ap.add_argument("--skip-transcript", action="store_true")
    ap.add_argument("--skip-vision", action="store_true",
                    help="only download + scenes + transcript (no API key needed)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if not args.skip_vision and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY (or pass --skip-vision).")

    video = download(args.source, out)
    scenes = detect_scenes(video, out, args.threshold, args.min_scene, args.max_scenes)
    segs = [] if args.skip_transcript else transcribe(video, out, args.whisper_model,
                                                      args.audio_lang)

    if args.skip_vision:
        write_timeline(scenes, segs, out)
        log(f"done -> {out}/timeline.md")
        return

    scenes = describe_scenes(scenes, segs, out, args.model, args.batch)
    write_timeline(scenes, segs, out)
    bible = style_bible(scenes, out, args.model)
    scene_prompts(scenes, bible, out, args.model, args.topic, args.target_lang)
    log(f"done. Open {out}/style_bible.md, timeline.md and prompts.md")


if __name__ == "__main__":
    main()
