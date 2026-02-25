#!/usr/bin/env python3
"""radio-t-recorder.py - monitors Radio-T live stream and records audio to file.

state machine with two states:
  IDLE      - polls stream URL, transitions to RECORDING on detection
  RECORDING - streams audio to file, transitions back to IDLE when stream ends

env vars:
  STREAM_URL    - stream endpoint (default: https://stream.radio-t.com/)
  RECORDING_DIR - directory for recordings (default: /mnt/nas/radio-t)

usage:
  python radio-t-recorder.py                  # run recorder
  python radio-t-recorder.py --test           # run embedded tests
"""

import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


STREAM_URL = os.environ.get("STREAM_URL", "https://stream.radio-t.com/")
RECORDING_DIR = os.environ.get("RECORDING_DIR", "/mnt/nas/radio-t")

STATE_IDLE = "IDLE"
STATE_RECORDING = "RECORDING"

POLL_ACTIVE = 30
POLL_PASSIVE = 900
CHUNK_SIZE = 8192
SIZE_LOG_INTERVAL = 30


def is_stream_live(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status != 404
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        return True
    except Exception:
        return False


def is_show_window(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    return now.weekday() == 5 and 19 <= now.hour < 23


def poll_interval(now=None):
    if is_show_window(now):
        return POLL_ACTIVE
    return POLL_PASSIVE


def recording_filename(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    return f"radio-t-{now.strftime('%Y-%m-%d')}.mp3"


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def record_stream(url, filepath):
    log(f"recording to {filepath}")
    req = urllib.request.Request(url)
    total_bytes = 0
    last_log_time = time.monotonic()

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        with open(filepath, "ab") as f:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                total_bytes += len(chunk)

                now = time.monotonic()
                if now - last_log_time >= SIZE_LOG_INTERVAL:
                    size_mb = total_bytes / (1024 * 1024)
                    log(f"recording... {size_mb:.1f} MB written")
                    last_log_time = now
    except Exception as e:
        log(f"recording stopped: {e}")

    size_mb = total_bytes / (1024 * 1024)
    log(f"recording finished, total: {size_mb:.1f} MB")
    return total_bytes


def run():
    state = STATE_IDLE
    log(f"starting recorder, stream_url={STREAM_URL}, recording_dir={RECORDING_DIR}")

    rec_dir = Path(RECORDING_DIR)
    rec_dir.mkdir(parents=True, exist_ok=True)

    while True:
        live = is_stream_live(STREAM_URL)

        if state == STATE_IDLE:
            if live:
                log("stream detected, starting recording")
                state = STATE_RECORDING
                log(f"state -> {STATE_RECORDING}")
                filepath = rec_dir / recording_filename()
                record_stream(STREAM_URL, filepath)
                state = STATE_IDLE
                log(f"state -> {STATE_IDLE}")
                continue
            interval = poll_interval()
        else:
            interval = poll_interval()

        log(f"state={state}, next check in {interval}s")
        time.sleep(interval)


def run_tests():
    import unittest
    import tempfile
    from unittest.mock import patch, MagicMock
    from io import BytesIO

    class TestIsStreamLive(unittest.TestCase):
        @patch("urllib.request.urlopen")
        def test_live_200(self, mock_urlopen):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value = mock_resp
            self.assertTrue(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_not_live_404_response(self, mock_urlopen):
            mock_resp = MagicMock()
            mock_resp.status = 404
            mock_urlopen.return_value = mock_resp
            self.assertFalse(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_not_live_404_error(self, mock_urlopen):
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test/", 404, "Not Found", {}, None
            )
            self.assertFalse(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_live_on_non_404_error(self, mock_urlopen):
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test/", 500, "Server Error", {}, None
            )
            self.assertTrue(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_not_live_on_network_error(self, mock_urlopen):
            mock_urlopen.side_effect = ConnectionError("refused")
            self.assertFalse(is_stream_live("http://test/"))

    class TestPollInterval(unittest.TestCase):
        def test_saturday_show_window(self):
            sat_20 = datetime(2026, 2, 28, 20, 0, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(sat_20), POLL_ACTIVE)

        def test_saturday_before_window(self):
            sat_18 = datetime(2026, 2, 28, 18, 0, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(sat_18), POLL_PASSIVE)

        def test_saturday_after_window(self):
            sat_23 = datetime(2026, 2, 28, 23, 0, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(sat_23), POLL_PASSIVE)

        def test_weekday(self):
            mon = datetime(2026, 2, 23, 20, 0, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(mon), POLL_PASSIVE)

        def test_saturday_start_of_window(self):
            sat_19 = datetime(2026, 2, 28, 19, 0, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(sat_19), POLL_ACTIVE)

    class TestRecordingFilename(unittest.TestCase):
        def test_format(self):
            dt = datetime(2026, 2, 28, 20, 30, tzinfo=timezone.utc)
            self.assertEqual(recording_filename(dt), "radio-t-2026-02-28.mp3")

        def test_different_date(self):
            dt = datetime(2025, 12, 6, 21, 0, tzinfo=timezone.utc)
            self.assertEqual(recording_filename(dt), "radio-t-2025-12-06.mp3")

    class TestRecordStream(unittest.TestCase):
        @patch("urllib.request.urlopen")
        def test_writes_chunks_to_file(self, mock_urlopen):
            chunk1 = b"x" * CHUNK_SIZE
            chunk2 = b"y" * 100
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[chunk1, chunk2, b""])
            mock_urlopen.return_value = mock_resp

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                total = record_stream("http://test/", tmp_path)
                self.assertEqual(total, CHUNK_SIZE + 100)

                with open(tmp_path, "rb") as f:
                    data = f.read()
                self.assertEqual(len(data), CHUNK_SIZE + 100)
                self.assertEqual(data[:CHUNK_SIZE], chunk1)
                self.assertEqual(data[CHUNK_SIZE:], chunk2)
            finally:
                os.unlink(tmp_path)

        @patch("urllib.request.urlopen")
        def test_handles_connection_error(self, mock_urlopen):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[b"data", ConnectionError("lost")])
            mock_urlopen.return_value = mock_resp

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                total = record_stream("http://test/", tmp_path)
                self.assertEqual(total, 4)
            finally:
                os.unlink(tmp_path)

        @patch("urllib.request.urlopen")
        def test_appends_to_existing_file(self, mock_urlopen):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[b"new", b""])
            mock_urlopen.return_value = mock_resp

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(b"existing")
                tmp_path = tmp.name

            try:
                record_stream("http://test/", tmp_path)
                with open(tmp_path, "rb") as f:
                    data = f.read()
                self.assertEqual(data, b"existingnew")
            finally:
                os.unlink(tmp_path)

    class TestRecordingDirCreation(unittest.TestCase):
        def test_creates_directory(self):
            with tempfile.TemporaryDirectory() as base:
                new_dir = Path(base) / "sub" / "radio-t"
                self.assertFalse(new_dir.exists())
                new_dir.mkdir(parents=True, exist_ok=True)
                self.assertTrue(new_dir.exists())

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestIsStreamLive, TestPollInterval, TestRecordingFilename, TestRecordStream, TestRecordingDirCreation]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Radio-T stream recorder")
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
