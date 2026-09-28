import os
import sys

import sounddevice as sd
import soundfile as sf
import pyautogui
import time

from src.notify import send_alert

PRIMARY_BUTTON_IMAGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "primary_button.png",
)
PRE_ROLL_SECONDS = 0.3
POST_ROLL_SECONDS = 0.3
MATCH_CONFIDENCE = 0.8


def resolve_audio_path(filename):
    if not filename:
        raise ValueError("Audio filename is required")

    if os.path.isabs(filename):
        return filename

    base_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_root = os.path.dirname(base_dir)
    audio_dir = os.path.join(workspace_root, "audio")
    candidate = os.path.join(audio_dir, filename)

    if os.path.exists(candidate):
        return candidate

    return candidate


def list_devices():
    print(sd.query_devices())


def find_primary_button():
    try:
        location = pyautogui.locateCenterOnScreen(
            PRIMARY_BUTTON_IMAGE, confidence=MATCH_CONFIDENCE
        )
    except TypeError:
        location = pyautogui.locateCenterOnScreen(PRIMARY_BUTTON_IMAGE)

    if location is None:
        raise RuntimeError(
            f"Could not find '{PRIMARY_BUTTON_IMAGE}' on screen."
        )
    return location


def press_primary_button():
    x, y = find_primary_button()
    pyautogui.mouseDown(x, y)
    print(f"Pressed and holding Primary button at ({x}, {y}).")
    return x, y


def release_primary_button(x, y):
    pyautogui.mouseUp(x, y)
    print(f"Released Primary button at ({x}, {y}).")


def play_audio_file(filename, device_index):
    audio_path = resolve_audio_path(filename)
    if not os.path.exists(audio_path):
        send_alert("Fail", f"File Not Existed: {filename}")
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    devices = sd.query_devices()
    dev = devices[device_index]
    print(f"Using device {device_index}: {dev['name']} ({dev['hostapi']})")

    data, samplerate = sf.read(audio_path, dtype='float32')
    x, y = press_primary_button()
    time.sleep(PRE_ROLL_SECONDS)

    try:
        sd.play(data, samplerate, device=device_index)
        sd.wait()
        print("Playback done.")
    finally:
        time.sleep(POST_ROLL_SECONDS)
        release_primary_button(x, y)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.audio_player <audio_file> <device_index>")
        list_devices()
        sys.exit(1)

    play_audio_file(sys.argv[1], int(sys.argv[2]))
