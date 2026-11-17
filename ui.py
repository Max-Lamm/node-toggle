"""Modern customtkinter GUI for Node Toggle."""

import os
import sys
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image
import queue
from typing import Optional

from data_model import (
    NodeLevel, NodeAssignment, AssignmentProfile, HOTKEY_SLOTS,
    save_config, list_presets, save_preset, load_preset, delete_preset,
)
from hotkey_manager import format_hotkey
from resolve_api import ResolveConnection

# -- Theme constants --
BG_DARK = "#2b2b2b"
BG_SURFACE = "#363636"
ACCENT = "#e94560"
ACCENT_HOVER = "#c73a52"
TEXT_PRIMARY = "#eaeaea"
TEXT_SECONDARY = "#888888"
BORDER_COLOR = "#444444"
CHIP_BG = "#444444"
BUTTON_FG = "#eaeaea"
BUTTON_BG = "#3a3a3a"
BUTTON_HOVER = "#4a4a4a"
GREEN = "#4ade80"
RED = "#ef4444"

FONT_FAMILY = "Helvetica Neue"
LEVEL_NAMES = [l.display_name for l in NodeLevel]

def _resource_path(filename: str) -> str:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)

ICON_PATH = _resource_path("node-toggle.png")

_KEY_SYMBOLS = {"ctrl": "⌃", "alt": "⌥", "shift": "⇧", "cmd": "⌘", " ": "Space"}


def hotkey_parts(hotkey: str) -> list[str]:
    """Split a hotkey into display chips. E.g. 'shift+cmd+t' -> ['⇧', '⌘', 'T']."""
    return [_KEY_SYMBOLS.get(p, p.upper()) for p in hotkey.split("+")]


