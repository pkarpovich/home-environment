#!/usr/bin/env python3

import json
import os
import socket
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Callable


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


NOTIFICATION_RETRY_DELAYS = [1, 3]


def send_notification(message: str, relay_url: str, secret: str) -> bool:
    payload = json.dumps({"message": message}).encode("utf-8")
    attempts = 1 + len(NOTIFICATION_RETRY_DELAYS)

    for i in range(attempts):
        try:
            req = urllib.request.Request(
                relay_url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-secret": secret,
                },
            )
            resp = urllib.request.urlopen(req, timeout=10.0)
            resp.close()
            log(f"notification sent: {message}")
            return True
        except (urllib.error.URLError, OSError) as e:
            log(f"notification attempt {i + 1}/{attempts} failed: {e}")
            if i < len(NOTIFICATION_RETRY_DELAYS):
                time.sleep(NOTIFICATION_RETRY_DELAYS[i])

    log(f"notification failed after {attempts} attempts, giving up")
    return False


RECONNECT_DELAYS = [1, 3, 10]
STREAM_READ_TIMEOUT = 30
CHUNK_SIZE = 8192
LOG_INTERVAL = 30


def record_stream(url: str, filepath: str, is_live_fn: Callable[[], bool]) -> bool:
    total_bytes = 0
    consecutive_failures = 0
    max_failures = len(RECONNECT_DELAYS) + 1

    while consecutive_failures < max_failures:
        bytes_this_attempt = 0
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
            resp = urllib.request.urlopen(req, timeout=STREAM_READ_TIMEOUT)
            try:
                last_log_time = time.monotonic()

                try:
                    f = open(filepath, "ab")
                except OSError as e:
                    log(f"storage error opening {filepath}: {e}")
                    return False

                close_failed = False
                try:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        try:
                            f.write(chunk)
                        except OSError as e:
                            log(f"storage error writing to {filepath}: {e}")
                            return False
                        consecutive_failures = 0
                        bytes_this_attempt += len(chunk)
                        total_bytes += len(chunk)
                        now = time.monotonic()
                        if now - last_log_time >= LOG_INTERVAL:
                            log(f"recording: {total_bytes} bytes written to {filepath}")
                            last_log_time = now
                finally:
                    try:
                        f.close()
                    except OSError as e:
                        log(f"storage error closing {filepath}: {e}")
                        close_failed = True

                if close_failed:
                    return False
                if bytes_this_attempt > 0:
                    return True
            finally:
                resp.close()
        except (socket.timeout, ConnectionError, urllib.error.URLError, OSError):
            pass

        if consecutive_failures < len(RECONNECT_DELAYS):
            delay = RECONNECT_DELAYS[consecutive_failures]
            log(f"stream connection lost, retrying in {delay}s ({consecutive_failures + 1}/{max_failures})")
            time.sleep(delay)
            if not is_live_fn():
                log("stream no longer live, stopping recording")
                return True
        consecutive_failures += 1

    log(f"recording stopped after {max_failures} failed reconnects, {total_bytes} bytes total")
    return True


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


def recording_filename(now: datetime) -> str:
    return now.strftime("radio-t-%Y-%m-%d.mp3")


