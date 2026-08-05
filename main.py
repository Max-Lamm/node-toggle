#!/usr/bin/env python3
"""maxlamm Node Toggle - DaVinci Resolve Node Toggle with configurable hotkeys.

Usage:
    cd node_toggle
    .venv/bin/python3.13 main.py
"""

import sys
import os

# Ensure we can import sibling modules when run from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk

from data_model import load_config, save_config
from resolve_api import ResolveConnection
from hotkey_manager import HotkeyManager
from ui import NodeToggleApp

# Dark mode by default
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def main():
    # Load saved config
    profile = load_config()

    # Initialize Resolve connection
    resolve_conn = ResolveConnection()
    resolve_conn.connect()
    resolve_conn.refresh_context()

    # Build UI
    root = ctk.CTk()
    app = NodeToggleApp(root, resolve_conn, profile)
    app.update_status_bar()

    # Hotkey callbacks
    def apply_hotkey(combo: str):
        """Runs on the main thread via the event queue."""
        assignment = app.profile.get_by_hotkey(combo)
        if assignment and assignment.node_index > 0:
            # Toggle: flip internal state and apply
            assignment._toggle_state = not assignment._toggle_state
            resolve_conn.toggle_node(
                assignment.level, assignment.node_index, assignment._toggle_state
            )

    def on_hotkey(combo: str):
        """Called when a valid hotkey press is detected (from listener thread).

        Must not call into Resolve's scripting API here: a slow response
        can block the CGEventTap callback long enough for macOS to
        silently disable the tap.
        """
        app.schedule_ui_update(apply_hotkey, combo)

    def on_record(combo: str):
        """Called when a key combo is captured during recording (from listener thread)."""
        app.schedule_ui_update(app.finish_hotkey_recording, combo)

    # Initialize hotkey manager
    hotkey_mgr = HotkeyManager(on_hotkey=on_hotkey, on_record=on_record)
    app.hotkey_mgr = hotkey_mgr

    # Link recording state between UI and hotkey manager
    original_start_recording = app.start_hotkey_recording

    def patched_start_recording(row):
        original_start_recording(row)
        hotkey_mgr.recording = True

    app.start_hotkey_recording = patched_start_recording

    original_finish = app.finish_hotkey_recording

    def patched_finish(combo):
        hotkey_mgr.recording = False
        original_finish(combo)

    app.finish_hotkey_recording = patched_finish

    # Start hotkey listener
    hotkey_mgr.start()

    # Periodic connection polling
    def poll_connection():
        was_connected = resolve_conn.connected
        if not was_connected:
            resolve_conn.connect()
        resolve_conn.refresh_context()
        app.update_status_bar()
        if resolve_conn.connected and not was_connected:
            for row in app._rows:
                row._refresh_nodes()
                if row.assignment.node_label:
                    row._select_node_by_label(row.assignment.node_label)
        root.after(3000, poll_connection)

    root.after(3000, poll_connection)

    # Run
    try:
        root.mainloop()
    finally:
        hotkey_mgr.stop()
        save_config(profile)


if __name__ == "__main__":
    main()
