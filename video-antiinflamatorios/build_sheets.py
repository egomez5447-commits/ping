#!/usr/bin/env python3
"""Generate copy-paste prompt sheets, narration files and a checklist from shots.json.

  python build_sheets.py            # writes ./sheets/
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
data = json.loads((HERE / "shots.json").read_text(encoding="utf-8"))
out = HERE / "sheets"
(out / "narration").mkdir(parents=True, exist_ok=True)


def heading(item_id: str) -> str:
    it = data["items"][item_id]
    return f"{it['label']}: {it['title']}" if it["title"] else it["label"]


# 1. ChatGPT image prompts (style prompt first, then one prompt per shot) -------------
lines = ["# Prompts de imagen (ChatGPT)\n",
         "1. Abre un chat NUEVO y pega primero el PROMPT DE ESTILO.",
         "2. Luego pega cada prompt de imagen (pide formato horizontal 16:9).",
         "3. Guarda cada imagen con su código exacto (ej. `B8-1.png`).\n",
         "## PROMPT DE ESTILO\n", f"```\n{data['style_prompt']}\n```\n"]
cur = None
for s in data["shots"]:
    if s["item"] != cur:
        cur = s["item"]
        lines.append(f"\n## {heading(cur)}\n")
    lines.append(f"**{s['code']}**\n```\n{s['image']}\n```")
(out / "prompts_imagenes.md").write_text("\n".join(lines), encoding="utf-8")

# 2. Google Flow prompts ---------------------------------------------------------------
lines = ["# Prompts de Google Flow (clips de 8 s)\n",
         "Sube la imagen con el mismo código como fotograma inicial, pega el prompt y descarga el clip como `CODIGO.mp4`.\n"]
cur = None
for s in data["shots"]:
    if s["item"] != cur:
        cur = s["item"]
        lines.append(f"\n## {heading(cur)}\n")
    lines.append(f"- **{s['code']}**: {s['flow']}")
(out / "prompts_flow.md").write_text("\n".join(lines), encoding="utf-8")

# 3. Narration (one file per shot + full script) -----------------------------------------
full = []
cur = None
for s in data["shots"]:
    (out / "narration" / f"{s['code']}.txt").write_text(s["text"], encoding="utf-8")
    if s["item"] != cur:
        cur = s["item"]
        full.append(f"\n=== {heading(cur)} ===\n")
    full.append(f"[{s['code']} · {s['start']}-{s['end']}]\n{s['text']}\n")
(out / "guion_locucion.txt").write_text("\n".join(full), encoding="utf-8")

# 4. Checklist ------------------------------------------------------------------------
with open(out / "checklist.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["codigo", "bloque", "inicio", "fin", "palabras", "imagen", "clip_flow", "voz"])
    for s in data["shots"]:
        w.writerow([s["code"], heading(s["item"]), s["start"], s["end"],
                    len(s["text"].split()), "", "", ""])

words = sum(len(s["text"].split()) for s in data["shots"])
print(f"{len(data['shots'])} shots, {words} words -> {out}")
