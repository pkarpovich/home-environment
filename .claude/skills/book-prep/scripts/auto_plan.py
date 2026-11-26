#!/usr/bin/env python3
"""Draft a build plan from the store's own structure; you review it before building.

usage: auto_plan.py <book.epub> <fantlab_work_id> <plan.json>

It nests chapters under parts ("Часть", "Книга", "Том", "Part"), drops service entries (the book
title, notes, annotation), finds the notes documents and the scene-break elements, and fills the
metadata from FantLab. It prints what it decided and what looks off, so the review can start there.
"""
import json
import re
import sys
import zipfile
from pathlib import Path
from posixpath import dirname, join, normpath
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
import fantlab  # noqa: E402 - the sibling script, imported as a module

NCX = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
OPF = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
PART = re.compile(r"^(часть|книга|том|part|book)\b", re.I)
EDGE = re.compile(r"^(пролог|эпилог|послесловие|предисловие|от автора|благодарност|интерлюдия|prologue|epilogue|afterword|foreword|interlude)", re.I)
SERVICE = re.compile(r"^(сноски|примечания|комментарии|аннотация|notes|об авторе|содержание|оглавление|иллюстрации)", re.I)
BREAK_XPATH = (
    "//h:*[(self::h:p or self::h:div or self::h:h1 or self::h:h2 or self::h:h3 or self::h:h4 or self::h:h5 or self::h:h6)"
    " and not(.//h:img) and not(h:p) and not(h:div)"
    " and string-length(normalize-space(.)) > 0 and string-length(normalize-space(.)) < 12"
    " and translate(normalize-space(.), ' *⁂•·~', '') = '']"
)


def ncx_tree(z, base, opf):
    item = opf.find("opf:manifest/opf:item[@media-type='application/x-dtbncx+xml']", OPF)
    ncx = ET.fromstring(z.read(normpath(join(base, item.get("href")))))

    def walk(point):
        label = " ".join((point.find("n:navLabel/n:text", NCX).text or "").split())
        return {"title": label, "target": point.find("n:content", NCX).get("src"),
                "children": [walk(c) for c in point.findall("n:navPoint", NCX)]}

    return [walk(p) for p in ncx.find("n:navMap", NCX).findall("n:navPoint", NCX)]


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item["children"])


def text_of(xml):
    return " ".join(re.sub(r"<[^>]+>", " ", xml).split())