def run() -> None:
    state = STATE_IDLE
    miss_count = 0
    filepath = None
    log(f"starting monitor, stream_url={STREAM_URL}")

    while True:
        live = is_stream_live(STREAM_URL)
        prev_state = state
        state, miss_count = step(state, miss_count, live)

        if prev_state != state:
            log(f"state {prev_state} -> {state}")

        if prev_state == STATE_IDLE and state == STATE_LIVE:
            send_notification("Radio-T stream is live!", RELAY_URL, RELAY_SECRET)
            now = datetime.now(timezone.utc)
            filename = recording_filename(now)
            filepath = os.path.join(RECORDING_DIR, filename)
            os.makedirs(RECORDING_DIR, exist_ok=True)

        if state == STATE_LIVE and live and filepath:
            log(f"recording to {filepath}")
            storage_error = False
            while True:
                resumable = record_stream(STREAM_URL, filepath, lambda: is_stream_live(STREAM_URL))
                if not resumable:
                    log("recording stopped due to storage error, not retrying")
                    storage_error = True
                    break
                still_live = is_stream_live(STREAM_URL)
                if not still_live:
                    time.sleep(POLL_ACTIVE)
                    still_live = is_stream_live(STREAM_URL)
                if not still_live:
                    break
                log("stream still live after recording interruption, resuming")
            if storage_error:
                filepath = None
            miss_count = 0 if storage_error else 1
            continue

        if state == STATE_IDLE:
            filepath = None

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
            mock_resp.close.assert_called_once()
            mock_resp.read.assert_not_called()

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

    class TestSendNotification(unittest.TestCase):
        @patch("time.sleep")
        @patch("urllib.request.urlopen")
        def test_notification_success_first_try(self, mock_urlopen, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value = mock_resp
            result = send_notification("test msg", "http://relay/send", "s3cret")
            self.assertTrue(result)
            self.assertEqual(mock_urlopen.call_count, 1)
            mock_sleep.assert_not_called()

        @patch("time.sleep")
        @patch("urllib.request.urlopen")
        def test_notification_retries_on_failure(self, mock_urlopen, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.side_effect = [
                urllib.error.URLError("connection refused"),
                mock_resp,
            ]
            result = send_notification("test msg", "http://relay/send", "s3cret")
            self.assertTrue(result)
            self.assertEqual(mock_urlopen.call_count, 2)
            mock_sleep.assert_called_once_with(1)

        @patch("time.sleep")
        @patch("urllib.request.urlopen")
        def test_notification_gives_up_after_three_attempts(self, mock_urlopen, mock_sleep):
            mock_urlopen.side_effect = urllib.error.URLError("connection refused")
            result = send_notification("test msg", "http://relay/send", "s3cret")
            self.assertFalse(result)
            self.assertEqual(mock_urlopen.call_count, 3)
            self.assertEqual(mock_sleep.call_count, 2)
            mock_sleep.assert_any_call(1)
            mock_sleep.assert_any_call(3)

        @patch("time.sleep")
        @patch("urllib.request.urlopen")
        def test_notification_payload_format(self, mock_urlopen, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value = mock_resp
            send_notification("Radio-T is live!", "http://relay/send", "s3cret")
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(req.get_header("Content-type"), "application/json")
            self.assertEqual(req.get_header("X-secret"), "s3cret")
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body, {"message": "Radio-T is live!"})

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

    class TestRecordStream(unittest.TestCase):
        @patch("time.sleep")
        @patch("time.monotonic")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_writes_chunks_to_file(self, mock_urlopen, mock_file, mock_monotonic, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[b"chunk1", b"chunk2", b""])
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp
            mock_monotonic.return_value = 0.0

            record_stream("http://test/stream", "/tmp/test.mp3", lambda: True)

            mock_file.assert_called_once_with("/tmp/test.mp3", "ab")
            handle = mock_file()
            handle.write.assert_any_call(b"chunk1")
            handle.write.assert_any_call(b"chunk2")
            self.assertEqual(handle.write.call_count, 2)

        @patch("time.sleep")
        @patch("time.monotonic")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_reconnects_on_connection_error_while_live(self, mock_urlopen, mock_file, mock_monotonic, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[b"data", b""])
            mock_resp.close = MagicMock()
            mock_is_live = MagicMock(return_value=True)
            mock_urlopen.side_effect = [
                ConnectionError("reset"),
                mock_resp,
            ]
            mock_monotonic.return_value = 0.0

            record_stream("http://test/stream", "/tmp/test.mp3", mock_is_live)

            self.assertEqual(mock_urlopen.call_count, 2)
            mock_sleep.assert_called_once_with(1)
            mock_is_live.assert_called_once()

        @patch("time.sleep")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_stops_recording_when_no_longer_live(self, mock_urlopen, mock_file, mock_sleep):
            mock_urlopen.side_effect = ConnectionError("reset")

            record_stream("http://test/stream", "/tmp/test.mp3", lambda: False)

            self.assertEqual(mock_urlopen.call_count, 1)
            mock_sleep.assert_called_once_with(1)

        @patch("time.sleep")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_gives_up_after_four_failed_reconnects(self, mock_urlopen, mock_file, mock_sleep):
            mock_urlopen.side_effect = ConnectionError("reset")

            record_stream("http://test/stream", "/tmp/test.mp3", lambda: True)

            self.assertEqual(mock_urlopen.call_count, 4)
            self.assertEqual(mock_sleep.call_count, 3)
            mock_sleep.assert_any_call(1)
            mock_sleep.assert_any_call(3)
            mock_sleep.assert_any_call(10)

        @patch("time.sleep")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_gives_up_when_read_always_fails(self, mock_urlopen, mock_file, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=OSError("read failed"))
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp

            record_stream("http://test/stream", "/tmp/test.mp3", lambda: True)

            self.assertEqual(mock_urlopen.call_count, 4)
            self.assertEqual(mock_sleep.call_count, 3)

        @patch("time.sleep")
        @patch("time.monotonic")
        @patch("urllib.request.urlopen")
        def test_appends_to_existing_file(self, mock_urlopen, mock_monotonic, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[b"new_data", b""])
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp
            mock_monotonic.return_value = 0.0

            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(b"existing_data")
                tmppath = f.name

            try:
                record_stream("http://test/stream", tmppath, lambda: True)
                with open(tmppath, "rb") as f:
                    content = f.read()
                self.assertEqual(content, b"existing_datanew_data")
            finally:
                os.unlink(tmppath)

    class TestRecordingFilename(unittest.TestCase):
        def test_filename_fixed_at_detection_time(self):
            now = datetime(2026, 4, 4, 20, 30, tzinfo=timezone.utc)
            self.assertEqual(recording_filename(now), "radio-t-2026-04-04.mp3")
            different = datetime(2026, 12, 25, 22, 0, tzinfo=timezone.utc)
            self.assertEqual(recording_filename(different), "radio-t-2026-12-25.mp3")

    class TestMainLoopIntegration(unittest.TestCase):
        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_full_cycle_idle_to_live_to_idle(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [True, False, False, SystemExit("done")]
            mock_notify.return_value = True

            with self.assertRaises(SystemExit):
                run()

            mock_notify.assert_called_once_with("Radio-T stream is live!", RELAY_URL, RELAY_SECRET)
            mock_record.assert_called_once()
            filepath_arg = mock_record.call_args[0][1]
            self.assertTrue(filepath_arg.startswith(RECORDING_DIR))
            self.assertTrue(filepath_arg.endswith(".mp3"))
            mock_makedirs.assert_called_once_with(RECORDING_DIR, exist_ok=True)
            self.assertEqual(mock_sleep.call_count, 1)

        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_notification_sent_on_transition(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [True, SystemExit("done")]
            mock_notify.return_value = True

            with self.assertRaises(SystemExit):
                run()

            mock_notify.assert_called_once_with("Radio-T stream is live!", RELAY_URL, RELAY_SECRET)
            mock_record.assert_called_once()

        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_filename_fixed_at_detection_time(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [True, SystemExit("done")]
            mock_notify.return_value = True

            with self.assertRaises(SystemExit):
                run()

            filepath_arg = mock_record.call_args[0][1]
            filename = os.path.basename(filepath_arg)
            import re
            self.assertRegex(filename, r"radio-t-\d{4}-\d{2}-\d{2}\.mp3")

    class TestRecordStreamStorageErrors(unittest.TestCase):
        @patch("time.sleep")
        @patch("builtins.open")
        @patch("urllib.request.urlopen")
        def test_stops_on_storage_error_opening_file(self, mock_urlopen, mock_open, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp
            mock_open.side_effect = OSError("Permission denied")

            result = record_stream("http://test/stream", "/tmp/test.mp3", lambda: True)

            self.assertFalse(result)
            self.assertEqual(mock_urlopen.call_count, 1)
            mock_sleep.assert_not_called()

        @patch("time.sleep")
        @patch("time.monotonic")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_stops_on_storage_error_writing(self, mock_urlopen, mock_file, mock_monotonic, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[b"data"])
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp
            mock_monotonic.return_value = 0.0

            handle = mock_file()
            handle.write.side_effect = OSError("No space left on device")

            result = record_stream("http://test/stream", "/tmp/test.mp3", lambda: True)

            self.assertFalse(result)
            self.assertEqual(mock_urlopen.call_count, 1)
            mock_sleep.assert_not_called()

        @patch("time.sleep")
        @patch("time.monotonic")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_stops_on_storage_error_closing(self, mock_urlopen, mock_file, mock_monotonic, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(side_effect=[b"data", b""])
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp
            mock_monotonic.return_value = 0.0

            handle = mock_file()
            handle.close.side_effect = OSError("No space left on device")

            result = record_stream("http://test/stream", "/tmp/test.mp3", lambda: True)

            self.assertFalse(result)
            self.assertEqual(mock_urlopen.call_count, 1)
            mock_sleep.assert_not_called()

    class TestRecordStreamEmptyResponse(unittest.TestCase):
        @patch("time.sleep")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_empty_response_triggers_backoff(self, mock_urlopen, mock_file, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(return_value=b"")
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp

            record_stream("http://test/stream", "/tmp/test.mp3", lambda: True)

            self.assertEqual(mock_urlopen.call_count, 4)
            self.assertEqual(mock_sleep.call_count, 3)
            mock_sleep.assert_any_call(1)
            mock_sleep.assert_any_call(3)
            mock_sleep.assert_any_call(10)

        @patch("time.sleep")
        @patch("builtins.open", new_callable=unittest.mock.mock_open)
        @patch("urllib.request.urlopen")
        def test_empty_response_stops_when_no_longer_live(self, mock_urlopen, mock_file, mock_sleep):
            mock_resp = MagicMock()
            mock_resp.read = MagicMock(return_value=b"")
            mock_resp.close = MagicMock()
            mock_urlopen.return_value = mock_resp

            result = record_stream("http://test/stream", "/tmp/test.mp3", lambda: False)

            self.assertTrue(result)
            self.assertEqual(mock_urlopen.call_count, 1)
            mock_sleep.assert_called_once_with(1)

    class TestRecordingRetryOnInterruption(unittest.TestCase):
        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_retries_recording_when_stream_stays_live(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [True, True, False, False, False, SystemExit("done")]
            mock_notify.return_value = True

            with self.assertRaises(SystemExit):
                run()

            mock_notify.assert_called_once()
            self.assertEqual(mock_record.call_count, 2)

        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_resumes_recording_on_transient_false_negative(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [
                True,
                False, True,
                False, False,
                SystemExit("done"),
            ]
            mock_notify.return_value = True

            with self.assertRaises(SystemExit):
                run()

            mock_notify.assert_called_once()
            self.assertEqual(mock_record.call_count, 2)

        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_does_not_retry_recording_on_storage_error(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [True, False, SystemExit("done")]
            mock_notify.return_value = True
            mock_record.return_value = False

            with self.assertRaises(SystemExit):
                run()

            mock_notify.assert_called_once()
            mock_record.assert_called_once()

    class TestRecordingReentersFromLiveState(unittest.TestCase):
        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_re_enters_recording_after_post_debounce_false_negative(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [
                True,
                False, False,
                True,
                False, False,
                False,
                SystemExit("done"),
            ]
            mock_notify.return_value = True

            with self.assertRaises(SystemExit):
                run()

            mock_notify.assert_called_once()
            self.assertEqual(mock_record.call_count, 2)

    class TestStorageErrorDebounce(unittest.TestCase):
        @patch("time.sleep")
        @patch("os.makedirs")
        @patch("__main__.record_stream")
        @patch("__main__.send_notification")
        @patch("__main__.is_stream_live")
        def test_storage_error_no_renotification_on_single_false(self, mock_is_live, mock_notify, mock_record, mock_makedirs, mock_sleep):
            mock_is_live.side_effect = [True, False, True, SystemExit("done")]
            mock_notify.return_value = True
            mock_record.return_value = False

            with self.assertRaises(SystemExit):
                run()

            mock_notify.assert_called_once()
            mock_record.assert_called_once()

    class TestEnvValidation(unittest.TestCase):
        @patch("__main__.RELAY_SECRET", "")
        def test_missing_relay_secret_exits(self):
            with self.assertRaises(SystemExit) as ctx:
                validate_env()
            self.assertEqual(ctx.exception.code, 1)

        @patch("__main__.RELAY_SECRET", "some-secret")
        def test_valid_relay_secret_passes(self):
            validate_env()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestIsStreamLive, TestIsShowWindow, TestPollInterval, TestSendNotification, TestStep, TestRecordStream, TestRecordStreamStorageErrors, TestRecordStreamEmptyResponse, TestRecordingFilename, TestMainLoopIntegration, TestRecordingRetryOnInterruption, TestRecordingReentersFromLiveState, TestStorageErrorDebounce, TestEnvValidation]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


def validate_env() -> None:
    if not RELAY_SECRET:
        log("RELAY_SECRET env var is required")
        sys.exit(1)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Radio-T stream monitor with notifications and recording")
    parser.add_argument("--test", action="store_true", help="run embedded unit tests")
    args = parser.parse_args()

    if args.test:
        run_tests()
        return

    validate_env()
    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\r\033[K", end="")
        sys.exit(130)
