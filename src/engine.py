"""Simple broadcast engine that refreshes the YAML schedule in the background and triggers playback when the clock matches a scheduled time."""
import copy
import logging
import os
import sys
import threading
import time
from datetime import datetime

import yaml

# from src.audio_player import play_audio_file
from src.playwrite_audio_play import play_audio_file
from src.notify import send_alert

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("engine")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DAY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
_tz_warned = set()


class ScheduleStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.schedule = {}

    def refresh(self):
        try:
            loaded = load_yaml(self.path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not reload schedule: %s", exc)
            return False

        with self.lock:
            self.schedule = loaded
        return True

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.schedule)


def resolve_path(path, fallback_relative, base_dir=None):
    candidates = []
    base_dir = base_dir or PROJECT_ROOT

    if path:
        text = str(path).strip()
        if text:
            candidates.append(text)
            if not os.path.isabs(text):
                candidates.append(os.path.join(base_dir, text))
                candidates.append(os.path.join(PROJECT_ROOT, text))
            if text.startswith(("C:/wave-poc", "C:\\wave-poc")):
                candidates.append(text.replace("C:/wave-poc", PROJECT_ROOT).replace("C:\\wave-poc", PROJECT_ROOT))

    candidates.append(os.path.join(PROJECT_ROOT, fallback_relative))
    if base_dir and base_dir != PROJECT_ROOT:
        candidates.append(os.path.join(base_dir, fallback_relative))

    for candidate in candidates:
        if not candidate:
            continue
        if not os.path.isabs(candidate):
            candidate = os.path.join(PROJECT_ROOT, candidate)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(PROJECT_ROOT, fallback_relative)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def normalize_time(value):
    if value is None:
        return None

    text = str(value).strip().replace(".", "")
    if not text:
        return None

    suffix = ""
    if text.upper().endswith("AM") or text.upper().endswith("PM"):
        suffix = text[-2:].upper()
        text = text[:-2].strip()

    if not text or ":" not in text:
        return None

    hour_text, minute_text = text.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None

    if suffix == "PM" and hour != 12:
        hour += 12
    if suffix == "AM" and hour == 12:
        hour = 0

    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None

    return f"{hour:02d}:{minute:02d}"


def now_in_tz(tzname):
    if tzname and ZoneInfo:
        try:
            return datetime.now(ZoneInfo(tzname))
        except Exception:  # noqa: BLE001
            if tzname not in _tz_warned:
                log.warning("Timezone %r unavailable - using system local", tzname)
                _tz_warned.add(tzname)
    return datetime.now()


def due_now(item, now):
    scheduled_time = normalize_time(item.get("time"))
    if scheduled_time != now.strftime("%H:%M"):
        return False
    days = item.get("days", "all")
    if days == "all":
        return True
    return _DAY[now.weekday()] in [d.lower() for d in days]


def expand_prompt_rules(schedule):
    items = []
    for rule in schedule.get("prompt_rules", []) or []:
        if not isinstance(rule, dict):
            continue
        times = rule.get("times") or []
        if isinstance(times, str):
            times = [times]
        for time_value in times:
            parsed = normalize_time(time_value)
            if not parsed:
                continue
            item = {
                "time": parsed,
                "days": rule.get("days", "all"),
                "audio": rule.get("audio"),
                "talkgroup": rule.get("talkgroup", "all-restaurants"),
                "label": rule.get("label") or rule.get("audio"),
                "character": rule.get("character"),
                "prompt_type": rule.get("prompt_type"),
            }
            items.append(item)
    return items


def run(settings_path="config/settings.yaml"):
    settings_path = resolve_path(settings_path, "config/settings.yaml")
    settings = load_yaml(settings_path)
    schedule_path = resolve_path(
        settings.get("schedule_file"),
        "config/schedule.yaml",
        base_dir=os.path.dirname(settings_path),
    )
    store = ScheduleStore(schedule_path)
    store.refresh()

    stop_event = threading.Event()

    def refresh_loop():
        while not stop_event.is_set():
            store.refresh()
            stop_event.wait(20)

    refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
    refresh_thread.start()

    last_fired = set()
    log.info("Engine started; refresh every 20 seconds, check every second")

    while True:
        sched = store.snapshot()
        now = now_in_tz(sched.get("timezone"))
        minute_key = now.strftime("%Y-%m-%d %H:%M")

        runtime_items = list(sched.get("broadcasts", [])) + expand_prompt_rules(sched)
        for item in runtime_items:
            fire_id = "%s|%s" % (minute_key, item.get("label", item.get("audio")))
            if fire_id in last_fired or not due_now(item, now):
                continue

            last_fired.add(fire_id)
            audio_name = item.get("audio")
            if not audio_name:
                continue

            try:
                log.info("Scheduled time %s matched; running audio now: %s", item.get("time"), audio_name)
                play_audio_file(audio_name, 13)
                log.info("Played %s at %s", audio_name, item.get("time"))
            except Exception as exc:  # noqa: BLE001
                send_alert("Fail", f"Playback error: {exc}")

        if len(last_fired) > 500:
            last_fired = set(list(last_fired)[-200:])
        time.sleep(1)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "config/settings.yaml")
