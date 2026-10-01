# 8 Bebidas y 8 Alimentos Antiinflamatorios (20 min)

Everything for the video lives in `shots.json` (55 shots: code, timing, narration, ChatGPT image prompt, Google Flow prompt). The scripts turn it into prompt sheets, voice files and the final edit.

## Pipeline

```bash
pip install -r requirements.txt
python build_sheets.py                 # -> sheets/ (prompts, narration, checklist)
```

1. **Images (ChatGPT).** Open `sheets/prompts_imagenes.md`. Paste the STYLE PROMPT once at the start of a new chat, then each shot prompt (16:9). Save as `assets/CODE.png` (e.g. `assets/B8-1.png`).
2. **Clips (Google Flow).** Open `sheets/prompts_flow.md`. Upload each image as the first frame, paste its Flow prompt (8 s), download as `assets/CODE.mp4`. Shots without a clip fall back to the still image with a slow zoom.
3. **Voice (Kokoro `em_alex`).** `pip install kokoro soundfile` (+ `espeak-ng` on your system), then `python tts_kokoro.py --out audio` -> `audio/CODE.wav`. (Any TTS works as long as files are named `CODE.wav|mp3`.)
4. **Edit.**
   ```bash
   python assemble.py --placeholders --only I-1,B8-1,B8-2 --res 640x360   # quick preview
   python assemble.py --res 1920x1080 --out final.mp4                      # full video
   ```
   Adds the big countdown number + title on the first shot of each item (then a small badge), holds the last frame with a slow zoom when a clip is shorter than the narration, and writes `final.srt` (subtitles timed to the real audio). Use `--font /path/Font-Bold.ttf` to pick your own font (must include Spanish accents).

## Length warning

The narration is **2,042 words**; the plan targets ~2,860 for 20:00. At normal voice speed 2,042 words is roughly **13-14 minutes**. By default `assemble.py` follows the real audio length (`--pace audio`), so the video will be that long. Options: expand the script by ~800 words, slow the voice (`--speed 0.85`), or force the plan's time slots with `--pace spec` (adds silent gaps — not recommended).

## Notes

- Script wording is hedged ("se asocia con", "puede ayudar") and includes medical-advice disclaimers; keep that for YouTube health policy.
- Typos fixed vs. the original draft: "oxálalos" -> "oxalatos", "colálas" -> "cuélalas", "betalainas" -> "betalaínas".
- The assembler was tested with placeholder cards, a synthetic clip and tone audio. The Kokoro step and Flow/ChatGPT steps are untested here (no network access in the build environment).
