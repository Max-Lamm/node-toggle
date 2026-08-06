"""Global hotkey capture and typing detection for macOS."""

import os
import sys
import time
import threading
from datetime import datetime
from typing import Callable, Optional

from pynput import keyboard

# Set NODE_TOGGLE_DEBUG=1 to log every raw key event and a startup
# permissions/layout snapshot to ~/.node_toggle/diagnose.log. stderr is
# invisible inside the packaged .app bundle, so this writes to a file
# instead. See diagnose_hotkeys.py for the standalone version of these
# same checks.
_DEBUG = os.environ.get("NODE_TOGGLE_DEBUG") == "1"
_DEBUG_LOG_PATH = os.path.expanduser("~/.node_toggle/diagnose.log")

# Set by the tap-recovery patch below once CGEventTapCreate has actually
# been called. None until the listener has tried to create a tap.
_event_tap_created: Optional[bool] = None


def _debug_log(msg: str, force: bool = False):
    if not _DEBUG and not force:
        return
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    try:
        os.makedirs(os.path.dirname(_DEBUG_LOG_PATH), exist_ok=True)
        with open(_DEBUG_LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, file=sys.stderr)

# macOS 15+ requires TISGetInputSourceProperty on the main thread.
# Patch pynput to pre-fetch the keyboard layout here (import = main thread)
# so the background listener thread never calls it.
def _patch_pynput_tsm():
    try:
        from pynput._util.darwin import keycode_context, ListenerMixin
        from pynput.keyboard import _darwin as _kb_darwin

        _cached = [None]
        with keycode_context() as ctx:
            _cached[0] = ctx

        def _patched_run(self):
            self._context = _cached[0]
            try:
                ListenerMixin._run(self)
            finally:
                self._context = None

        _kb_darwin.Listener._run = _patched_run
    except Exception as e:
        # Non-macOS or pynput internals changed; fall back to default
        print(f"[hotkey] pynput TSM patch skipped: {e}", file=sys.stderr)

_patch_pynput_tsm()


# macOS silently disables an event tap (kCGEventTapDisabledByTimeout /
# ByUserInput) if its callback doesn't return quickly enough, e.g. under
# system load. pynput 1.8.2 never re-enables it: the listener thread stays
# alive in its run loop, but no key event is ever delivered again until the
# process is relaunched. This is indistinguishable from "hotkeys are dead"
# without a live process inspection. Patch tap creation to remember the tap
# reference, and the handler to re-enable it when the OS disables it.
def _patch_pynput_tap_recovery():
    try:
        from pynput._util.darwin import ListenerMixin
        from Quartz import (
            kCGEventTapDisabledByTimeout,
            kCGEventTapDisabledByUserInput,
            CGEventTapEnable,
        )

        _disabled_events = (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput)

        _original_create_event_tap = ListenerMixin._create_event_tap

        def _patched_create_event_tap(self):
            tap = _original_create_event_tap(self)
            self._node_toggle_cg_tap = tap
            global _event_tap_created
            _event_tap_created = tap is not None
            return tap

        ListenerMixin._create_event_tap = _patched_create_event_tap

        _original_handler = ListenerMixin._handler

        def _patched_handler(self, proxy, event_type, event, refcon):
            if event_type in _disabled_events:
                tap = getattr(self, "_node_toggle_cg_tap", None)
                if tap is not None:
                    try:
                        CGEventTapEnable(tap, True)
                        _debug_log(f"[hotkey] event tap disabled (type={event_type}), re-enabled")
                    except Exception as e:
                        _debug_log(f"[hotkey] failed to re-enable event tap: {e}")
                else:
                    _debug_log(f"[hotkey] event tap disabled (type={event_type}) but no tap reference")
                return None
            return _original_handler(self, proxy, event_type, event, refcon)

        ListenerMixin._handler = _patched_handler
    except Exception as e:
        print(f"[hotkey] pynput tap-recovery patch skipped: {e}", file=sys.stderr)

_patch_pynput_tap_recovery()


def _import_ax_module():
    """Import whichever module exposes the AX* symbols in this environment.

    The packaged .app bundle only ships HIServices as a compiled .so;
    ApplicationServices is a pure-Python shim around it (plus CoreText/Quartz)
    that resolves its symbols lazily via objc.createFrameworkDirAndGetattr,
    so it's tried second rather than assumed present.
    """
    for module_name in ("HIServices", "ApplicationServices"):
        try:
            return __import__(module_name)
        except Exception as e:
            _debug_log(f"[hotkey] import {module_name} failed: {e}", force=True)
    return None


