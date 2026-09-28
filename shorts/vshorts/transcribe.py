"""Offline speech-to-text with word timestamps (NVIDIA Parakeet TDT via sherpa-onnx).

Also reads existing caption files (.json words, .srt, .vtt, YouTube .json3) so a
transcript from elsewhere can stand in for local ASR.
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from . import config
from .media import FF

SR = 16000


def _load_audio_16k(path, t0=None, t1=None) -> np.ndarray:
    cmd = [FF, "-v", "error", "-nostdin"]
    if t0 is not None:
        cmd += ["-ss", f"{t0:.3f}"]
    if t1 is not None:
        cmd += ["-t", f"{t1 - (t0 or 0):.3f}"]
    cmd += ["-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)


def _speech_segments(audio: np.ndarray):
    import sherpa_onnx

    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(config.SILERO_VAD)
    cfg.silero_vad.min_silence_duration = 0.3
    cfg.silero_vad.min_speech_duration = 0.2
    cfg.silero_vad.max_speech_duration = 25
    cfg.silero_vad.threshold = 0.4
    cfg.sample_rate = SR
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
    win = cfg.silero_vad.window_size
    segs = []

    def drain():
        while not vad.empty():
            segs.append((vad.front.start, len(vad.front.samples)))
            vad.pop()

    for i in range(0, len(audio), win):
        vad.accept_waveform(audio[i:i + win])
        drain()
    vad.flush()
    drain()
    return segs


def _recognizer():
    import sherpa_onnx

    m = config.PARAKEET
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(m / "encoder.int8.onnx"), decoder=str(m / "decoder.int8.onnx"),
        joiner=str(m / "joiner.int8.onnx"), tokens=str(m / "tokens.txt"),
        num_threads=4, model_type="nemo_transducer", decoding_method="greedy_search")


def _tokens_to_words(tokens, starts, durs, offset):
    words = []
    for tok, ts, du in zip(tokens, starts, durs):
        if not tok:
            continue
        end = ts + max(du, 0.04)
        if tok.startswith(" ") or not words:
            words.append({"w": tok.strip(), "s": ts + offset, "e": end + offset})
        else:
            words[-1]["w"] += tok
            words[-1]["e"] = max(words[-1]["e"], end + offset)
    return [w for w in words if w["w"]]


def transcribe(path, t0=None, t1=None, log=print):
    """Return [{"w": word, "s": start_sec, "e": end_sec}] in source time."""
    audio = _load_audio_16k(path, t0, t1)
    base = t0 or 0.0
    if len(audio) == 0:
        return []
    segs = _speech_segments(audio)
    log(f"  asr: {len(segs)} speech regions, {len(audio) / SR:.0f}s audio")
    rec = _recognizer()
    pad = int(0.25 * SR)
    words = []
    for b in range(0, len(segs), 8):
        batch = segs[b:b + 8]
        streams, offs = [], []
        for start, n in batch:
            a0, a1 = max(0, start - pad), min(len(audio), start + n + pad)
            s = rec.create_stream()
            s.accept_waveform(SR, audio[a0:a1])
            streams.append(s)
            offs.append(a0 / SR)
        rec.decode_streams(streams)
        for s, off in zip(streams, offs):
            r = s.result
            durs = list(r.durations) if len(r.durations) == len(r.tokens) else [0.08] * len(r.tokens)
            words += _tokens_to_words(r.tokens, r.timestamps, durs, base + off)
    words.sort(key=lambda w: w["s"])
    for a, b in zip(words, words[1:]):  # no overlaps; padded chunks can double-hear edges
        a["e"] = min(a["e"], max(b["s"], a["s"] + 0.04))
    dedup = []
    for w in words:
        if dedup and w["w"] == dedup[-1]["w"] and w["s"] - dedup[-1]["s"] < 0.15:
            continue
        dedup.append(w)
    return [{"w": w["w"], "s": round(w["s"], 3), "e": round(w["e"], 3)} for w in dedup]


# ---------------------------------------------------------------- caption files

def _ts(s: str) -> float:
    s = s.strip().replace(",", ".")
    parts = [float(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _spread(text, s, e):
    """Distribute a cue's words over its span, weighted by length."""
    toks = text.split()
    if not toks:
        return []
    weights = np.array([len(t) + 2 for t in toks], float)
    edges = s + (e - s) * np.concatenate([[0], np.cumsum(weights) / weights.sum()])
    return [{"w": t, "s": round(edges[i], 3), "e": round(edges[i + 1], 3)} for i, t in enumerate(toks)]


def load_words(path):
    """Load words from our .json, YouTube .json3, .srt or .vtt."""
    p = Path(path)
    txt = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix == ".json" or p.suffix == ".json3":
        data = json.loads(txt)
        if isinstance(data, list):
            return data
        words = []  # YouTube json3: events[].segs[] with tOffsetMs word offsets
        for ev in data.get("events", []):
            if "segs" not in ev:
                continue
            t0 = ev.get("tStartMs", 0) / 1000
            dur = ev.get("dDurationMs", 0) / 1000
            segs = [sg for sg in ev["segs"] if sg.get("utf8", "").strip()]
            for i, sg in enumerate(segs):
                s = t0 + sg.get("tOffsetMs", 0) / 1000
                nxt = t0 + segs[i + 1].get("tOffsetMs", 0) / 1000 if i + 1 < len(segs) else t0 + dur
                for w in _spread(sg["utf8"].strip(), s, max(nxt, s + 0.1)):
                    words.append(w)
        return words
    cues = re.findall(r"([\d:.,]+)\s*-->\s*([\d:.,]+)[^\n]*\n(.*?)(?:\n\s*\n|\Z)", txt, re.S)
    words, last_end = [], -1
    for a, b, body in cues:
        body = re.sub(r"<[^>]+>", "", body)
        body = " ".join(line.strip() for line in body.splitlines() if line.strip())
        s, e = _ts(a), _ts(b)
        if s < last_end - 0.01:  # rolling auto-captions repeat the previous line
            continue
        words += _spread(body, s, e)
        last_end = e
    return words


def get_words(src, cache=None, captions=None, log=print):
    if captions:
        return load_words(captions)
    cache = Path(cache) if cache else Path(str(src) + ".words.json")
    if cache.exists():
        return json.loads(cache.read_text())
    log("transcribing (Parakeet TDT, offline)...")
    words = transcribe(src, log=log)
    cache.write_text(json.dumps(words))
    return words
