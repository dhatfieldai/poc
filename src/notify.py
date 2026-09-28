import logging
import os
from pathlib import Path

import requests
import yaml

log = logging.getLogger("notify")


def load_settings(config_path=None):
    default_path = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"
    path = Path(config_path).expanduser() if config_path else default_path
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_slack_payload(message, username=None, icon_emoji=None):
    payload = {"text": message}
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    return payload


def send_slack_webhook(webhook_url, message, username=None, icon_emoji=None):
    if not webhook_url:
        return False

    payload = build_slack_payload(message, username=username, icon_emoji=icon_emoji)
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Slack alert failed: %s", exc)
        return False


def send_alert(subject="Alert", body="", settings=None):
    if settings is None:
        settings = load_settings()

    alerts = settings.get("alerts", {}) or {}
    webhook = alerts.get("slack_webhook") or os.environ.get("SLACK_WEBHOOK_URL")
    if webhook:
        message = f"*{subject}*\n{body}"
        return send_slack_webhook(webhook, message, username=alerts.get("slack_username"), icon_emoji=alerts.get("slack_icon_emoji"))

    log.warning("ALERT not delivered (no Slack webhook configured): %s", subject)
    return False
