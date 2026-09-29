# video-cloner

Analyzes a whole YouTube video (scenes, narration, visual style) so you can remake its look for another channel/language.

## Setup (once)

```bash
cd video-cloner
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # Windows: set ANTHROPIC_API_KEY=...
```

ffmpeg is bundled through `imageio-ffmpeg`; nothing else to install.

## Run

```bash
python video_cloner.py "https://youtu.be/1GowFTjbUnk" --out out \
  --topic "9 bebidas que no rompen el ayuno" --target-lang Spanish
```

A ~22 min video with the defaults takes roughly 10-20 min (whisper on CPU is the slow part) and uses about 20-25 vision requests. Lower `--max-scenes` to cut API cost; use `--whisper-model base` for faster transcription.

Re-running resumes from cached files in `--out`. To redo a stage, delete its file (`scenes.json`, `transcript.json`, `scene_descriptions.json`, `style_bible.md`, `prompts.md`).

No API key yet? Run `--skip-vision` to only get the download, scene keyframes and transcript.

## Output (`out/`)

| File | What it is |
|---|---|
| `video.mp4` | Downloaded video (720p max) |
| `frames/` | One keyframe per scene |
| `transcript.txt` / `.json` | Timestamped narration |
| `timeline.md` | Every scene: keyframe + visual description + narration |
| `style_bible.md` | Character design, palette (hex), typography, composition, video structure, thumbnail formula, reusable style-suffix prompt |
| `prompts.md` | Per-scene on-screen text (target language) + image prompts for your remake |

Then send `style_bible.md`, `timeline.md` and `transcript.txt` back to Claude to write the remake script and refine the prompts.

## Notes

- Use the output to recreate the *style* and structure with your own script, wording and artwork. Don't reuse the original's exact text, images or audio.
- Verify health claims (e.g. what does or doesn't break a fast) before publishing them.
- Model defaults to `claude-sonnet-5-5`; override with `--model` or `CLONER_MODEL`.
