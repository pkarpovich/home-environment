# Radio-T Monitor Consolidation

## Overview

Merge two existing scripts (`radio-t-checker.py` and `radio-t-recorder.py`) into a single `radio-t-monitor.py` that simultaneously sends push notifications and records the stream. Fix bugs that caused checker to send false-positive "Radio-T stream is live!" notifications all last week when no stream was active.

**Root bugs:**
1. `is_stream_live()` uses HEAD requests, but after Radio-T's migration to Hetzner the server returns `400 Bad Request` on HEAD (instead of `404`). The check `e.code != 404` treats 400 as "stream live".
2. Logic `resp.status != 404` treats any 2xx/3xx/5xx response as live — fragile, breaks on 503/redirects.
3. No read timeout in recorder — if stream hangs without closing the connection, recording blocks indefinitely.
4. No debounce: a single network error flips LIVE→IDLE, next positive check sends a duplicate notification.
5. Two processes duplicate polls (2 HEAD requests every 30s during show window).

**Benefits of merging:**
- One poll instead of two → half the traffic to Radio-T server.
- Single source of truth for stream state.
- Unified debounce and reconnect logic.

## Context (from discovery)

**Files:**
- `scripts/radio-t-checker.py` — existing checker with notifications (to be deleted)
- `scripts/radio-t-recorder.py` — existing recorder (to be deleted)
- `scripts/radio-t-monitor.py` — new merged script

**Duplicated code across both scripts:**
- `is_stream_live(url)` — identical implementations
- `is_show_window(now)` — identical
- `poll_interval(now)` — identical
- `log(msg)` — identical
- Constants: `STATE_IDLE`, `POLL_ACTIVE=30`, `POLL_PASSIVE=900`

**Server diagnostics (2026-04-04, after broadcast ended):**
- `GET /` → `404` (correct)
- `HEAD /` → `400 Bad Request` (source of the bug)
- `GET /` during broadcast → `200` + audio/mpeg stream

**Env vars (from existing scripts):**
- `STREAM_URL` (default: `https://stream.radio-t.com/`)
- `RELAY_URL` (default: `https://relay.pkarpovich.space/send`)
- `RELAY_SECRET` (required)
- `RECORDING_DIR` (default: `/mnt/nas/radio-t`)

## Development Approach

- **Testing approach**: Regular (code first, tests within the same task)
- Each task ends with writing tests and making them pass
- Stdlib-only: `urllib.request`, `unittest`, `threading.Event` — matching the existing scripts (no new dependencies)
- Python 3.12+, type hints everywhere, early return pattern, no globals
- Tests mock `urllib.request.urlopen`

## Testing Strategy

- **Unit tests**: embedded in the script via `--test` flag (matches existing style)
- Mocks only for `urllib.request.urlopen` and filesystem
- Coverage: success, 404, 400, 5xx, timeout, network error, debounce, reconnect

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## Implementation Steps

### Task 1: Script skeleton + fixed `is_stream_live`

- [x] Create `scripts/radio-t-monitor.py` with module docstring, imports, env-based config
- [x] Define constants: `STATE_IDLE`, `STATE_LIVE`, `POLL_ACTIVE=30`, `POLL_PASSIVE=900`, `POLL_LIVE=300`, `USER_AGENT`
- [x] Implement `is_stream_live(url)`: **GET** instead of HEAD, check `200 <= status < 300`, close response without reading body, User-Agent header, timeout=10s
- [x] Implement `log(msg)` (with UTC timestamp)
- [x] Write tests: `test_live_200`, `test_not_live_404`, `test_not_live_400_bad_request` (regression for Hetzner bug), `test_not_live_500`, `test_not_live_timeout`, `test_not_live_network_error`
- [x] Run `python radio-t-monitor.py --test` — all tests pass

### Task 2: State machine with debounce

- [x] Implement `run()` with `IDLE`/`LIVE` state and `miss_count` counter
- [x] LIVE→IDLE transition only after **N=2 consecutive** negative checks (debounce against network glitches)
- [x] IDLE→LIVE on first positive check (fast detection of broadcast start)
- [x] Extract `is_show_window(now)` and `poll_interval(now)` (logic identical to existing)
- [x] Write tests: `test_idle_to_live_on_first_positive`, `test_live_to_idle_requires_two_misses`, `test_single_miss_does_not_flap`, `test_debounce_resets_on_positive`
- [x] Run tests — pass

### Task 3: Notification with retry

