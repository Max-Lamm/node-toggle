"""Global hotkey capture and typing detection for macOS."""

import sys
import time
import threading
from typing import Callable, Optional

from pynput import keyboard

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


def is_accessibility_trusted() -> bool:
    """Check if this process has macOS Accessibility permission."""
    try:
        import ApplicationServices
        return bool(ApplicationServices.AXIsProcessTrusted())
    except Exception as e:
        print(f"[hotkey] AXIsProcessTrusted check failed: {e}", file=sys.stderr)
        return False

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
    try:
        import ApplicationServices
        system_element = ApplicationServices.AXUIElementCreateSystemWide()
        err, focused_app = ApplicationServices.AXUIElementCopyAttributeValue(
            system_element, "AXFocusedApplication", None
        )
        if err != 0 or focused_app is None:
            return False
        err, focused_element = ApplicationServices.AXUIElementCopyAttributeValue(
            focused_app, "AXFocusedUIElement", None
        )
        if err != 0 or focused_element is None:
            return False
        err, role = ApplicationServices.AXUIElementCopyAttributeValue(
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
            "listener_started": self._listener_started,
            "has_received_event": self._has_received_event,
            "last_error": self._last_error,
        }

    def start(self):
        """Start the global keyboard listener."""
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()
            self._listener_started = True
            self._last_error = None
        except Exception as e:
            self._listener_started = False
            self._last_error = str(e)
            print(f"[hotkey] listener failed to start: {e}", file=sys.stderr)

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
        if not key_char:
            return

        combo = self._build_combo(key_char)
        has_modifiers = bool(self._modifiers_pressed)

        # Recording mode: capture the full combo
        if self._recording:
            self._on_record(combo)
            return

        # For plain keys (no modifier): apply typing detection
        if not has_modifiers:
            self._typing_detector.record_keystroke()

            # Check if a text field is focused
            if _is_text_field_focused():
                return

            # Check for typing burst
            if self._typing_detector.is_typing_burst():
                return

        # For modifier combos: skip typing detection (intentional action)
        # Check if this combo matches any registered hotkey
        self._on_hotkey(combo)
