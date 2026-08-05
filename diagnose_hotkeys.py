#!/usr/bin/env python3
"""Standalone diagnostic for the "hotkeys don't arrive" bug.

Logs to ~/.node_toggle/diagnose.log (not just stderr, which is invisible
inside the packaged .app bundle). Run this both from the terminal
(.venv/bin/python3.13 diagnose_hotkeys.py) and from inside the built app
(see main.py's NODE_TOGGLE_DEBUG hook) to compare TCC-granted permissions
against actual behavior.

Checks, in order:
  1. AXIsProcessTrusted() - Accessibility permission
  2. CGPreflightListenEventAccess() - Input Monitoring permission
  3. pynput's cached keyboard layout (keycode_context) - catches the case
     where the TSM patch cached an empty layout at import time, which
     silently makes every key.char resolve to "" forever after.
  4. A manual CGEventTapCreate with the same parameters pynput uses -
     catches the case where the tap itself fails or is refused.
  5. A real pynput listener for 20s, logging every raw key event (char,
     vk, and what our own get_key_char() resolves it to).

Usage:
    .venv/bin/python3.13 diagnose_hotkeys.py
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOG_DIR = os.path.expanduser("~/.node_toggle")
LOG_PATH = os.path.join(LOG_DIR, "diagnose.log")


def log(msg: str):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"  (failed to write log file: {e})")


def section(title: str):
    log("")
    log(f"=== {title} ===")


def main():
    section(f"Diagnose run (pid={os.getpid()}, argv0={sys.argv[0]})")

    # 1. Accessibility
    section("1. Accessibility (AXIsProcessTrusted)")
    try:
        import ApplicationServices
        trusted = bool(ApplicationServices.AXIsProcessTrusted())
        log(f"AXIsProcessTrusted() = {trusted}")
    except Exception as e:
        log(f"FAILED: {e}")

    # 2. Input Monitoring
    section("2. Input Monitoring (CGPreflightListenEventAccess)")
    try:
        import Quartz
        allowed = bool(Quartz.CGPreflightListenEventAccess())
        log(f"CGPreflightListenEventAccess() = {allowed}")
    except Exception as e:
        log(f"FAILED: {e}")

    # 3. Cached keyboard layout (this is what the TSM patch caches once at import)
    section("3. pynput keyboard layout (keycode_context)")
    try:
        from pynput._util.darwin import keycode_context, keycode_to_string
        with keycode_context() as ctx:
            keyboard_type, layout_data = ctx
            log(f"keyboard_type = {keyboard_type!r}")
            if layout_data is None:
                log("layout_data = None  <-- BAD: UCKeyTranslate will fail, "
                    "every key.char will resolve to ''")
            else:
                log(f"layout_data = {len(layout_data)} bytes (looks OK)")
                # Sanity: translate keycode 0 (which is 'a' on a US layout)
                try:
                    s = keycode_to_string(ctx, 0)
                    log(f"keycode_to_string(ctx, 0) = {s!r} (expect 'a' on US layout)")
                except Exception as e:
                    log(f"keycode_to_string FAILED: {e}")
    except Exception as e:
        log(f"FAILED: {e}")

    # 4. Manual event tap creation, same params pynput's ListenerMixin uses
    section("4. Manual CGEventTapCreate")
    try:
        from Quartz import (
            CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly, CGEventMaskBit, kCGEventKeyDown,
            kCGEventKeyUp, kCGEventFlagsChanged,
        )
        events = (
            CGEventMaskBit(kCGEventKeyDown)
            | CGEventMaskBit(kCGEventKeyUp)
            | CGEventMaskBit(kCGEventFlagsChanged)
        )

        def _noop_handler(proxy, event_type, event, refcon):
            return event

        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            events,
            _noop_handler,
            None,
        )
        if tap is None:
            log("CGEventTapCreate returned None  <-- BAD: no permission or "
                "tap refused by the system")
        else:
            log("CGEventTapCreate succeeded (tap is not None)")
    except Exception as e:
        log(f"FAILED: {e}")

    # 5. Real listener for 20s, log every raw event
    section("5. Live pynput listener (20s) - press some keys now")
    try:
        from pynput import keyboard
        import hotkey_manager as hm  # imports patch _patch_pynput_tsm as a side effect

        event_count = [0]

        def on_press(key):
            event_count[0] += 1
            char = getattr(key, "char", None)
            vk = getattr(key, "vk", None)
            resolved = hm.get_key_char(key)
            log(f"PRESS  key={key!r} char={char!r} vk={vk!r} "
                f"get_key_char()={resolved!r}")

        def on_release(key):
            pass

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        log("Listener started, waiting 20s for key events...")
        time.sleep(20)
        listener.stop()
        log(f"Total key-down events received: {event_count[0]}")
        if event_count[0] == 0:
            log("No events arrived  <-- points to branch A (nothing arriving)")
        else:
            log("Events arrived, check whether get_key_char() resolved to "
                "None above -> branch B (arriving but discarded)")
    except Exception as e:
        log(f"FAILED: {e}")

    section("Diagnose run complete")
    log(f"Full log at: {LOG_PATH}")


if __name__ == "__main__":
    main()
