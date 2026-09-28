# Vertical shorts

Turns a landscape video into a 9:16 short that is **framed for vertical**, not a
letterboxed or center-cropped copy of the landscape frame.

What it does to the footage:

| Situation in the source | What you get in 9:16 |
| --- | --- |
| One person | A 9:16 window that follows their face, eye line ~40% down. The frame stays locked while they sway and eases into a move when they shift (dead zone + smoothing, planned ahead so it starts a beat early). |
| Two people who fit in one 9:16 window | One window framing both. |
| Two people too far apart (podcast two-shot) | Cuts to whoever is talking when lips clearly match voice (audio-visual sync); otherwise a stacked split screen, one person per 1080x960 panel, each panel slid away from the other person. |
| Three or more | The group if it fits, else the speaker, else the most prominent face. |
| No faces (b-roll, empty room) | Pans to what's salient or moving (spectral-residual saliency + motion). |
| A real cut in the source | A hard cut in the short. Camera paths never smooth across cuts. |

What it does to the edit:

- **Cold open**: segments play in EDL order, so a later punchline can go first.
- **Dead-air removal**: pauses longer than `max_pause` become jump cuts, snapped to word boundaries. Pauses with sound in them (laughs, music hits) are kept.
- **Punch-ins**: every other jump cut zooms in 12% around the face, plus a slow 3.5% push-in within each piece.
- **Captions**: 1 to 3 word pages in Poppins Black with a thick outline. The word being spoken lights up yellow; numbers, money and EDL `emphasis` words get their own bigger green page. Each page pops in. Captions sit clear of the TikTok/Shorts/Reels UI, and in split layout they move to the seam.
- **Hook headline**: a boxed Anton title for the first seconds; `*starred*` words are yellow.
- **Finish**: progress bar, a light contrast/saturation lift, 2-pass loudness normalization to -14 LUFS, and 1080x1920 H.264 High at the source frame rate.

## Setup

```bash
pip install -r requirements.txt
./setup_models.sh          # face detector, face landmarks, VAD, Parakeet ASR, fonts (~700 MB)
```

MediaPipe on headless Linux needs `libegl1 libgles2` (`apt-get install libegl1 libgles2`).
Everything runs offline on CPU after setup.

## Use

```bash
yt-dlp -f "bv*[height<=2160]+ba/b" --merge-output-format mp4 -o source.mp4 "<youtube url>"

python make_short.py transcribe source.mp4      # word-timed transcript, cached as source.mp4.words.json
python make_short.py suggest source.mp4         # shortlist of hook-first 20-55s windows
# write edl.json (below), then:
python make_short.py render source.mp4 edl.json -o short.mp4 --debug
```

`--debug` also writes `short.work/debug.mp4`: the source with the crop windows drawn, next to
the result, which is the quickest way to QA the framing. `short.work/plan_notes.txt` lists the
layout chosen for every shot.

Already have captions? `--captions video.en.vtt` (or `.srt`, YouTube `.json3`) skips local ASR.
`--two-person split|speaker` forces the two-shot behaviour for the whole video.

## EDL

```json
{
  "hook": "He turned down *$10 million*",
  "hook_seconds": 3.0,
  "segments": [
    {"start": 412.3, "end": 416.8, "note": "punchline as cold open"},
    {"start": 371.0, "end": 409.5}
  ],
  "trim_silence": true,
  "max_pause": 0.35,
  "emphasis": ["million", "never"],
  "punch_zoom": 1.12,
  "layout": [
    {"start": 380.0, "end": 386.0, "mode": "split"},
    {"start": 390.0, "end": 395.0, "mode": "single", "target": "left"}
  ]
}
```

Times are source seconds. Segment edges snap outward to whole words. `layout` overrides take
`mode` = `split` | `single` (+ `target` = `left` | `right` | `center` | `largest` | track id) |
`speaker` | `fit`; `fit` shows the whole frame over a blurred fill, which is only worth it
for screen recordings and other text-heavy shots.

## Layout of the code

```
make_short.py          CLI
vshorts/transcribe.py  Parakeet TDT (sherpa-onnx) + Silero VAD -> word timestamps; .srt/.vtt/.json3 readers
vshorts/edit.py        EDL -> frame-exact cuts (word snapping, pause removal, punch-in pattern)
vshorts/analyze.py     shot cuts, YuNet face tracks, lip aperture, speech envelope, saliency
vshorts/reframe.py     layout decisions + camera paths per source frame
vshorts/captions.py    ASS captions and hook
vshorts/render.py      frame compositor, audio splice + loudnorm, x264 encode
vshorts/suggest.py     transcript heuristics for picking moments
vshorts/debug.py       crop-overlay QA video
```
