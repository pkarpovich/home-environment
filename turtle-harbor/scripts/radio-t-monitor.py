#!/usr/bin/env python3

import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


STREAM_URL = os.environ.get("STREAM_URL", "https://stream.radio-t.com/")
RELAY_URL = os.environ.get("RELAY_URL", "https://relay.pkarpovich.space/send")
RELAY_SECRET = os.environ.get("RELAY_SECRET", "")
RECORDING_DIR = os.environ.get("RECORDING_DIR", "/mnt/nas/radio-t")

STATE_IDLE = "IDLE"
STATE_LIVE = "LIVE"

POLL_ACTIVE = 30
POLL_PASSIVE = 900
POLL_LIVE = 300

USER_AGENT = "radio-t-monitor/1.0"
DEBOUNCE_THRESHOLD = 2


def is_stream_live(url: str, timeout: float = 10.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=timeout)
        resp.close()
        return 200 <= resp.status < 300
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, OSError):
        return False


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def is_show_window(now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)
    return now.weekday() == 5 and 19 <= now.hour < 23


def poll_interval(now: datetime | None = None) -> int:
    if is_show_window(now):
        return POLL_ACTIVE
    return POLL_PASSIVE


def step(state: str, miss_count: int, is_live: bool) -> tuple[str, int]:
    if state == STATE_IDLE and is_live:
        return STATE_LIVE, 0
    if state == STATE_LIVE:
        if not is_live:
            miss_count += 1
            if miss_count >= DEBOUNCE_THRESHOLD:
                return STATE_IDLE, 0
            return STATE_LIVE, miss_count
        return STATE_LIVE, 0
    return state, miss_count


def run() -> None:
    state = STATE_IDLE
    miss_count = 0
    log(f"starting monitor, stream_url={STREAM_URL}")

    while True:
        live = is_stream_live(STREAM_URL)
        new_state, miss_count = step(state, miss_count, live)

        if state != new_state:
            log(f"state {state} -> {new_state}")
        state = new_state

        interval = POLL_LIVE if state == STATE_LIVE else poll_interval()
        log(f"state={state}, next check in {interval}s")
        time.sleep(interval)


def run_tests() -> None:
    import unittest
    from unittest.mock import patch, MagicMock

    class TestIsStreamLive(unittest.TestCase):
        @patch("urllib.request.urlopen")
        def test_live_200(self, mock_urlopen):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value = mock_resp
            self.assertTrue(is_stream_live("http://test/"))
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(req.get_header("User-agent"), USER_AGENT)

        @patch("urllib.request.urlopen")
        def test_not_live_404(self, mock_urlopen):
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test/", 404, "Not Found", {}, None
            )
            self.assertFalse(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_not_live_400_bad_request(self, mock_urlopen):
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test/", 400, "Bad Request", {}, None
            )
            self.assertFalse(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_not_live_500(self, mock_urlopen):
            mock_urlopen.side_effect = urllib.error.HTTPError(
                "http://test/", 500, "Server Error", {}, None
            )
            self.assertFalse(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_not_live_timeout(self, mock_urlopen):
            import socket
            mock_urlopen.side_effect = socket.timeout("timed out")
            self.assertFalse(is_stream_live("http://test/"))

        @patch("urllib.request.urlopen")
        def test_not_live_network_error(self, mock_urlopen):
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
            self.assertFalse(is_stream_live("http://test/"))

    class TestIsShowWindow(unittest.TestCase):
        def test_saturday_in_window(self):
            sat_20 = datetime(2026, 2, 28, 20, 0, tzinfo=timezone.utc)
            self.assertTrue(is_show_window(sat_20))

        def test_saturday_start_of_window(self):
            sat_19 = datetime(2026, 2, 28, 19, 0, tzinfo=timezone.utc)
            self.assertTrue(is_show_window(sat_19))

        def test_saturday_end_of_window(self):
            sat_2259 = datetime(2026, 2, 28, 22, 59, tzinfo=timezone.utc)
            self.assertTrue(is_show_window(sat_2259))

        def test_saturday_before_window(self):
            sat_18 = datetime(2026, 2, 28, 18, 0, tzinfo=timezone.utc)
            self.assertFalse(is_show_window(sat_18))

        def test_saturday_after_window(self):
            sat_23 = datetime(2026, 2, 28, 23, 0, tzinfo=timezone.utc)
            self.assertFalse(is_show_window(sat_23))

        def test_weekday(self):
            mon = datetime(2026, 2, 23, 20, 0, tzinfo=timezone.utc)
            self.assertFalse(is_show_window(mon))

    class TestPollInterval(unittest.TestCase):
        def test_active_during_show_window(self):
            sat_20 = datetime(2026, 2, 28, 20, 0, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(sat_20), POLL_ACTIVE)

        def test_passive_outside_show_window(self):
            mon = datetime(2026, 2, 23, 20, 0, tzinfo=timezone.utc)
            self.assertEqual(poll_interval(mon), POLL_PASSIVE)

    class TestStep(unittest.TestCase):
        def test_idle_to_live_on_first_positive(self):
            new_state, miss = step(STATE_IDLE, 0, True)
            self.assertEqual(new_state, STATE_LIVE)
            self.assertEqual(miss, 0)

        def test_live_to_idle_requires_two_misses(self):
            state, miss = step(STATE_LIVE, 0, False)
            self.assertEqual(state, STATE_LIVE)
            self.assertEqual(miss, 1)

            state, miss = step(state, miss, False)
            self.assertEqual(state, STATE_IDLE)
            self.assertEqual(miss, 0)

        def test_single_miss_does_not_flap(self):
            state, miss = step(STATE_LIVE, 0, False)
            self.assertEqual(state, STATE_LIVE)
            self.assertEqual(miss, 1)

        def test_debounce_resets_on_positive(self):
            state, miss = step(STATE_LIVE, 0, False)
            self.assertEqual(state, STATE_LIVE)
            self.assertEqual(miss, 1)

            state, miss = step(state, miss, True)
            self.assertEqual(state, STATE_LIVE)
            self.assertEqual(miss, 0)

            state, miss = step(state, miss, False)
            self.assertEqual(state, STATE_LIVE)
            self.assertEqual(miss, 1)

            state, miss = step(state, miss, False)
            self.assertEqual(state, STATE_IDLE)
            self.assertEqual(miss, 0)

        def test_idle_stays_idle_on_negative(self):
            state, miss = step(STATE_IDLE, 0, False)
            self.assertEqual(state, STATE_IDLE)
            self.assertEqual(miss, 0)

        def test_live_stays_live_on_positive(self):
            state, miss = step(STATE_LIVE, 0, True)
            self.assertEqual(state, STATE_LIVE)
            self.assertEqual(miss, 0)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestIsStreamLive, TestIsShowWindow, TestPollInterval, TestStep]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_tests()