class AssignmentRow:
    """A single compact assignment card."""

    def __init__(self, parent: ctk.CTkFrame, app: "NodeToggleApp", assignment: NodeAssignment):
        self.app = app
        self.assignment = assignment

        # Separator line above each card
        self._sep = ctk.CTkFrame(parent, height=1, fg_color=BORDER_COLOR)
        self._sep.pack(fill=tk.X, padx=10, pady=(4, 0))

        # Card frame — flat, compact
        self.frame = ctk.CTkFrame(parent, fg_color=BG_SURFACE, corner_radius=6)
        self.frame.pack(fill=tk.X, padx=10, pady=3)

        inner = ctk.CTkFrame(self.frame, fg_color="transparent")
        inner.pack(fill=tk.X, padx=10, pady=8)

        # Row 1: Level + Node
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill=tk.X, pady=(0, 5))

        self.level_var = ctk.StringVar(value=assignment.level.display_name)
        self.level_combo = ctk.CTkComboBox(
            row1, variable=self.level_var, values=LEVEL_NAMES,
            state="readonly", width=130, height=26,
            fg_color=BG_DARK, border_color=BORDER_COLOR, border_width=1,
            button_color=BORDER_COLOR, button_hover_color=BUTTON_HOVER,
            dropdown_fg_color=BG_DARK, dropdown_hover_color=BUTTON_BG,
            text_color=TEXT_PRIMARY, corner_radius=4,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self._on_level_changed,
        )
        self.level_combo.pack(side=tk.LEFT, padx=(0, 6))

        self.node_var = ctk.StringVar()
        self.node_combo = ctk.CTkComboBox(
            row1, variable=self.node_var, values=["(no nodes)"],
            state="readonly", width=160, height=26,
            fg_color=BG_DARK, border_color=BORDER_COLOR, border_width=1,
            button_color=BORDER_COLOR, button_hover_color=BUTTON_HOVER,
            dropdown_fg_color=BG_DARK, dropdown_hover_color=BUTTON_BG,
            text_color=TEXT_PRIMARY, corner_radius=4,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            command=self._on_node_changed,
        )
        self.node_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.remove_btn = ctk.CTkButton(
            row1, text="Remove", width=60, height=26,
            fg_color="transparent", hover_color=BUTTON_HOVER,
            text_color=TEXT_SECONDARY, border_color=BORDER_COLOR,
            border_width=1, corner_radius=4,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self._remove,
        )
        self.remove_btn.pack(side=tk.RIGHT)

        # Hotkey list: one box per hotkey, all active at the same time.
        # _recording_slot is the index being recorded. It equals
        # len(hotkeys) while a new hotkey is being added.
        self._recording_slot: Optional[int] = None
        self.hotkey_area = ctk.CTkFrame(inner, fg_color="transparent")
        self.hotkey_area.pack(fill=tk.X)
        self._render_hotkeys()

        self._refresh_nodes()
        if assignment.node_label:
            self._select_node_by_label(assignment.node_label)

    def _on_level_changed(self, _choice=None):
        new_level = NodeLevel.from_display_name(self.level_var.get())
        self.assignment.level = new_level
        self._refresh_nodes()
        self.assignment.node_index = 0
        self.assignment.node_label = ""
        self.node_var.set("")
        self.app.save()

    def _on_node_changed(self, _choice=None):
        selection = self.node_var.get()
        if not selection:
            return
        try:
            parts = selection.split(" - ", 1)
            self.assignment.node_index = int(parts[0])
            self.assignment.node_label = parts[1] if len(parts) > 1 else f"Node {parts[0]}"
        except (ValueError, IndexError):
            pass
        self.app.save()

    def _refresh_nodes(self):
        level = NodeLevel.from_display_name(self.level_var.get())
        nodes = self.app.resolve_conn.get_nodes_for_level(level)
        values = [f"{n['index']} - {n['label']}" for n in nodes]
        if not values:
            values = ["(no nodes)"]
        self.node_combo.configure(values=values)

    def _select_node_by_label(self, label: str):
        for val in self.node_combo.cget("values"):
            if label in val:
                self.node_var.set(val)
                return
        idx_str = f"{self.assignment.node_index} - "
        for val in self.node_combo.cget("values"):
            if val.startswith(idx_str):
                self.node_var.set(val)
                return

    # --- Hotkey list ---

    def _render_hotkeys(self):
        """Rebuild the hotkey boxes from assignment.hotkeys + recording state."""
        for child in self.hotkey_area.winfo_children():
            child.destroy()

        hotkeys = self.assignment.hotkeys
        slots = len(hotkeys)
        if self._recording_slot == slots or slots == 0:
            slots += 1  # placeholder box for a new hotkey
        can_add = self._recording_slot is None and 0 < len(hotkeys) < HOTKEY_SLOTS

        for slot in range(slots):
            line = ctk.CTkFrame(self.hotkey_area, fg_color="transparent")
            line.pack(fill=tk.X, pady=(0, 4) if slot < slots - 1 else 0)
            hotkey = hotkeys[slot] if slot < len(hotkeys) else None
            self._build_hotkey_box(line, slot, hotkey)
            if can_add and slot == slots - 1:
                ctk.CTkButton(
                    line, text="+", width=30, height=30,
                    fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
                    text_color=BUTTON_FG, corner_radius=6,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=16),
                    command=lambda: self._start_recording(len(self.assignment.hotkeys)),
                ).pack(side=tk.RIGHT, padx=(6, 0))
            elif HOTKEY_SLOTS > 1:
                # keep all boxes the same width as the one next to "+"
                ctk.CTkFrame(line, width=30, height=30, fg_color="transparent").pack(
                    side=tk.RIGHT, padx=(6, 0))

    def _build_hotkey_box(self, parent, slot: int, hotkey: Optional[str]):
        recording = self._recording_slot == slot
        box = ctk.CTkFrame(
            parent, height=30, fg_color=BG_DARK, corner_radius=6, border_width=1,
            border_color=ACCENT if recording else BORDER_COLOR,
        )
        box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        box.pack_propagate(False)

        content = ctk.CTkFrame(box, fg_color="transparent")
        content.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0), pady=3)

        if recording:
            self._hint(content, "Press a key…", TEXT_PRIMARY)
        elif hotkey:
            for part in hotkey_parts(hotkey):
                ctk.CTkLabel(
                    content, text=part, height=22, fg_color=CHIP_BG,
                    corner_radius=4, text_color=TEXT_PRIMARY,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                ).pack(side=tk.LEFT, padx=(0, 4), ipadx=5)
        else:
            self._hint(content, "Click to add a shortcut", TEXT_SECONDARY)
            for w in (box, content, *content.winfo_children()):
                w.bind("<Button-1>", lambda _e, s=slot: self._start_recording(s))

        # Delete: removes an existing hotkey or cancels the current recording
        if hotkey and not recording:
            self._icon_btn(box, "⌫", lambda s=slot: self._delete_hotkey(s))
        if not recording:
            self._icon_btn(box, "✎", lambda s=slot: self._start_recording(s))
        else:
            self._icon_btn(box, "Esc", self._stop_recording, size=10)

    @staticmethod
    def _hint(parent, text: str, color: str):
        ctk.CTkLabel(
            parent, text=text, height=22, text_color=color,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        ).pack(side=tk.LEFT, padx=(4, 0))

    @staticmethod
    def _icon_btn(parent, text: str, command, size: int = 14):
        ctk.CTkButton(
            parent, text=text, width=26, height=22,
            fg_color="transparent", hover_color=BUTTON_HOVER,
            text_color=TEXT_SECONDARY, corner_radius=4,
            font=ctk.CTkFont(family=FONT_FAMILY, size=size),
            command=command,
        ).pack(side=tk.RIGHT, padx=(0, 4))

    def _start_recording(self, slot: int):
        self._recording_slot = slot
        self._render_hotkeys()
        self.app.start_hotkey_recording(self)

    def _stop_recording(self):
        """Cancel via the Esc button in the box."""
        self.app.cancel_hotkey_recording(self)
        self.cancel_recording()

    def _delete_hotkey(self, slot: int):
        if slot < len(self.assignment.hotkeys):
            del self.assignment.hotkeys[slot]
            self.app.save()
        if self._recording_slot is not None:
            self.app.cancel_hotkey_recording(self)
        self._recording_slot = None
        self._render_hotkeys()

    def finish_recording(self, combo: str):
        slot = self._recording_slot
        if slot is None:
            return
        self._recording_slot = None
        if self.app.profile.is_hotkey_taken(combo, exclude=self.assignment, exclude_slot=slot):
            self._render_hotkeys()
            messagebox.showwarning(
                "Hotkey Conflict",
                f"'{format_hotkey(combo)}' is already assigned.\n"
                "Choose a different key.",
            )
            return
        if slot < len(self.assignment.hotkeys):
            self.assignment.hotkeys[slot] = combo
        else:
            self.assignment.hotkeys.append(combo)
        self._render_hotkeys()
        self.app.save()

    def cancel_recording(self):
        if self._recording_slot is not None:
            self._recording_slot = None
            self._render_hotkeys()

    def _remove(self):
        self.app.remove_assignment(self)

    def destroy(self):
        self._sep.destroy()
        self.frame.destroy()


