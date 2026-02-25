#!/usr/bin/env python3
"""twitch-nfo-generator.py - creates NFO files for Twitch recordings for Plex/tinyMediaManager.

scans twitch recording directories for *-info.json files and generates
matching NFO files compatible with XBMCnfoMoviesImporter plugin.

env vars:
  TWITCH_DIR - root directory of twitch recordings (default: /mnt/nas/twitch)

usage:
  TWITCH_DIR=/mnt/nas/twitch python twitch-nfo-generator.py    # generate NFOs
  python twitch-nfo-generator.py --test                         # run embedded tests
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from datetime import datetime, timezone
from pathlib import Path


TWITCH_DIR = os.environ.get("TWITCH_DIR", "/mnt/nas/twitch")


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def find_info_files(root_dir):
    results = []
    for root, _, files in os.walk(root_dir):
        for name in files:
            if name.endswith("-info.json"):
                results.append(Path(root) / name)
    return results


def nfo_path_for(info_path):
    video_id = info_path.name.removesuffix("-info.json")
    return info_path.parent / f"{video_id}-video.nfo"


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return json.loads(path.read_text(encoding="latin-1"))


def extract_date(data, info_path):
    for field in ("created_at", "published_at", "recorded_at"):
        raw = data.get(field)
        if not raw:
            continue
        try:
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%Y-%m-%d"), str(dt.year)
        except ValueError:
            pass

    for part in info_path.parent.parts:
        if not part.startswith("20") or len(part) < 10:
            continue
        try:
            datetime.strptime(part[:10], "%Y-%m-%d")
            return part[:10], part[:4]
        except ValueError:
            pass

    return "", ""


def extract_duration(data):
    raw = data.get("duration")
    if raw is None:
        return 0

    if isinstance(raw, int):
        return raw

    if isinstance(raw, str):
        if raw.isdigit():
            return int(raw)
        try:
            return int(float(raw) / 1_000_000_000)
        except (ValueError, TypeError):
            return 0

    return 0


def find_thumbnail(info_path):
    video_id = info_path.name.removesuffix("-info.json")
    directory = info_path.parent

    for suffix in ("thumbnail.jpg", "web_thumbnail.jpg", "video-poster.jpg"):
        candidate = directory / f"{video_id}-{suffix}"
        if candidate.exists():
            return candidate.name

    sprites_dir = directory / "sprites"
    if sprites_dir.exists():
        jpgs = sorted(f.name for f in sprites_dir.iterdir() if f.suffix == ".jpg")
        if jpgs:
            return f"sprites/{jpgs[0]}"

    return None


def format_chapters(data):
    chapters = data.get("chapters")
    if not chapters:
        return ""

    lines = ["\n\nChapters:"]
    for ch in chapters:
        seconds = int(ch.get("start", 0))
        h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
        lines.append(f"{h:02d}:{m:02d}:{s:02d} - {ch.get('title', 'Untitled')}")
    return "\n".join(lines)


def unique_games(data):
    chapters = data.get("chapters") or []
    return sorted({ch["title"] for ch in chapters if ch.get("title")})


def build_nfo_xml(data, info_path):
    title = data.get("title", "Unknown Title")
    user_name = data.get("user_name", "Unknown User")
    description = data.get("description", "")
    language = data.get("language", "")
    video_id = info_path.name.removesuffix("-info.json")

    premiere_date, year = extract_date(data, info_path)
    duration = extract_duration(data)

    movie = ET.Element("movie")
    ET.SubElement(movie, "title").text = title
    ET.SubElement(movie, "originaltitle").text = f"{user_name} - {premiere_date} - {title}"
    ET.SubElement(movie, "sorttitle").text = f"{premiere_date} - {title}"
    ET.SubElement(movie, "year").text = year
    ET.SubElement(movie, "set").text = user_name

    full_description = description + format_chapters(data)
    ET.SubElement(movie, "plot").text = full_description
    ET.SubElement(movie, "runtime").text = str(duration)

    ET.SubElement(movie, "premiered").text = premiere_date
    ET.SubElement(movie, "aired").text = premiere_date
    ET.SubElement(movie, "watched").text = "false"
    ET.SubElement(movie, "playcount").text = "0"
    ET.SubElement(movie, "studio").text = user_name

    games = unique_games(data)
    for game in games:
        ET.SubElement(movie, "genre").text = game
        ET.SubElement(movie, "tag").text = game

    category = data.get("category")
    if category:
        ET.SubElement(movie, "genre").text = category
        ET.SubElement(movie, "tag").text = category

    ET.SubElement(movie, "tag").text = user_name

    if language:
        langs = ET.SubElement(movie, "languages")
        ET.SubElement(langs, "language").text = language

    thumb = find_thumbnail(info_path)
    if thumb:
        ET.SubElement(movie, "thumb").text = thumb

    ET.SubElement(movie, "dateadded").text = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    chapters = data.get("chapters")
    if chapters:
        ch_elem = ET.SubElement(movie, "chapters")
        for ch in chapters:
            ET.SubElement(ch_elem, "chapter", name=ch.get("title", "Untitled"), start=str(int(ch.get("start", 0))))

    fileinfo = ET.SubElement(movie, "fileinfo")
    streamdetails = ET.SubElement(fileinfo, "streamdetails")
    video = ET.SubElement(streamdetails, "video")
    ET.SubElement(video, "codec").text = "h264"
    ET.SubElement(video, "aspect").text = "1.78"
    ET.SubElement(video, "width").text = "1920"
    ET.SubElement(video, "height").text = "1080"
    ET.SubElement(video, "durationinseconds").text = str(duration)

    audio = ET.SubElement(streamdetails, "audio")
    ET.SubElement(audio, "codec").text = "AAC"
    ET.SubElement(audio, "channels").text = "1"

    ET.SubElement(movie, "source").text = "UNKNOWN"
    ET.SubElement(movie, "original_filename").text = f"{video_id}-video.mp4"

    rough = ET.tostring(movie, "utf-8")
    reparsed = minidom.parseString(rough)
    xml_decl = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    body = reparsed.toprettyxml(indent="  ")[23:]
    return xml_decl + body


def generate_nfo(info_path):
    output = nfo_path_for(info_path)
    if output.exists():
        return False

    data = load_json(info_path)
    xml_content = build_nfo_xml(data, info_path)
    output.write_text(xml_content, encoding="utf-8")
    return True


def run():
    root = Path(TWITCH_DIR)
    if not root.is_dir():
        log(f"twitch directory not found: {root}")
        sys.exit(1)

    log(f"scanning {root}")
    info_files = find_info_files(root)
    log(f"found {len(info_files)} info files")

    created = 0
    skipped = 0
    errors = 0

    for info_path in info_files:
        try:
            if generate_nfo(info_path):
                log(f"created {nfo_path_for(info_path).name}")
                created += 1
            else:
                skipped += 1
        except Exception as e:
            log(f"error processing {info_path.name}: {e}")
            errors += 1

    log(f"done: {created} created, {skipped} skipped, {errors} errors")


def run_tests():
    import tempfile
    import unittest

    class TestNfoPath(unittest.TestCase):
        def test_generates_correct_path(self):
            p = Path("/media/twitch/stream/abc123-info.json")
            self.assertEqual(nfo_path_for(p), Path("/media/twitch/stream/abc123-video.nfo"))

    class TestExtractDate(unittest.TestCase):
        def test_from_created_at(self):
            data = {"created_at": "2025-03-15T20:00:00Z"}
            date, year = extract_date(data, Path("/x/y/file-info.json"))
            self.assertEqual(date, "2025-03-15")
            self.assertEqual(year, "2025")

        def test_from_directory_name(self):
            data = {}
            path = Path("/media/twitch/streamer/2025-03-15_stream/abc-info.json")
            date, year = extract_date(data, path)
            self.assertEqual(date, "2025-03-15")
            self.assertEqual(year, "2025")

        def test_empty_when_no_date(self):
            data = {}
            path = Path("/media/twitch/abc-info.json")
            date, year = extract_date(data, path)
            self.assertEqual(date, "")
            self.assertEqual(year, "")

    class TestExtractDuration(unittest.TestCase):
        def test_integer(self):
            self.assertEqual(extract_duration({"duration": 3600}), 3600)

        def test_string_digits(self):
            self.assertEqual(extract_duration({"duration": "3600"}), 3600)

        def test_nanoseconds(self):
            self.assertEqual(extract_duration({"duration": "5400000000000"}), 5400)

        def test_missing(self):
            self.assertEqual(extract_duration({}), 0)

    class TestFindThumbnail(unittest.TestCase):
        def test_finds_thumbnail(self):
            with tempfile.TemporaryDirectory() as tmp:
                info = Path(tmp) / "abc-info.json"
                thumb = Path(tmp) / "abc-thumbnail.jpg"
                info.touch()
                thumb.touch()
                self.assertEqual(find_thumbnail(info), "abc-thumbnail.jpg")

        def test_returns_none_when_missing(self):
            with tempfile.TemporaryDirectory() as tmp:
                info = Path(tmp) / "abc-info.json"
                info.touch()
                self.assertIsNone(find_thumbnail(info))

        def test_finds_sprite(self):
            with tempfile.TemporaryDirectory() as tmp:
                info = Path(tmp) / "abc-info.json"
                info.touch()
                sprites = Path(tmp) / "sprites"
                sprites.mkdir()
                (sprites / "001.jpg").touch()
                (sprites / "002.jpg").touch()
                self.assertEqual(find_thumbnail(info), "sprites/001.jpg")

    class TestFormatChapters(unittest.TestCase):
        def test_with_chapters(self):
            data = {"chapters": [
                {"start": 0, "title": "Intro"},
                {"start": 3661, "title": "Game"},
            ]}
            result = format_chapters(data)
            self.assertIn("00:00:00 - Intro", result)
            self.assertIn("01:01:01 - Game", result)

        def test_empty(self):
            self.assertEqual(format_chapters({}), "")

    class TestUniqueGames(unittest.TestCase):
        def test_deduplicates_and_sorts(self):
            data = {"chapters": [
                {"title": "Zelda"},
                {"title": "Mario"},
                {"title": "Zelda"},
            ]}
            self.assertEqual(unique_games(data), ["Mario", "Zelda"])

    class TestBuildNfoXml(unittest.TestCase):
        def test_produces_valid_xml(self):
            data = {
                "title": "Test Stream",
                "user_name": "streamer",
                "created_at": "2025-06-01T20:00:00Z",
                "duration": 7200,
            }
            with tempfile.TemporaryDirectory() as tmp:
                info = Path(tmp) / "vid123-info.json"
                info.write_text(json.dumps(data))
                xml = build_nfo_xml(data, info)

                self.assertIn("<title>Test Stream</title>", xml)
                self.assertIn("<set>streamer</set>", xml)
                self.assertIn("<year>2025</year>", xml)
                self.assertIn("<premiered>2025-06-01</premiered>", xml)
                self.assertIn("<runtime>7200</runtime>", xml)
                self.assertIn("vid123-video.mp4", xml)

    class TestGenerateNfo(unittest.TestCase):
        def test_creates_nfo_file(self):
            with tempfile.TemporaryDirectory() as tmp:
                data = {"title": "Test", "user_name": "user", "duration": 100}
                info = Path(tmp) / "vid-info.json"
                info.write_text(json.dumps(data))

                self.assertTrue(generate_nfo(info))
                nfo = Path(tmp) / "vid-video.nfo"
                self.assertTrue(nfo.exists())
                self.assertIn("<title>Test</title>", nfo.read_text())

        def test_skips_existing(self):
            with tempfile.TemporaryDirectory() as tmp:
                data = {"title": "Test", "user_name": "user"}
                info = Path(tmp) / "vid-info.json"
                info.write_text(json.dumps(data))
                nfo = Path(tmp) / "vid-video.nfo"
                nfo.write_text("existing")

                self.assertFalse(generate_nfo(info))
                self.assertEqual(nfo.read_text(), "existing")

    class TestFindInfoFiles(unittest.TestCase):
        def test_finds_nested(self):
            with tempfile.TemporaryDirectory() as tmp:
                sub = Path(tmp) / "streamer" / "2025-01-01"
                sub.mkdir(parents=True)
                (sub / "abc-info.json").touch()
                (sub / "abc-video.mp4").touch()
                (sub / "other.txt").touch()

                results = find_info_files(tmp)
                self.assertEqual(len(results), 1)
                self.assertTrue(results[0].name.endswith("-info.json"))

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestNfoPath, TestExtractDate, TestExtractDuration, TestFindThumbnail,
        TestFormatChapters, TestUniqueGames, TestBuildNfoXml, TestGenerateNfo,
        TestFindInfoFiles,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Twitch NFO generator for Plex/tinyMediaManager")
    parser.add_argument("--test", action="store_true", help="run unit tests")
    args = parser.parse_args()

    if args.test:
        run_tests()
        return

    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\r\033[K", end="")
        sys.exit(130)