- [x] Implement `send_notification(message, relay_url, secret)`: POST JSON `{"message": ...}` with `x-secret` header
- [x] Retry with exponential backoff: 3 attempts, delays 1s, 3s (after each failed attempt)
- [x] Catch-and-log: if all 3 attempts fail — log only, do not crash
- [x] Write tests: `test_notification_success_first_try`, `test_notification_retries_on_failure`, `test_notification_gives_up_after_three_attempts`, `test_notification_payload_format`
- [x] Run tests — pass

### Task 4: Stream recording with reconnect

- [x] Implement `record_stream(url, filepath, is_live_fn)`: open GET stream, write chunks to file in `"ab"` mode, log size every 30s
- [x] Read timeout = 30s (in urlopen), on socket.timeout / ConnectionError — **reconnect loop** with backoff (1s, 3s, 10s)
- [x] Between reconnect attempts call `is_live_fn()` — if `False`, stop recording and return control
- [x] After 3 failed reconnects in a row — treat stream as ended
- [x] Write tests: `test_writes_chunks_to_file`, `test_reconnects_on_connection_error_while_live`, `test_stops_recording_when_no_longer_live`, `test_gives_up_after_three_failed_reconnects`, `test_appends_to_existing_file`
- [x] Run tests — pass

### Task 5: Main loop integration

- [x] On IDLE→LIVE transition in `run()`: call `send_notification()` + fix `recording_filename` at detection moment + create `RECORDING_DIR` + call `record_stream()` (blocking)
- [x] After `record_stream` returns: apply debounce logic for final IDLE transition
- [x] `recording_filename(now)` produces `radio-t-YYYY-MM-DD.mp3` from UTC detection date (fixed once per broadcast)
- [x] Write tests: `test_full_cycle_idle_to_live_to_idle`, `test_notification_sent_on_transition`, `test_filename_fixed_at_detection_time`
- [x] Run tests — pass

### Task 6: CLI + remove old scripts

- [ ] Add `main()` with argparse: `--test` flag to run embedded tests
- [ ] KeyboardInterrupt handling (matches existing scripts)
- [ ] Validate required env vars (RELAY_SECRET) with clear error
- [ ] Delete `scripts/radio-t-checker.py` and `scripts/radio-t-recorder.py`
- [ ] Run `python radio-t-monitor.py --test` — full test suite passes

### Task 7: Update turtle-harbor `scripts.yml`

- [ ] Remove `radio-t-checker` and `radio-t-recorder` entries from `scripts.yml`
- [ ] Add single `radio-t-monitor` entry mirroring their config (context: `./scripts`, venv, env_file, `PYTHONUNBUFFERED=1`, `restart_policy: always`, `max_restarts: 5`)
- [ ] Verify `.env` already contains `RELAY_SECRET` and `RECORDING_DIR` (both previously used by old scripts); add them if missing
- [ ] No tests needed — config-only change

### Task 8: Verify acceptance criteria

- [ ] All tests pass
- [ ] `is_stream_live` correctly returns `False` for statuses 404, 400, 5xx
- [ ] Debounce prevents false LIVE→IDLE transitions on network glitches
- [ ] Reconnect correctly recovers from connection drops during broadcast
- [ ] Recording filename remains stable throughout a broadcast
- [ ] Old scripts removed, services switched to new script

## Technical Details

**New `is_stream_live`:**
```python
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
```

**State machine with debounce (pseudocode):**
```
state = IDLE
miss_count = 0
while True:
    live = is_stream_live(url)
    match (state, live):
        case (IDLE, True):
            send_notification(...)
            filename = recording_filename(now)
            record_stream(url, filename, is_live_fn)
            state = LIVE; miss_count = 0
        case (LIVE, False):
            miss_count += 1
            if miss_count >= 2:
                state = IDLE; miss_count = 0
        case (LIVE, True):
            miss_count = 0
    sleep(poll_interval())
```

Reconnect happens **inside** `record_stream`, so the main loop only reaches the `LIVE` post-state after the broadcast ends.

**Reconnect backoff:** `[1, 3, 10]` seconds, counter resets on successful connection.

## Post-Completion

**Manual verification:**
- Run on broadcast day (Saturday ~22:00 MSK) — confirm notification arrives once, recording writes to file
- Confirm script is silent outside show window (no false notifications)
- Check logs for notification retry attempts if relay is temporarily unavailable

**External system updates:**
- If script runs under systemd/launchd/supervisord — update unit file with new `radio-t-monitor.py` path
- If launched via turtle-harbor (check `scripts.yml` at project root) — update config
