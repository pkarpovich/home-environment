#!/usr/bin/env python3
"""Print what a book is made of, so the plan for build_epub.py can be written from facts.

usage: inspect_epub.py <book.epub> [--file <name>]   (--file dumps one content document as text)
"""
import collections
import re
import sys
import zipfile
from posixpath import dirname, join, normpath
from xml.etree import ElementTree as ET

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
BREAK_TEXT = re.compile(r"^[\s*•·⁂~#=_—–-]{1,15}$")


def text_of(xml):
    xml = re.sub(r"<(script|style)\b.*?</\1>", "", xml, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml)).strip()


def image_size(data):
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + length
    if data[:4] == b"\x89PNG":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def main():
    path = sys.argv[1]
    only = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--file" else None
    z = zipfile.ZipFile(path)
    opf_path = re.search(rb'full-path="([^"]+)"', z.read("META-INF/container.xml")).group(1).decode()
    base = dirname(opf_path)
    opf = ET.fromstring(z.read(opf_path))
    manifest = {i.get("id"): i for i in opf.find("opf:manifest", NS)}
    spine = [manifest[r.get("idref")].get("href") for r in opf.find("opf:spine", NS)]

    if only:
        print(text_of(z.read(normpath(join(base, only))).decode("utf-8", "replace")))
        return

    print("== package", opf_path, "version", opf.get("version"))
    for el in opf.find("opf:metadata", NS):
        tag = el.tag.split("}")[1]
        attrs = {k.split("}")[-1]: v for k, v in el.attrib.items()}
        print(f"  {tag:12} {attrs or ''} {(el.text or '').strip()[:80]}")

    docs = {h: z.read(normpath(join(base, h))).decode("utf-8", "replace") for h in spine}
    link_targets = collections.Counter()
    for html in docs.values():
        for href in re.findall(r'<a\b[^>]*href="([^"#]*)#[^"]+"', html):
            if href:
                link_targets[href] += 1

    print("\n== spine (file, chars, headings, scene-break candidates, links in)")
    classes = collections.Counter()
    for h in spine:
        html = docs[h]
        classes.update(c for c in re.findall(r'class="([^"]+)"', html))
        heads = [f"{m[0]}:{text_of(m[1])[:50]}" for m in re.findall(r"<(h[1-6])\b[^>]*>(.*?)</\1>", html, re.S)]
        breaks = [text_of(b) for b in re.findall(r"<(?:p|div)\b[^>]*>(.*?)</(?:p|div)>", html, re.S) if BREAK_TEXT.match(text_of(b) or "x")]
        breaks += ["<hr>"] * len(re.findall(r"<hr\b", html))
        print(f"  {h:28} {len(text_of(html)):>7}  {heads[:4]}  breaks={collections.Counter(breaks).most_common(3)}  in={link_targets.get(h, 0)}")

    print("\n== most used classes", classes.most_common(15))
    note_files = [h for h, n in link_targets.most_common() if n > 3]
    print("== files many links point into (note candidates)", note_files[:5])
    sample = re.search(r".{0,80}<a\b[^>]*href=\"[^\"]+#[^\"]+\"[^>]*>.{0,60}", "".join(docs.values()), re.S)
    if sample:
        print("== first internal link:", re.sub(r"\s+", " ", sample.group(0)))

    print("\n== images")
    for item in manifest.values():
        if item.get("media-type", "").startswith("image/"):
            data = z.read(normpath(join(base, item.get("href"))))
            print(f"  {item.get('href'):30} {image_size(data)} {len(data)} bytes {item.get('properties') or ''}")

    ncx_item = next((i for i in manifest.values() if i.get("media-type") == "application/x-dtbncx+xml"), None)
    if ncx_item is not None:
        ncx = ET.fromstring(z.read(normpath(join(base, ncx_item.get("href")))))
        print("\n== current toc.ncx")

        def walk(point, depth):
            label = point.find("ncx:navLabel/ncx:text", NS).text or ""
            src = point.find("ncx:content", NS).get("src")
            print(f"  {'  ' * depth}{label.strip()[:60]}  -> {src}")
            for child in point.findall("ncx:navPoint", NS):
                walk(child, depth + 1)

        for p in ncx.find("ncx:navMap", NS).findall("ncx:navPoint", NS):
            walk(p, 0)


if __name__ == "__main__":
    main()
