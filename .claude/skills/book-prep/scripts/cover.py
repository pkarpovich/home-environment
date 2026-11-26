#!/usr/bin/env python3
"""Fetch the largest available image of the cover of one edition and stretch it to the Kindle screen.

usage: cover.py <goodreads book url> <out.jpg> [--size 1236x1648]

The Goodreads page names the edition (ISBN-13, ASIN) and carries its own cover; the same edition
is then tried at the publisher (Penguin Random House serves print TIFFs) and at Amazon. The
biggest image wins. Covers are stretched, never cropped or padded: a crop cuts the title, and
padding a picture leaves the same bars the stretch is there to remove.
"""
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def size(path):
    out = subprocess.run(["magick", "identify", "-format", "%w %h", f"{path}[0]"], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    w, h = out.stdout.split()
    return int(w), int(h)


def main():
    page_url, out = sys.argv[1], Path(sys.argv[2])
    target = sys.argv[sys.argv.index("--size") + 1] if "--size" in sys.argv else "1236x1648"
    html = fetch(page_url).decode("utf-8", "replace")
    isbn13 = next(iter(re.findall(r'"isbn13":"(\d{13})"', html)), None)
    asin = next(iter(re.findall(r'"asin":"([0-9A-Z]{10})"', html)), None) or next(iter(re.findall(r'"isbn":"([0-9X]{10})"', html)), None)
    og = next(iter(re.findall(r'property="og:image" content="([^"]+)"', html)), None)
    candidates = []
    if og:
        candidates.append(("goodreads", og))
    if isbn13:
        candidates.append(("penguinrandomhouse-tif", f"https://images.penguinrandomhouse.com/cover/tif/{isbn13}"))
        candidates.append(("penguinrandomhouse", f"https://images.penguinrandomhouse.com/cover/{isbn13}"))
    if asin:
        candidates.append(("amazon", f"https://m.media-amazon.com/images/P/{asin}.01._SCRMZZZZZZ_.jpg"))

    tmp = Path(tempfile.mkdtemp(prefix="cover-"))
    found = []
    for name, url in candidates:
        path = tmp / name
        try:
            path.write_bytes(fetch(url))
        except Exception as exc:  # a missing source is normal, the others still count
            print(f"  {name:24} unavailable ({exc.__class__.__name__})")
            continue
        dims = size(path)
        print(f"  {name:24} {dims}  {url}")
        if dims:
            found.append((dims[0] * dims[1], name, path, dims))
    if not found:
        sys.exit("no cover found")
    _, name, path, dims = max(found)
    tw, th = (int(x) for x in target.split("x"))
    subprocess.run(["magick", f"{path}[0]", "-colorspace", "sRGB", "-resize", f"{tw}x{th}!", "-quality", "90", str(out)], check=True)
    print(json.dumps({"source": name, "source_size": dims, "isbn13": isbn13, "asin": asin, "upscaled": dims[0] < tw, "out": str(out)}))


if __name__ == "__main__":
    main()
