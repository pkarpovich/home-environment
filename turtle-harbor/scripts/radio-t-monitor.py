#!/usr/bin/env python3

import os
import sys
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

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestIsStreamLive))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_tests()
