#!/usr/bin/env python3
"""Look a book up on FantLab: Russian and original names of the work, its authors and its cycle.

usage: fantlab.py search "<title> <author>"
       fantlab.py work <work_id>
"""
import http.client
import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.fantlab.ru"


def get(path, tries=4):
    """FantLab drops connections when asked often; a pause and a retry get through."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "book-prep/1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except (OSError, http.client.HTTPException):
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def search(query):
    data = get("/search-works?" + urllib.parse.urlencode({"q": query, "page": 1}))
    for w in (data if isinstance(data, list) else data.get("matches", []))[:15]:
        print(f"{w.get('work_id'):>8}  {w.get('name_eng') or '':8} {w.get('year') or '':>5}  {w.get('rusname') or ''} / {w.get('name') or ''}  — {w.get('autor_rusname') or ''}")


def fetch_work(work_id):
    w = get(f"/work/{work_id}/extended")
    english = []
    blocks = w.get("editions_blocks") or {}
    for block in (blocks.values() if isinstance(blocks, dict) else blocks):
        for e in block.get("list") or []:
            if e.get("lang_code") == "en" and e.get("name") and e["name"] not in english:
                english.append(e["name"])
    out = {
        "work_id": w["work_id"],
        "url": f"https://fantlab.ru/work{w['work_id']}",
        "title_ru": w.get("work_name"),
        "title_orig": w.get("work_name_orig"),
        "year": w.get("work_year"),
        "type": w.get("work_type"),
        "authors": [{"id": a.get("id"), "ru": a.get("name"), "orig": a.get("name_orig")} for a in w.get("authors", [])],
        "cycles": [],
        "english_editions": english,
    }
    for chain in (w.get("parents") or {}).get("cycles", []):
        for cycle in chain:
            c = get(f"/work/{cycle['work_id']}/extended")
            novels = [ch for ch in c.get("children", []) if ch.get("work_type_name") in ("Роман", "Повесть", "novel") or ch.get("work_type") in ("novel", "Роман")]
            members = novels or c.get("children", [])
            position = next((i for i, ch in enumerate(members, 1) if ch.get("work_id") == w["work_id"]), None)
            out["cycles"].append({
                "id": cycle["work_id"],
                "ru": cycle.get("work_name"),
                "orig": c.get("work_name_orig"),
                "position": position,
                "members": [f"{ch.get('work_name') or ''} / {ch.get('work_name_orig') or ''} ({ch.get('work_year')})" for ch in members],
            })
    return out


def work(work_id):
    print(json.dumps(fetch_work(work_id), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    {"search": lambda: search(sys.argv[2]), "work": lambda: work(sys.argv[2])}[sys.argv[1]]()
