#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["mutagen>=1.47"]
# ///
"""Join an audiobook's parts into one m4b with all chapters, tags and a square cover. No re-encoding.

usage: build_m4b.py <meta.json> <cover.jpg> <out.m4b> <part1.m4b> [<part2.m4b> ...]

meta.json:
{
  "title": "Иллюзия", "author": "Хью Хауи", "narrator": "Станислав Федорчук", "year": "2024",
  "description": "...", "genre": "Фантастика", "publisher": "ЛитРес", "language": "rus",
  "series": "Укрытие", "series_index": 1,
  "chapter_titles": ["Глава 1", ...]        (optional; replaces every title, the count must match)
}

Parts are joined with ffmpeg's concat demuxer and stream copy, so the audio is bit for bit the same.
Each part's chapters move to its offset on the joined timeline. Generic titles ("Chapter  01") become
"Глава 1" for a Russian book. Tags follow what Audiobookshelf, BookOrbit, Plex and Prologue read:
album = title, album artist and artist = author, composer = narrator, series and series-part as
freeform atoms, ©mvn/©mvi for Apple's players, stik 2 marks it an audiobook.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

GENERIC = re.compile(r"^\s*(?:chapter|глава|track|part|часть)?\s*0*(\d+)\s*$", re.I)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_chapters", str(path)],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def main():
    meta_path, cover, out, *parts = sys.argv[1:]
    meta = json.load(open(meta_path, encoding="utf-8"))
    offset, chapters, total = 0.0, [], 0.0
    for part in parts:
        p = probe(part)
        duration = float(p["format"]["duration"])
        for c in p.get("chapters", []):
            title = (c.get("tags") or {}).get("title", "").strip()
            chapters.append([offset + float(c["start_time"]), offset + float(c["end_time"]), title])
        if not p.get("chapters"):
            chapters.append([offset, offset + duration, ""])
        offset += duration
        total += duration
    if meta.get("chapter_titles"):
        if len(meta["chapter_titles"]) != len(chapters):
            sys.exit(f"chapter_titles has {len(meta['chapter_titles'])} entries, the parts have {len(chapters)} chapters")
        for c, title in zip(chapters, meta["chapter_titles"]):
            c[2] = title
    for n, c in enumerate(chapters, 1):
        m = GENERIC.match(c[2])
        if not c[2] or m:
            c[2] = f"Глава {int(m.group(1)) if m else n}" if meta.get("language", "rus") == "rus" else f"Chapter {int(m.group(1)) if m else n}"
    chapters[-1][1] = total

    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{Path(p).resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in parts))
        ffmeta = Path(tmp) / "chapters.txt"
        lines = [";FFMETADATA1"]
        for start, end, title in chapters:
            safe = re.sub(r"([=;#\\\n])", r"\\\1", title)
            lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start * 1000)}", f"END={int(end * 1000)}", f"title={safe}"]
        ffmeta.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(ffmeta),
                        "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1", "-c", "copy",
                        "-metadata:s:a:0", f"language={meta.get('language', 'rus')}", "-movflags", "+faststart", "-f", "mp4", out], check=True)

    tags = MP4(out)
    tags.delete()
    tags = MP4(out)
    tags.add_tags() if tags.tags is None else None
    t = tags.tags
    t["\xa9nam"] = [meta["title"]]
    t["\xa9alb"] = [meta["title"]]
    t["\xa9ART"] = [meta["author"]]
    t["aART"] = [meta["author"]]
    if meta.get("narrator"):
        t["\xa9wrt"] = [meta["narrator"]]
    if meta.get("year"):
        t["\xa9day"] = [str(meta["year"])]
    if meta.get("genre"):
        t["\xa9gen"] = [meta["genre"]]
    if meta.get("description"):
        t["desc"] = [meta["description"][:255]]
        t["ldes"] = [meta["description"]]
        t["\xa9cmt"] = [meta["description"]]
    t["stik"] = [2]
    freeform = {"publisher": meta.get("publisher"), "language": meta.get("language", "rus")}
    if meta.get("series"):
        t["\xa9mvn"] = [meta["series"]]
        t["\xa9mvi"] = [int(float(meta["series_index"]))]
        t["shwm"] = [1]
        freeform.update({"series": meta["series"], "series-part": f"{meta['series_index']:g}" if isinstance(meta["series_index"], float) else str(meta["series_index"])})
    for key, value in freeform.items():
        if value:
            t[f"----:com.apple.iTunes:{key}"] = [MP4FreeForm(str(value).encode("utf-8"))]
    t["covr"] = [MP4Cover(Path(cover).read_bytes(), imageformat=MP4Cover.FORMAT_JPEG)]
    tags.save()

    check = probe(out)
    print(json.dumps({"out": out, "parts": len(parts), "chapters": len(check.get("chapters", [])), "expected_chapters": len(chapters),
                      "duration_h": round(float(check["format"]["duration"]) / 3600, 2), "parts_h": round(total / 3600, 2),
                      "first_chapters": [c[2] for c in chapters[:3]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