def is_accessibility_trusted() -> Optional[bool]:
    """Check if this process has macOS Accessibility permission.

    Returns True/False for a real permission result, or None if the check
    itself couldn't run (e.g. the AX module failed to import) — that case
    must not be reported to the user as "permission missing".
    """
    mod = _import_ax_module()
    if mod is None:
        return None
    try:
        return bool(mod.AXIsProcessTrusted())
    except Exception as e:
        print(f"[hotkey] AXIsProcessTrusted check failed: {e}", file=sys.stderr)
        _debug_log(f"[hotkey] AXIsProcessTrusted check failed: {e}", force=True)
        return None


def is_input_monitoring_allowed() -> Optional[bool]:
    """Check if this process has macOS Input Monitoring permission.

    pynput's global key listener relies on a Quartz event tap, which needs
    this permission (separate from Accessibility). Returns None if the
    check itself couldn't run.
    """
    try:
        import Quartz
        return bool(Quartz.CGPreflightListenEventAccess())
    except Exception as e:
        _debug_log(f"[hotkey] CGPreflightListenEventAccess check failed: {e}", force=True)
        return None

# Normalize modifier keys to canonical names
_MODIFIER_MAP = {
    keyboard.Key.cmd: "cmd",
    keyboard.Key.cmd_l: "cmd",
    keyboard.Key.cmd_r: "cmd",
    keyboard.Key.ctrl: "ctrl",
    keyboard.Key.ctrl_l: "ctrl",
    keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.alt: "alt",
    keyboard.Key.alt_l: "alt",
    keyboard.Key.alt_r: "alt",
    keyboard.Key.shift: "shift",
    keyboard.Key.shift_l: "shift",
    keyboard.Key.shift_r: "shift",
}

# Canonical modifier order for display/comparison
_MODIFIER_ORDER = ["ctrl", "alt", "shift", "cmd"]


def normalize_hotkey(hotkey: str) -> str:
    """Normalize a hotkey string for consistent comparison.

    E.g. 'Shift+Cmd+T' -> 'shift+cmd+t', 'T' -> 't'
    """
    parts = [p.strip().lower() for p in hotkey.split("+")]
    mods = sorted([p for p in parts if p in _MODIFIER_ORDER], key=_MODIFIER_ORDER.index)
    keys = [p for p in parts if p not in _MODIFIER_ORDER]
    return "+".join(mods + keys)


def format_hotkey(hotkey: str) -> str:
    """Format a hotkey string for display. E.g. 'cmd+1' -> 'CMD+1'."""
    return "+".join(p.upper() for p in hotkey.split("+"))


def _is_text_field_focused() -> bool:
    """Check if a text input field is currently focused (macOS Accessibility API)."""
    mod = _import_ax_module()
    if mod is None:
        return False
    try:
        system_element = mod.AXUIElementCreateSystemWide()
        err, focused_app = mod.AXUIElementCopyAttributeValue(
            system_element, "AXFocusedApplication", None
        )
        if err != 0 or focused_app is None:
            return False
        err, focused_element = mod.AXUIElementCopyAttributeValue(
            focused_app, "AXFocusedUIElement", None
        )
        if err != 0 or focused_element is None:
            return False
        err, role = mod.AXUIElementCopyAttributeValue(
            focused_element, "AXRole", None
        )
        if err != 0:
            return False
        return role in ("AXTextField", "AXTextArea", "AXComboBox", "AXSearchField")
    except Exception as e:
        print(f"[hotkey] text-field focus check failed: {e}", file=sys.stderr)
        return False


class TypingDetector:
    """Detects rapid keystroke bursts to distinguish typing from toggle intent."""

    def __init__(self, burst_threshold_ms: float = 80, burst_count: int = 2):
        self.recent_times: list[float] = []
        self.burst_threshold = burst_threshold_ms / 1000.0
        self.burst_count = burst_count
        self._lock = threading.Lock()

    def record_keystroke(self):
        now = time.time()
        with self._lock:
            self.recent_times.append(now)
            self.recent_times = self.recent_times[-10:]

    def is_typing_burst(self) -> bool:
        with self._lock:
            if len(self.recent_times) < self.burst_count + 1:
                return False
            recent = self.recent_times[-(self.burst_count + 1):]
            gaps = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
            return all(gap < self.burst_threshold for gap in gaps)


def get_key_char(key) -> Optional[str]:
    """Extract the character from a pynput key event."""
    if hasattr(key, "char") and key.char:
        return key.char.lower()
    # Handle number keys that may come through as Key objects on macOS with modifiers
    if hasattr(key, "vk") and key.vk is not None:
        # Number keys 0-9 have vk codes 48-57
        if 48 <= key.vk <= 57:
            return str(key.vk - 48)
        # Letter keys a-z have vk codes 0-5, 6-12 etc (macOS keycodes)
    return None


