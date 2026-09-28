# import atexit
# import os
# import sys
# import time

# import sounddevice as sd
# import soundfile as sf
# from playwright.sync_api import sync_playwright

# from src.notify import send_alert

# from scipy.signal import resample_poly
# import numpy as np

# PRE_ROLL_SECONDS = 0.3
# POST_ROLL_SECONDS = 0.3

# CDP_URL = "http://127.0.0.1:9222"
# TARGET_URL = "https://wds.poc01.waveoncloud.com/WebDispatcher/v12/index.html"

# _playwright = None
# _browser = None
# _page = None


# def _get_or_create_page():
#     global _playwright, _browser, _page

#     if _page is not None and not getattr(_page, "is_closed", lambda: False)():
#         return _page

#     if _playwright is None:
#         _playwright = sync_playwright().start()

#     if _browser is None:
#         try:
#             _browser = _playwright.chromium.connect_over_cdp(CDP_URL)
#         except Exception as exc:
#             raise RuntimeError(
#                 f"Could not attach to Chrome via CDP at {CDP_URL}. Start Chrome with "
#                 '--remote-debugging-port=9222 and --user-data-dir="C:\\chrome-automation-profile".'
#             ) from exc

#     if _browser.contexts:
#         context = _browser.contexts[0]
#     else:
#         context = _browser.new_context()

#     pages = context.pages
#     if pages:
#         _page = pages[0]
#     else:
#         _page = context.new_page()

#     if _page.url != TARGET_URL and not _page.url.startswith("about:"):
#         _page.goto(TARGET_URL)

#     return _page


# def close_browser():
#     global _playwright, _browser, _page

#     _page = None
#     _browser = None

#     if _playwright is not None:
#         _playwright.stop()
#         _playwright = None


# atexit.register(close_browser)


# def resolve_audio_path(filename):
#     if not filename:
#         raise ValueError("Audio filename is required")

#     if os.path.isabs(filename):
#         return filename

#     base_dir = os.path.dirname(os.path.abspath(__file__))
#     workspace_root = os.path.dirname(base_dir)
#     audio_dir = os.path.join(workspace_root, "audio")
#     candidate = os.path.join(audio_dir, filename)

#     if os.path.exists(candidate):
#         return candidate

#     return candidate


# def find_call_button(page):
#     button = page.locator("#CA-CallIconId")
#     if button.count() == 0:
#         raise RuntimeError("Could not find button with id CA-CallIconId")
#     return button.first


# def press_call_button(page):
#     button = find_call_button(page)
#     button.scroll_into_view_if_needed()
#     box = button.bounding_box()
#     if not box:
#         raise RuntimeError("Could not determine button position")

#     x = box["x"] + box["width"] / 2
#     y = box["y"] + box["height"] / 2
#     page.mouse.move(x, y)
#     page.mouse.down()
#     return button


# def release_call_button(page):
#     page.mouse.up()


# def play_audio_file(filename, device_index, page=None):
#     audio_path = resolve_audio_path(filename)
#     if not os.path.exists(audio_path):
#         send_alert("Fail", f"File Not Existed: {filename}")
#         raise FileNotFoundError(f"Audio file not found: {audio_path}")

#     if page is None:
#         page = _get_or_create_page()

#     devices = sd.query_devices()
#     dev = devices[device_index]
#     print(f"Using device {device_index}: {dev['name']} ({dev['hostapi']})")

#     data, samplerate = sf.read(audio_path, dtype='float32')
#     button = press_call_button(page)
#     time.sleep(PRE_ROLL_SECONDS)

#     try:
#         sd.play(data, samplerate, device=device_index)
#         sd.wait()
#         print("Playback done.")
#     finally:
#         time.sleep(POST_ROLL_SECONDS)
#         release_call_button(page)


# if __name__ == "__main__":
#     if len(sys.argv) < 3:
#         print("Usage: python -m src.playwrite_audio_play <audio_file> <device_index>")
#         sys.exit(1)

#     play_audio_file(sys.argv[1], int(sys.argv[2]))
import atexit
import os
import sys
import time
from math import gcd

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly
from playwright.sync_api import sync_playwright

from src.notify import send_alert

PRE_ROLL_SECONDS = 0.3
POST_ROLL_SECONDS = 0.3

TARGET_SAMPLE_RATE = 48000
TARGET_CHANNELS = 2

CDP_URL = "http://127.0.0.1:9222"
TARGET_URL = "https://wds.poc01.waveoncloud.com/WebDispatcher/v12/index.html"

_playwright = None
_browser = None
_page = None


def _get_or_create_page():
    global _playwright, _browser, _page

    if _page is not None and not getattr(_page, "is_closed", lambda: False)():
        return _page

    if _playwright is None:
        _playwright = sync_playwright().start()

    if _browser is None:
        try:
            _browser = _playwright.chromium.connect_over_cdp(CDP_URL)
        except Exception as exc:
            raise RuntimeError(
                f"Could not attach to Chrome via CDP at {CDP_URL}. Start Chrome with "
                '--remote-debugging-port=9222 and --user-data-dir="C:\\chrome-automation-profile".'
            ) from exc

    context = _browser.contexts[0] if _browser.contexts else _browser.new_context()

    # Prefer an existing WAVE Dispatcher page
    for page in context.pages:
        if TARGET_URL in page.url or "waveoncloud.com/WebDispatcher" in page.url:
            _page = page
            return _page

    _page = context.pages[0] if context.pages else context.new_page()

    if _page.url != TARGET_URL:
        _page.goto(TARGET_URL, wait_until="domcontentloaded")

    return _page


