#!/usr/bin/env python3
"""Find the LitRes audio edition of a book: narrator, year, ISBN, description, square cover.

usage: litres_audio.py search "<russian title> <author>"
       litres_audio.py get <litres audiobook url> [cover.jpg]   (downloads the 1500x1500 cover when a path is given)

Match the edition by narrator and duration against the files: the same title often has several
recordings, and the one in the folder is the one to describe.
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def search(query):
    data = json.loads(fetch("https://api.litres.ru/foundation/api/search?" + urllib.parse.urlencode({"q": query, "types": "audiobook", "limit": 10})))
    for item in data["payload"]["data"]:
        art = item["instance"]
        persons = art.get("persons") or []
        names = {p.get("role"): p.get("full_name") for p in persons}
        print(json.dumps({"id": art["id"], "title": art["title"], "url": "https://www.litres.ru" + art["url"],
                          "author": names.get("author"), "reader": names.get("reader")}, ensure_ascii=False))


def get(url, cover=None):
    page = fetch(url).decode("utf-8", "replace")
    book = {}
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Audiobook":
                book = item
    art_id = re.search(r"-(\d+)/?$", url.rstrip("/")).group(1)
    hours = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", book.get("duration") or "")
    out = {
        "url": url,
        "title": book.get("name"),
        "author": (book.get("author") or {}).get("name"),
        "narrator": (book.get("readBy") or {}).get("name"),
        "year": book.get("datePublished"),
        "isbn": book.get("isbn"),
        "publisher": (book.get("publisher") or {}).get("name"),
        "duration_h": round(int(hours.group(1) or 0) + int(hours.group(2) or 0) / 60, 2) if hours else None,
        "description": html.unescape(book.get("description") or ""),
        "cover": f"https://cdn.litres.ru/pub/c/cover_max1500/{art_id}.jpg",
    }
    if cover:
        with open(cover, "wb") as f:
            f.write(fetch(out["cover"]))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    {"search": lambda: search(sys.argv[2]), "get": lambda: get(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)}[sys.argv[1]]()