def main():
    src, work_id, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    z = zipfile.ZipFile(src)
    opf_path = re.search(rb'full-path="([^"]+)"', z.read("META-INF/container.xml")).group(1).decode()
    base = dirname(opf_path)
    opf = ET.fromstring(z.read(opf_path))
    manifest = {i.get("id"): i.get("href") for i in opf.find("opf:manifest", OPF)}
    spine = [manifest[r.get("idref")] for r in opf.find("opf:spine", OPF)]
    docs = {h: z.read(normpath(join(base, h))).decode("utf-8", "replace") for h in spine}
    notes = []

    incoming = {h: 0 for h in spine}
    for html in docs.values():
        for target in re.findall(r'<a\b[^>]*href="([^"#]+)#[^"]+"', html):
            if target in incoming:
                incoming[target] += 1
    for h in spine:
        heads = [text_of(x) for x in re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", docs[h], re.S)]
        numeric = sum(1 for x in heads if re.fullmatch(r"\[?\d+\]?", x))
        if incoming[h] >= 3 and (numeric >= 3 or re.search(r"note", h, re.I)):
            notes.append(h)

    w = fantlab.fetch_work(work_id)
    book_title = w["title_ru"]
    flat = [dict(e, children=[]) for e in flatten(ncx_tree(z, base, opf))]
    notes_entries = [e for e in flat if e["target"].split("#")[0] in notes]
    ids = {h: set(re.findall(r'\bid="([^"]+)"', docs[h])) for h in spine}
    retargeted = []
    for e in flat:
        href, _, frag = e["target"].partition("#")
        if frag and frag not in ids.get(href, ()):
            e["target"] = href
            retargeted.append(e["title"])
    kept, dropped = [], []
    for n, e in enumerate(flat):
        is_title = n == 0 and (book_title.lower()[:12] in e["title"].lower() or any(a["ru"].split()[-1] in e["title"] for a in w["authors"]))
        is_break = not re.sub(r"[\s*⁂•·~]", "", e["title"])
        if is_title or is_break or SERVICE.match(e["title"]) or e in notes_entries:
            dropped.append(e["title"])
        else:
            kept.append(e)

    toc, part = [], None
    has_parts = any(PART.match(e["title"]) for e in kept)
    for e in kept:
        if has_parts and PART.match(e["title"]):
            part = dict(e, children=[])
            toc.append(part)
        elif has_parts and EDGE.match(e["title"]):
            part = None if re.match(r"^(эпилог|послесловие|epilogue|afterword)", e["title"], re.I) else part
            (part["children"] if part and not EDGE.match(e["title"]) else toc).append(e)
        elif part is not None:
            part["children"].append(e)
        else:
            toc.append(e)
    if not has_parts:
        toc = [e for e in kept]
        original = ncx_tree(z, base, opf)
        if any(item["children"] for item in original) and len(kept) == len(flat) - len(dropped):
            keep_titles = {(e["title"], e["target"]) for e in kept}

            def prune(items):
                result = []
                for item in items:
                    children = prune(item["children"])
                    if (item["title"], item["target"]) in keep_titles:
                        result.append(dict(item, children=children))
                    else:
                        result.extend(children)
                return result

            toc = prune(original)

    breaks = {}
    for h in spine:
        if h in notes:
            continue
        found = re.findall(r"<(p|div|h[1-6])\b[^>]*>\s*((?:<[^>]+>\s*)*)([\s*⁂•·~]{1,11})\s*((?:</[^>]+>\s*)*)</\1>", docs[h])
        count = sum(1 for f in found if f[2].strip())
        if count:
            breaks[h] = count

    meta_opf = opf.find("opf:metadata", OPF)
    date = (meta_opf.findtext("dc:date", default="", namespaces=OPF) or "")[:4]
    description = " ".join((meta_opf.findtext("dc:description", default="", namespaces=OPF) or "").split())
    subjects = [s.text for s in meta_opf.findall("dc:subject", OPF) if s.text]
    publisher = meta_opf.findtext("dc:publisher", default="", namespaces=OPF)
    cycle = w["cycles"][0] if w["cycles"] else None
    plan = {
        "metadata": {
            "title": book_title, "language": "ru", "date": date, "description": description, "subjects": subjects,
            "publisher": "" if "litres" in publisher.lower() else publisher,
            "authors": [{"name": a["ru"], "file_as": ", ".join(reversed(a["ru"].rsplit(" ", 1)))} for a in w["authors"]],
            "source": w["url"],
        },
        "toc": toc,
        "bodymatter": toc[0]["target"] if toc else spine[1],
        "notes": {"files": notes},
        "chars_per_page": 1800,
    }
    if cycle and cycle.get("position"):
        plan["metadata"]["series"] = {"name": cycle["ru"], "index": cycle["position"]}
    if breaks:
        plan["scene_break_xpath"] = BREAK_XPATH
        plan["scene_toc"] = True
    Path(out).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

    def count(items):
        return sum(1 + count(i.get("children", [])) for i in items)

    print(json.dumps({
        "title": book_title, "orig": w["title_orig"], "authors_orig": [a["orig"] for a in w["authors"]],
        "series": cycle and {"ru": cycle["ru"], "orig": cycle["orig"], "position": cycle["position"]},
        "toc_top": [i["title"] for i in toc][:8], "toc_entries": count(toc), "parts": has_parts,
        "dropped": dropped if len(dropped) < 12 else dropped[:6] + [f"... {len(dropped)} in all"], "retargeted": retargeted, "notes_files": notes, "scene_break_docs": len(breaks), "scene_breaks": sum(breaks.values()),
        "english_editions": w.get("english_editions", []),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
