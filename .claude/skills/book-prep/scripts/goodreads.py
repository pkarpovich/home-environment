#!/usr/bin/env python3
"""Find a book on Goodreads: its page, series and number, and the English author name.

usage: goodreads.py search "<english title> <author>"     top results: url, title (series, #n), author

Series names and numbers come from here, not from FantLab: FantLab counts a book's place inside
its widest cycle (Dune is 17th in "Dune Universe"), while Goodreads keeps the numbering readers
use. Pick the edition whose cover the user wants; the search gives the most popular one.
"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def search(query, limit=5):
    page = fetch("https://www.goodreads.com/search?" + urllib.parse.urlencode({"q": query}))
    rows = []
    for row in re.findall(r'<tr itemscope itemtype="http://schema.org/Book">(.*?)</tr>', page, re.S)[:limit]:
        url = re.search(r'href="(/book/show/[^"?]+)', row)
        title = re.search(r'<span itemprop=.name. role=.heading. aria-level=.4.>(.*?)</span>', row, re.S)
        author = re.search(r'<span itemprop="name">(.*?)</span>', row, re.S)
        if not (url and title):
            continue
        full = html.unescape(" ".join(re.sub(r"<[^>]+>", "", title.group(1)).split()))
        series = re.search(r"\(([^()]+?),?\s*#([\d.]+)[^()]*\)\s*$", full)
        rows.append({
            "url": "https://www.goodreads.com" + url.group(1),
            "title": re.sub(r"\s*\([^()]*#[\d.][^()]*\)\s*$", "", full),
            "series": series.group(1).strip() if series else None,
            "position": series.group(2) if series else None,
            "author": html.unescape(author.group(1).strip()) if author else None,
        })
    return rows


if __name__ == "__main__":
    if sys.argv[1] == "search":
        print(json.dumps(search(sys.argv[2]), ensure_ascii=False, indent=1))
