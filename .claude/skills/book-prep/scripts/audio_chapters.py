#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["mutagen>=1.47"]
# ///
"""Name an m4b's chapters after its book's EPUB table of contents.

usage: audio_chapters.py <book.m4b> <book.epub> [--write]

Only for an m4b whose chapters are generic ("Глава N"); real titles from the audio stay. The EPUB nav gives parts,
chapters and scene sub-entries: scenes and service pages (annotation, acknowledgements, translator's notes) are
dropped, and a part's name goes in front of its first chapter. When the counts match, each chapter's share of the
text must track its track's share of the time (correlation >= 0.9). When they differ by a few, the entries are
aligned to the tracks by those shares, allowing two chapters in one track or one chapter over two tracks; the
result is used only at correlation >= 0.97. Otherwise nothing changes. Stream copy, tags and cover kept.
"""
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from mutagen.mp4 import MP4

PART = re.compile(r"^(часть|книга|том|part|book)\b", re.I)
SCENE = re.compile(r"^\d+\.\d+$")
SERVICE = re.compile(r"^(annotation|аннотация|благодарност|предисловие переводчика|действующие лица|от переводчика|послесловие|хронолог|об авторе|примечания|сноски|содержание)", re.I)


def toc(epub):
    """Chapter-level entries with the share of the book's text each one covers."""
    z = zipfile.ZipFile(epub)
    opf_path = re.search(rb'full-path="([^"]+)"', z.read("META-INF/container.xml")).group(1).decode()
    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    opf = z.read(opf_path).decode()
    manifest = dict(re.findall(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf))
    manifest.update({i: h for h, i in re.findall(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
    spine = [manifest[i] for i in re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)]
    docs = {h: z.read(base + h).decode("utf-8", "replace") for h in spine}
    nav = next(n for n in z.namelist() if n.endswith("nav.xhtml"))
    nav_dir = nav.rsplit("/", 1)[0] + "/" if "/" in nav else ""
    body = z.read(nav).decode().split('epub:type="toc"')[1].split("</nav>")[0]
    entries = []
    for href, label in re.findall(r'<li[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        label = re.sub(r"<[^>]+>|\s+", " ", label).strip()
        doc, _, frag = (nav_dir + href).removeprefix(base).partition("#")
        entries.append((label, doc, frag))
    def position(doc, frag):
        offset = sum(len(docs[d]) for d in spine[:spine.index(doc)]) if doc in spine else 0
        if frag and doc in docs:
            m = re.search(r'\bid="' + re.escape(frag) + '"', docs[doc])
            offset += m.start() if m else 0
        return offset
    full = "".join(docs[d] for d in spine)
    starts = []
    titles, part = [], None
    for label, doc, frag in entries:
        if SCENE.match(label):
            continue
        if PART.match(label) or re.match(r"^(первая|вторая|третья) смена", label, re.I):
            part = label
            continue
        if SERVICE.match(label):
            continue
        name = f"Глава {label}" if label.isdigit() else label
        titles.append(f"{part}. {name}" if part else name)
        starts.append(position(doc, frag))
        part = None
    ends = starts[1:] + [len(full)]
    sizes = [len(re.sub(r"<[^>]+>", "", full[a:b])) for a, b in zip(starts, ends)]
    return titles, sizes


def chapters(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", str(path)], capture_output=True, text=True, check=True)
    return [(float(c["start_time"]), float(c["end_time"]), (c.get("tags") or {}).get("title", "")) for c in json.loads(out.stdout)["chapters"]]


def retitle(path, spans, titles):
    with tempfile.TemporaryDirectory() as tmp:
        ffmeta = Path(tmp) / "chapters.txt"
        lines = [";FFMETADATA1"]
        for (start, end, _), title in zip(spans, titles):
            lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(start * 1000)}", f"END={round(end * 1000)}", "title=" + re.sub(r"([=;#\\\n])", r"\\\1", title)]
        ffmeta.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = Path(tmp) / path.name
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-i", str(ffmeta), "-map", "0:a", "-map_chapters", "1", "-map_metadata", "1",
                        "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(out)], check=True)
        old, new = MP4(path), MP4(out)
        new.tags = old.tags
        new.save()
        out.replace(path)


def align(sizes, durations, titles):
    """Map book entries onto audio tracks: 1:1, two entries in one track, or one entry over two tracks.

    Minimises the squared difference between each group's share of the text and of the audio time,
    with a small penalty on every non 1:1 step so a plain match wins when it exists."""
    text = [x / sum(sizes) for x in sizes]
    audio = [d / sum(durations) for d in durations]
    n, m, inf = len(text), len(audio), float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if cost[i][j] == inf:
                continue
            for di, dj, pen in ((1, 1, 0.0), (2, 1, 2e-5), (1, 2, 2e-5)):
                if i + di <= n and j + dj <= m:
                    c = cost[i][j] + (sum(text[i:i + di]) - sum(audio[j:j + dj])) ** 2 + pen
                    if c < cost[i + di][j + dj]:
                        cost[i + di][j + dj] = c
                        back[i + di][j + dj] = (i, j, di, dj)
    if cost[n][m] == inf:
        return None, 0.0, 0
    names, groups_t, groups_a, odd = [], [], [], 0
    i, j = n, m
    steps = []
    while (i, j) != (0, 0):
        pi, pj, di, dj = back[i][j]
        steps.append((pi, pj, di, dj))
        i, j = pi, pj
    for pi, pj, di, dj in reversed(steps):
        odd += (di, dj) != (1, 1)
        if dj == 1:
            names.append(" / ".join(titles[pi:pi + di]))
        else:
            names += [titles[pi], titles[pi] + " (продолжение)"]
        groups_t += [sum(text[pi:pi + di])] * dj
        groups_a += audio[pj:pj + dj] if dj == 2 else [sum(audio[pj:pj + dj])]
    if len(groups_t) != len(groups_a):
        groups_t = [sum(text[pi:pi + di]) for pi, pj, di, dj in reversed(steps) for _ in range(1)]
        groups_a = [sum(audio[pj:pj + dj]) for pi, pj, di, dj in reversed(steps)]
    mt, ma = sum(groups_t) / len(groups_t), sum(groups_a) / len(groups_a)
    cov = sum((a - mt) * (b - ma) for a, b in zip(groups_t, groups_a))
    var = (sum((a - mt) ** 2 for a in groups_t) * sum((b - ma) ** 2 for b in groups_a)) ** 0.5
    return names, (cov / var if var else 0.0), odd


def main():
    built, epub, write = Path(sys.argv[1]), Path(sys.argv[2]), "--write" in sys.argv
    spans = chapters(built)
    titles, sizes = toc(epub)
    row = {"audio": len(spans), "book": len(titles)}
    if not all(re.fullmatch(r"Глава \d+", t) for _, _, t in spans):
        row["action"] = "keep: the audio has real titles"
    elif len(titles) == len(spans):
        row["corr"] = round(correlation([x / sum(sizes) for x in sizes], [(e - s) for s, e, _ in spans]), 3)
        row["action"] = "rename" if row["corr"] >= 0.9 else "keep Глава N"
    elif abs(len(titles) - len(spans)) <= 8:
        names, corr, odd = align(sizes, [e - s for s, e, _ in spans], titles)
        row.update({"corr": round(corr, 3), "merged_or_split": odd})
        if names and len(names) == len(spans) and corr >= 0.97 and odd <= max(3, len(spans) // 20):
            row["action"], titles = "rename (aligned)", names
        else:
            row["action"] = "keep Глава N"
    else:
        row["action"] = "keep Глава N"
    if write and row["action"].startswith("rename"):
        retitle(built, spans, titles)
    row["first"], row["last"] = titles[:3], titles[-2:]
    print(json.dumps(row, ensure_ascii=False))


def correlation(a, b):
    a = [x / sum(a) for x in a]
    b = [x / sum(b) for x in b]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    var = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return cov / var if var else 0.0


if __name__ == "__main__":
    main()