class HotkeyManager:
    """Manages global hotkey listening with typing detection and modifier support."""

    def __init__(
        self,
        on_hotkey: Callable[[str], None],
        on_record: Callable[[str], None],
    ):
        self._on_hotkey = on_hotkey
        self._on_record = on_record
        self._typing_detector = TypingDetector()
        self._listener: Optional[keyboard.Listener] = None
        self._recording = False
        self._modifiers_pressed: set[str] = set()  # normalized modifier names
        self._listener_started = False
        self._has_received_event = False
        self._last_error: Optional[str] = None

    @property
    def recording(self) -> bool:
        return self._recording

    @recording.setter
    def recording(self, value: bool):
        self._recording = value

    @property
    def status(self) -> dict:
        """Current listener health snapshot for UI display."""
        return {
            "accessibility_trusted": is_accessibility_trusted(),
            "input_monitoring_allowed": is_input_monitoring_allowed(),
            "event_tap_created": _event_tap_created,
            "listener_started": self._listener_started,
            "has_received_event": self._has_received_event,
            "last_error": self._last_error,
        }

    def start(self):
        """Start the global keyboard listener."""
        self._log_debug_snapshot()
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()
            self._listener_started = True
            self._last_error = None
            _debug_log("[hotkey] listener started")
        except Exception as e:
            self._listener_started = False
            self._last_error = str(e)
            print(f"[hotkey] listener failed to start: {e}", file=sys.stderr)
            _debug_log(f"[hotkey] listener failed to start: {e}")

    def _log_debug_snapshot(self):
        """Permissions/layout snapshot on every start(), same checks as
        diagnose_hotkeys.py. Always written (force=True) since stderr is
        invisible inside the packaged .app bundle — this is the only trace
        of *why* the hotkey status came out the way it did."""
        _debug_log(f"=== HotkeyManager.start() snapshot (pid={os.getpid()}) ===", force=True)
        _debug_log(f"accessibility_trusted = {is_accessibility_trusted()}", force=True)
        _debug_log(f"input_monitoring_allowed = {is_input_monitoring_allowed()}", force=True)
        try:
            from pynput._util.darwin import keycode_context
            with keycode_context() as ctx:
                _keyboard_type, layout_data = ctx
                if layout_data is None:
                    _debug_log("layout_data = None  <-- BAD: chars will resolve to ''", force=True)
                else:
                    _debug_log(f"layout_data = {len(layout_data)} bytes", force=True)
        except Exception as e:
            _debug_log(f"keycode_context check FAILED: {e}", force=True)

    def stop(self):
        """Stop the listener."""
        if self._listener:
            self._listener.stop()

    def _get_modifier_name(self, key) -> Optional[str]:
        """Return canonical modifier name or None."""
        return _MODIFIER_MAP.get(key)

    def _build_combo(self, key_char: str) -> str:
        """Build a hotkey combo string from current modifiers + key."""
        mods = sorted(self._modifiers_pressed, key=lambda m: _MODIFIER_ORDER.index(m))
        parts = mods + [key_char]
        return "+".join(parts)

    def _on_release(self, key):
        self._has_received_event = True
        mod = self._get_modifier_name(key)
        if mod:
            self._modifiers_pressed.discard(mod)

    def _on_press(self, key):
        self._has_received_event = True
        # Track modifier presses
        mod = self._get_modifier_name(key)
        if mod:
            self._modifiers_pressed.add(mod)
            return

        key_char = get_key_char(key)
        if _DEBUG:
            _debug_log(
                f"_on_press: key={key!r} char={getattr(key, 'char', None)!r} "
                f"vk={getattr(key, 'vk', None)!r} get_key_char()={key_char!r} "
                f"recording={self._recording} modifiers={self._modifiers_pressed!r}"
            )
        if not key_char:
            return

        combo = self._build_combo(key_char)
        has_modifiers = bool(self._modifiers_pressed)

        # Recording mode: capture the full combo
        if self._recording:
            _debug_log(f"_on_press: recording -> combo={combo!r}")
            self._on_record(combo)
            return

        # For plain keys (no modifier): apply typing detection
        if not has_modifiers:
            self._typing_detector.record_keystroke()

            # Check if a text field is focused
            if _is_text_field_focused():
                _debug_log(f"_on_press: swallowed (text field focused), combo={combo!r}")
                return

            # Check for typing burst
            if self._typing_detector.is_typing_burst():
                _debug_log(f"_on_press: swallowed (typing burst), combo={combo!r}")
                return

        # For modifier combos: skip typing detection (intentional action)
        # Check if this combo matches any registered hotkey
        _debug_log(f"_on_press: dispatching combo={combo!r}")
        self._on_hotkey(combo)
