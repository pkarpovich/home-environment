#!/usr/bin/env python3
"""radio-t-checker.py - monitors Radio-T live stream and sends push notification when it starts.

state machine with two states:
  IDLE  - polls stream URL, sends notification on detection, transitions to LIVE
  LIVE  - polls to detect stream end, transitions back to IDLE

env vars:
  STREAM_URL   - stream endpoint (default: https://stream.radio-t.com/)
  RELAY_URL    - notification relay (default: https://relay.pkarpovich.space/send)
  RELAY_SECRET - secret for relay x-secret header (required)

usage:
  RELAY_SECRET=xxx python radio-t-checker.py          # run checker
  python radio-t-checker.py --test                    # run embedded tests
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


STREAM_URL = os.environ.get("STREAM_URL", "https://stream.radio-t.com/")
RELAY_URL = os.environ.get("RELAY_URL", "https://relay.pkarpovich.space/send")
RELAY_SECRET = os.environ.get("RELAY_SECRET", "")

STATE_IDLE = "IDLE"
STATE_LIVE = "LIVE"

POLL_ACTIVE = 30
POLL_PASSIVE = 900
POLL_LIVE = 300


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


def send_notification(message):
    payload = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        RELAY_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-secret": RELAY_SECRET,
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"notification failed: {e}")


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def run():
    if not RELAY_SECRET:
        log("RELAY_SECRET is required")
        sys.exit(1)

    state = STATE_IDLE
    log(f"starting checker, stream_url={STREAM_URL}")

    while True:
        live = is_stream_live(STREAM_URL)

        if state == STATE_IDLE:
            if live:
                log("stream detected, sending notification")
                send_notification("Radio-T stream is live!")
                state = STATE_LIVE
                log(f"state -> {STATE_LIVE}")
            interval = poll_interval() if not live else POLL_LIVE
        else:
            if not live:
                log("stream ended")
                state = STATE_IDLE
                log(f"state -> {STATE_IDLE}")
                interval = poll_interval()
            else:
                interval = POLL_LIVE

        log(f"state={state}, next check in {interval}s")
        time.sleep(interval)


def run_tests():
    import unittest
    from unittest.mock import patch, MagicMock

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

        def test_saturday_end_of_window(self):
            sat_2259 = datetime(2026, 2, 28, 22, 59, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(sat_2259), POLL_ACTIVE)

    class TestSendNotification(unittest.TestCase):
        @patch("urllib.request.urlopen")
        def test_sends_correct_payload(self, mock_urlopen):
            mock_urlopen.return_value = MagicMock()

            with patch.dict(os.environ, {"RELAY_SECRET": "test-secret"}):
                import importlib
                global RELAY_SECRET
                old_secret = RELAY_SECRET
                RELAY_SECRET = "test-secret"
                try:
                    send_notification("test message")
                finally:
                    RELAY_SECRET = old_secret

            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["message"], "test message")
            self.assertEqual(req.get_header("X-secret"), "test-secret")
            self.assertEqual(req.get_header("Content-type"), "application/json")
            self.assertEqual(req.get_method(), "POST")

    class TestStateTransitions(unittest.TestCase):
        @patch("urllib.request.urlopen")
        def test_idle_to_live_on_detection(self, mock_urlopen):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value = mock_resp

            state = STATE_IDLE
            if is_stream_live("http://test/"):
                state = STATE_LIVE
            self.assertEqual(state, STATE_LIVE)

        @patch("urllib.request.urlopen")
        def test_live_to_idle_on_end(self, mock_urlopen):
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test/", 404, "Not Found", {}, None
            )

            state = STATE_LIVE
            if not is_stream_live("http://test/"):
                state = STATE_IDLE
            self.assertEqual(state, STATE_IDLE)

        @patch("urllib.request.urlopen")
        def test_no_duplicate_notifications(self, mock_urlopen):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value = mock_resp

            state = STATE_IDLE
            notifications_sent = 0

            for _ in range(5):
                live = is_stream_live("http://test/")
                if state == STATE_IDLE and live:
                    notifications_sent += 1
                    state = STATE_LIVE
                elif state == STATE_LIVE and live:
                    pass

            self.assertEqual(notifications_sent, 1)
            self.assertEqual(state, STATE_LIVE)

        @patch("urllib.request.urlopen")
        def test_full_cycle(self, mock_urlopen):
            responses = []
            live_resp = MagicMock()
            live_resp.status = 200
            dead_error = urllib.error.HTTPError("http://test/", 404, "Not Found", {}, None)

            call_count = 0

            def side_effect(*args, **kwargs):
                nonlocal call_count
                idx = call_count
                call_count += 1
                if idx < 2:
                    return live_resp
                raise dead_error

            mock_urlopen.side_effect = side_effect

            state = STATE_IDLE
            notifications = 0

            for _ in range(4):
                live = is_stream_live("http://test/")
                if state == STATE_IDLE and live:
                    notifications += 1
                    state = STATE_LIVE
                elif state == STATE_LIVE and not live:
                    state = STATE_IDLE

            self.assertEqual(notifications, 1)
            self.assertEqual(state, STATE_IDLE)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestIsStreamLive, TestPollInterval, TestSendNotification, TestStateTransitions]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Radio-T stream checker with push notifications")
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
