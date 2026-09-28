"""
WAVE PTX programming dashboard.

A web UI (behind a login) to manage the operational voice prompts and the broadcast
schedule. The scheduler engine reads the same schedule file this app writes, so the
dashboard directly drives what airs on the radios -- no Radio.co needed.

Run:
    pip install -r requirements.txt
    python web/app.py            # http://localhost:8080  (default login: admin / changeme)
"""
import functools
import json
import os

import yaml
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = os.path.join(ROOT, "audio")
SCHEDULE_FILE = os.path.join(ROOT, "config", "schedule.yaml")
USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET", "dev-secret-change-me")


# --- auth ---
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    users = {"admin": generate_password_hash("changeme")}   # first-run default
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f)
    return users


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# --- schedule + media ---
def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("timezone", "America/Chicago")
    data.setdefault("broadcasts", [])
    data.setdefault("prompt_rules", [])
    return data


def save_schedule(data):
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def list_prompts():
    if not os.path.isdir(AUDIO_DIR):
        return []
    return sorted(f for f in os.listdir(AUDIO_DIR)
                  if f.lower().endswith((".mp3", ".wav")))


def parse_time(value):
    value = (value or "").strip().upper()
    if not value:
        return None

    value = value.replace(".", "")
    suffix = ""
    if value.endswith("AM") or value.endswith("PM"):
        suffix = value[-2:]
        value = value[:-2]

    value = value.replace(" ", "")
    if ":" in value:
        hour_text, minute_text = value.split(":", 1)
    else:
        hour_text, minute_text = value, "0"

    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None

    if suffix == "PM" and hour != 12:
        hour += 12
    if suffix == "AM" and hour == 12:
        hour = 0

    return f"{hour:02d}:{minute:02d}"


def normalize_times(value):
    if not value:
        return []

    times = []
    for part in value.splitlines():
        for item in part.split(","):
            item = item.strip()
            if item:
                times.append(item)
    return times


def import_schedule_rules(schedule, rule_entries, audio_name, talkgroup, days):
    if not rule_entries:
        return schedule

    schedule.setdefault("broadcasts", [])
    schedule.setdefault("prompt_rules", [])

    for entry in rule_entries:
        if not entry:
            continue

        if isinstance(entry, dict):
            label = (entry.get("label") or "").strip()
            character = (entry.get("character") or "").strip()
            prompt_type = (entry.get("prompt_type") or "").strip()
            frequency_text = (entry.get("frequency") or "").strip() or "1X A DAY"
            times = normalize_times(entry.get("times") or "")
        else:
            text = str(entry).strip()
            if "|" in text:
                parts = [p.strip() for p in text.split("|") if p and p.strip()]
                if len(parts) >= 4:
                    label = parts[0]
                    character = parts[1]
                    prompt_type = parts[2]
                    frequency_text = parts[3]
                    times = normalize_times(", ".join(parts[4:])) if len(parts) > 4 else []
                else:
                    label = text
                    character = ""
                    prompt_type = ""
                    frequency_text = "1X A DAY"
                    times = []
            else:
                label = text
                character = ""
                prompt_type = ""
                frequency_text = "1X A DAY"
                times = []

                parts = text.split()
                if len(parts) >= 4:
                    time_tokens = []
                    idx = len(parts) - 1
                    while idx >= 0 and parse_time(parts[idx]) is not None:
                        time_tokens.append(parts[idx])
                        idx -= 1
                    if time_tokens:
                        times = list(reversed(time_tokens))
                        remainder = parts[:idx + 1]
                        if remainder:
                            known_chars = {"SARGE", "DOC", "PROFESSOR", "COACH", "TEX"}
                            char_idx = None
                            for pos, token in enumerate(remainder):
                                if token.upper() in known_chars:
                                    char_idx = pos
                                    break
                            if char_idx is not None:
                                label = " ".join(remainder[:char_idx])
                                character = remainder[char_idx].upper()
                                suffix = remainder[char_idx + 1:]
                                if len(suffix) >= 3:
                                    prompt_type = " ".join(suffix[:-3])
                                    frequency_text = " ".join(suffix[-3:])
                                else:
                                    prompt_type = " ".join(suffix)

        if not label:
            continue

        if not times:
            continue

        schedule["prompt_rules"].append({
            "label": label,
            "character": character,
            "prompt_type": prompt_type,
            "frequency": frequency_text,
            "times": times,
            "audio": audio_name,
            "days": days,
            "talkgroup": talkgroup,
        })

    return schedule