def close_browser():
    global _playwright, _browser, _page

    _page = None
    _browser = None

    if _playwright is not None:
        _playwright.stop()
        _playwright = None


atexit.register(close_browser)


def resolve_audio_path(filename):
    if not filename:
        raise ValueError("Audio filename is required")

    if os.path.isabs(filename):
        return filename

    base_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_root = os.path.dirname(base_dir)
    audio_dir = os.path.join(workspace_root, "audio")
    return os.path.join(audio_dir, filename)


def list_output_devices():
    devices = sd.query_devices()

    print("\nAvailable output devices:")
    for index, device in enumerate(devices):
        if device["max_output_channels"] > 0:
            print(
                f"{index}: {device['name']} | "
                f"outputs={device['max_output_channels']} | "
                f"default_sr={device['default_samplerate']}"
            )
    print()


def validate_output_device(device_index):
    devices = sd.query_devices()

    if device_index < 0 or device_index >= len(devices):
        list_output_devices()
        raise ValueError(f"Invalid device index: {device_index}")

    device = devices[device_index]

    if device["max_output_channels"] <= 0:
        list_output_devices()
        raise ValueError(
            f"Selected device {device_index} is not an output device: {device['name']}"
        )

    print(
        f"Using output device {device_index}: {device['name']} | "
        f"default_sr={device['default_samplerate']} | "
        f"max_output_channels={device['max_output_channels']}"
    )

    return device


def prepare_audio_for_device(data, samplerate):
    """
    Normalize audio for Windows shared-mode playback:
    - float32
    - 48000 Hz
    - stereo
    - contiguous memory
    """

    if data.ndim == 1:
        data = data.reshape(-1, 1)

    # If more than 2 channels, keep first 2 only
    if data.shape[1] > TARGET_CHANNELS:
        data = data[:, :TARGET_CHANNELS]

    # Convert mono to stereo
    if data.shape[1] == 1 and TARGET_CHANNELS == 2:
        data = np.repeat(data, 2, axis=1)

    # Resample to 48000 Hz if needed
    if samplerate != TARGET_SAMPLE_RATE:
        print(f"Resampling audio from {samplerate} Hz to {TARGET_SAMPLE_RATE} Hz")

        common = gcd(int(samplerate), int(TARGET_SAMPLE_RATE))
        up = TARGET_SAMPLE_RATE // common
        down = samplerate // common

        data = resample_poly(data, up, down, axis=0)

    data = data.astype("float32", copy=False)
    data = np.ascontiguousarray(data)

    return data, TARGET_SAMPLE_RATE


def find_call_button(page):
    button = page.locator("#CA-CallIconId")

    if button.count() == 0:
        raise RuntimeError("Could not find button with id CA-CallIconId. Dispatch is logged out now.")

    return button.first


def press_call_button(page):
    button = find_call_button(page)
    button.scroll_into_view_if_needed()

    box = button.bounding_box()
    if not box:
        raise RuntimeError("Could not determine call button position")

    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2

    page.mouse.move(x, y)
    page.mouse.down()

    return button


def release_call_button(page):
    try:
        page.mouse.up()
    except Exception as exc:
        print(f"Warning: failed to release call button: {exc}")


def play_audio_file(filename, device_index, page=None):
    audio_path = resolve_audio_path(filename)

    if not os.path.exists(audio_path):
        send_alert("Fail", f"File Not Existed: {filename}")
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    validate_output_device(device_index)

    print(f"Loading audio file: {audio_path}")
    data, samplerate = sf.read(audio_path, dtype="float32")
    print(f"Original audio: samplerate={samplerate}, shape={data.shape}")

    data, samplerate = prepare_audio_for_device(data, samplerate)
    channels = data.shape[1]

    print(f"Prepared audio: samplerate={samplerate}, channels={channels}, shape={data.shape}")

    # Check output compatibility before pressing PTT
    try:
        sd.check_output_settings(
            device=device_index,
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
        )
    except Exception as exc:
        list_output_devices()
        raise RuntimeError(
            f"Selected output device cannot play {samplerate} Hz / {channels} channels. "
            f"Try another output device or confirm Windows sound format is 48000 Hz."
        ) from exc

    if page is None:
        page = _get_or_create_page()

    button_pressed = False

    try:
        press_call_button(page)
        button_pressed = True

        time.sleep(PRE_ROLL_SECONDS)

        sd.play(
            data,
            samplerate,
            device=device_index,
            blocking=True,
        )

        print("Playback done.")

    except Exception as exc:
        send_alert("Fail", f"Audio playback failed: {exc}")
        raise

    finally:
        time.sleep(POST_ROLL_SECONDS)

        if button_pressed:
            release_call_button(page)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python -m src.playwrite_audio_play <audio_file> <device_index>")
        print()
        list_output_devices()
        sys.exit(1)

    audio_file = sys.argv[1]
    device_index = int(sys.argv[2])

    play_audio_file(audio_file, device_index)