class NodeToggleApp:
    """Main application UI."""

    def __init__(self, root: ctk.CTk, resolve_conn: ResolveConnection, profile: AssignmentProfile):
        self.root = root
        self.resolve_conn = resolve_conn
        self.profile = profile
        self.event_queue: queue.Queue = queue.Queue()
        self._recording_row: Optional[AssignmentRow] = None
        self._rows: list[AssignmentRow] = []

        self.root.title("Node Toggle")
        self.root.geometry("420x540")
        self.root.minsize(400, 400)
        self.root.configure(fg_color=BG_DARK)

        self._build_ui()
        self._load_existing_assignments()
        self.root.after(50, self._process_queue)

    def _build_ui(self):
        # ── Status bar ──
        status_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        status_frame.pack(fill=tk.X, padx=12, pady=(10, 4))

        status_row = ctk.CTkFrame(status_frame, fg_color="transparent")
        status_row.pack(fill=tk.X)

        self._status_dot = ctk.CTkLabel(
            status_row, text="●", width=12,
            text_color=RED,
            font=ctk.CTkFont(size=10),
        )
        self._status_dot.pack(side=tk.LEFT, padx=(0, 6))

        self.status_var = ctk.StringVar(value="Connecting...")
        ctk.CTkLabel(
            status_row, textvariable=self.status_var,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
        ).pack(side=tk.LEFT)

        # App icon top-right
        if os.path.exists(ICON_PATH):
            icon_image = ctk.CTkImage(
                light_image=Image.open(ICON_PATH),
                dark_image=Image.open(ICON_PATH),
                size=(32, 32),
            )
            ctk.CTkLabel(status_row, image=icon_image, text="").pack(side=tk.RIGHT)

        self.timeline_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            status_frame, textvariable=self.timeline_var,
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).pack(anchor=tk.W, padx=(18, 0), pady=(1, 0))

        self.hotkey_status_var = ctk.StringVar(value="")
        self._hotkey_status_label = ctk.CTkLabel(
            status_frame, textvariable=self.hotkey_status_var,
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        self._hotkey_status_label.pack(anchor=tk.W, padx=(18, 0), pady=(1, 0))

        # ── Separator ──
        ctk.CTkFrame(self.root, height=1, fg_color=BORDER_COLOR).pack(fill=tk.X, padx=10, pady=(6, 0))

        # ── Preset bar ──
        preset_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        preset_frame.pack(fill=tk.X, padx=12, pady=6)

        ctk.CTkLabel(
            preset_frame, text="Preset",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).pack(side=tk.LEFT, padx=(0, 6))

        self.preset_var = ctk.StringVar()
        self.preset_combo = ctk.CTkComboBox(
            preset_frame, variable=self.preset_var,
            values=[""], state="readonly", width=140, height=26,
            fg_color=BG_SURFACE, border_color=BORDER_COLOR, border_width=1,
            button_color=BORDER_COLOR, button_hover_color=BUTTON_HOVER,
            dropdown_fg_color=BG_DARK, dropdown_hover_color=BUTTON_BG,
            text_color=TEXT_PRIMARY, corner_radius=4,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        self.preset_combo.pack(side=tk.LEFT, padx=(0, 6))
        self._refresh_preset_list()

        for text, cmd in [("Load", self._load_preset), ("Save", self._save_preset), ("Delete", self._delete_preset)]:
            ctk.CTkButton(
                preset_frame, text=text, width=46, height=26,
                fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
                text_color=BUTTON_FG, corner_radius=4,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                command=cmd,
            ).pack(side=tk.LEFT, padx=1)

        # ── Toolbar ──
        toolbar = ctk.CTkFrame(self.root, fg_color="transparent")
        toolbar.pack(fill=tk.X, padx=12, pady=(2, 4))

        ctk.CTkButton(
            toolbar, text="+ Add", width=70, height=26,
            fg_color="transparent", hover_color=BUTTON_BG,
            text_color=TEXT_PRIMARY, border_color=BORDER_COLOR,
            border_width=1, corner_radius=4,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self._add_assignment,
        ).pack(side=tk.LEFT)

        ctk.CTkButton(
            toolbar, text="Refresh", width=60, height=26,
            fg_color="transparent", hover_color=BUTTON_BG,
            text_color=TEXT_SECONDARY, border_color=BORDER_COLOR,
            border_width=1, corner_radius=4,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self._refresh_all_nodes,
        ).pack(side=tk.RIGHT)

        # ── Scrollable assignments area ──
        self.scroll_frame = ctk.CTkScrollableFrame(
            self.root, fg_color=BG_DARK,
            scrollbar_button_color=BUTTON_BG,
            scrollbar_button_hover_color=BUTTON_HOVER,
        )
        self.scroll_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

    def _load_existing_assignments(self):
        for assignment in self.profile.assignments:
            row = AssignmentRow(self.scroll_frame, self, assignment)
            self._rows.append(row)

    def _clear_all_rows(self):
        for row in self._rows:
            row.destroy()
        self._rows.clear()

    def _rebuild_rows(self):
        self._clear_all_rows()
        self._load_existing_assignments()

    def _add_assignment(self):
        assignment = NodeAssignment(level=NodeLevel.TIMELINE, node_index=0, node_label="")
        self.profile.add(assignment)
        row = AssignmentRow(self.scroll_frame, self, assignment)
        self._rows.append(row)
        self.save()

    def remove_assignment(self, row: AssignmentRow):
        self.cancel_hotkey_recording(row)
        self.profile.remove(row.assignment)
        self._rows.remove(row)
        row.destroy()
        self.save()

    def _refresh_all_nodes(self):
        self.resolve_conn.refresh_context()
        for row in self._rows:
            row._refresh_nodes()
            if row.assignment.node_label:
                row._select_node_by_label(row.assignment.node_label)
        self.update_status_bar()

    # --- Preset management ---

    def _refresh_preset_list(self):
        presets = list_presets()
        self.preset_combo.configure(values=presets if presets else [""])
        if presets and not self.preset_var.get():
            self.preset_var.set(presets[0])

    def _save_preset(self):
        dialog = ctk.CTkInputDialog(
            text="Preset name:", title="Save Preset",
            fg_color=BG_DARK, button_fg_color=ACCENT, button_hover_color=ACCENT_HOVER,
        )
        name = dialog.get_input()
        if not name:
            return
        name = name.strip()
        if not name:
            return
        save_preset(name, self.profile)
        self._refresh_preset_list()
        self.preset_var.set(name)

    def _load_preset(self):
        name = self.preset_var.get()
        if not name:
            messagebox.showinfo("Load Preset", "No preset selected.")
            return
        try:
            loaded = load_preset(name)
        except FileNotFoundError:
            messagebox.showerror("Error", f"Preset '{name}' not found.")
            return
        self.profile.assignments = loaded.assignments
        self._rebuild_rows()
        self.save()

    def _delete_preset(self):
        name = self.preset_var.get()
        if not name:
            return
        if not messagebox.askyesno("Delete Preset", f"Delete preset '{name}'?"):
            return
        delete_preset(name)
        self.preset_var.set("")
        self._refresh_preset_list()

    # --- Hotkey recording ---

    def start_hotkey_recording(self, row: AssignmentRow):
        if self._recording_row and self._recording_row is not row:
            self._recording_row.cancel_recording()
        self._recording_row = row

    def finish_hotkey_recording(self, combo: str):
        if self._recording_row:
            row = self._recording_row
            self._recording_row = None
            row.finish_recording(combo)

    def cancel_hotkey_recording(self, row: AssignmentRow):
        if self._recording_row is row:
            self._recording_row = None
            mgr = getattr(self, "hotkey_mgr", None)
            if mgr:
                mgr.recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording_row is not None

    def save(self):
        save_config(self.profile)

    def update_status_bar(self):
        if self.resolve_conn.connected:
            project = self.resolve_conn.get_project_name()
            timeline = self.resolve_conn.get_timeline_name()
            self._status_dot.configure(text_color=GREEN)
            self.status_var.set(f"Connected — {project}")
            self.timeline_var.set(f"› {timeline}" if timeline else "No timeline selected")
        else:
            self._status_dot.configure(text_color=RED)
            self.status_var.set("Not connected")
            self.timeline_var.set("Make sure Resolve Studio is running")
        self._update_hotkey_status()

    def _update_hotkey_status(self):
        mgr = getattr(self, "hotkey_mgr", None)
        if mgr is None:
            return
        status = mgr.status
        if not status["listener_started"]:
            color = RED
            text = f"Hotkeys: listener failed to start ({status['last_error']})"
        elif status["accessibility_trusted"] is None or status["input_monitoring_allowed"] is None:
            color = RED
            text = "Hotkeys: permission check failed (see ~/.node_toggle/diagnose.log)"
        elif not status["accessibility_trusted"]:
            color = RED
            text = "Hotkeys: Accessibility permission missing"
        elif not status["input_monitoring_allowed"]:
            color = RED
            text = "Hotkeys: Input Monitoring permission missing"
        elif status["event_tap_created"] is False:
            color = RED
            text = "Hotkeys: event tap could not be created"
        elif not status["has_received_event"]:
            color = TEXT_SECONDARY
            text = "Hotkeys: waiting for first key press…"
        else:
            color = GREEN
            text = "Hotkeys: active"
        self._hotkey_status_label.configure(text_color=color)
        self.hotkey_status_var.set(text)

    def schedule_ui_update(self, func, *args):
        self.event_queue.put((func, args))

    def _process_queue(self):
        while not self.event_queue.empty():
            try:
                func, args = self.event_queue.get_nowait()
                func(*args)
            except queue.Empty:
                break
        self.root.after(50, self._process_queue)