def delete_prompt_rule(schedule, idx):
    rules = schedule.get("prompt_rules") or []
    if not isinstance(rules, list):
        return 0

    if not (0 <= idx < len(rules)):
        return 0

    rule = rules[idx]
    rule_label = (rule.get("label") or "").strip()
    rule_character = (rule.get("character") or "").strip()
    rule_prompt_type = (rule.get("prompt_type") or "").strip()
    rule_audio = (rule.get("audio") or "").strip()
    rule_times = [str(t).strip() for t in (rule.get("times") or []) if str(t).strip()]

    remaining_broadcasts = []
    removed_count = 0
    for item in schedule.get("broadcasts", []) or []:
        item_label = (item.get("label") or "").strip()
        item_audio = (item.get("audio") or "").strip()
        item_time = (item.get("time") or "").strip()

        match = True
        if rule_label and item_label and item_label != rule_label:
            match = False
        if match and rule_audio and item_audio and item_audio != rule_audio:
            match = False
        if match and rule_times and item_time and item_time not in rule_times:
            match = False

        if match:
            removed_count += 1
        else:
            remaining_broadcasts.append(item)

    schedule["broadcasts"] = remaining_broadcasts
    del rules[idx]
    return removed_count


# --- routes ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        users = load_users()
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u in users and check_password_hash(users[u], p):
            session["user"] = u
            return redirect(url_for("dashboard"))
        flash("Invalid username or password")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    sched = load_schedule()
    sched.setdefault("broadcasts", [])
    sched.setdefault("prompt_rules", [])
    return render_template("dashboard.html", user=session["user"],
                           schedule=sched, prompts=list_prompts(), days=DAYS)


@app.route("/broadcast", methods=["POST"])
@login_required
def add_broadcast():
    sched = load_schedule()
    picked = request.form.getlist("days")
    days = "all" if (not picked or "all" in picked) else picked
    sched.setdefault("broadcasts", []).append({
        "time": request.form["time"],
        "days": days,
        "audio": request.form["audio"],
        "talkgroup": request.form.get("talkgroup", "all-restaurants"),
        "label": request.form.get("label") or request.form["audio"],
    })
    save_schedule(sched)
    flash("Reminder scheduled")
    return redirect(url_for("dashboard"))


@app.route("/schedule/import", methods=["POST"])
@login_required
def import_schedule():
    sched = load_schedule()
    audio_name = request.form.get("audio_name", "").strip()
    talkgroup = request.form.get("talkgroup", "all-restaurants").strip() or "all-restaurants"
    picked = request.form.getlist("days")
    days = "all" if (not picked or "all" in picked) else picked

    if not audio_name:
        flash("Please choose a prompt file name")
        return redirect(url_for("dashboard"))

    rule_entry = {
        "label": request.form.get("label", "").strip(),
        "character": request.form.get("character", "").strip(),
        "prompt_type": request.form.get("prompt_type", "").strip(),
        "frequency": request.form.get("frequency", "").strip(),
        "times": request.form.get("times", ""),
    }

    import_schedule_rules(sched, [rule_entry], audio_name, talkgroup, days)
    save_schedule(sched)
    flash("Prompt rule saved")
    return redirect(url_for("dashboard"))


@app.route("/broadcast/delete/<int:idx>", methods=["POST"])
@login_required
def delete_broadcast(idx):
    sched = load_schedule()
    items = sched.get("broadcasts", [])
    if 0 <= idx < len(items):
        items.pop(idx)
        save_schedule(sched)
        flash("Reminder removed")
    return redirect(url_for("dashboard"))


@app.route("/prompt-rule/delete/<int:idx>", methods=["POST"])
@login_required
def delete_prompt_rule_route(idx):
    sched = load_schedule()
    before_count = len(sched.get("prompt_rules", []) or [])
    removed = delete_prompt_rule(sched, idx)
    if removed or (0 <= idx < before_count):
        save_schedule(sched)
        flash("Prompt rule removed")
    return redirect(url_for("dashboard"))


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("file")
    if f and f.filename:
        os.makedirs(AUDIO_DIR, exist_ok=True)
        f.save(os.path.join(AUDIO_DIR, secure_filename(f.filename)))
        flash("Prompt uploaded: %s" % f.filename)
    return redirect(url_for("dashboard"))


@app.route("/prompt/delete/<path:filename>", methods=["POST"])
@login_required
def delete_prompt(filename):
    safe_name = secure_filename(filename)
    if safe_name:
        file_path = os.path.join(AUDIO_DIR, safe_name)
        if os.path.exists(file_path):
            os.remove(file_path)
            flash("Prompt removed: %s" % safe_name)
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
