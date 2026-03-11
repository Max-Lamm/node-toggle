"""TKinter GUI for Node Toggle."""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import queue
from typing import Optional

from data_model import (
    NodeLevel, NodeAssignment, AssignmentProfile,
    save_config, list_presets, save_preset, load_preset, delete_preset,
)
from hotkey_manager import format_hotkey
from resolve_api import ResolveConnection


class AssignmentRow:
    """A single assignment row in the UI."""

    def __init__(self, parent: tk.Frame, app: "NodeToggleApp", assignment: NodeAssignment):
        self.app = app
        self.assignment = assignment

        self.frame = ttk.LabelFrame(parent, padding=8)
        self.frame.pack(fill=tk.X, padx=8, pady=4)

        # Row 1: Level + Node
        row1 = ttk.Frame(self.frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="Level:", width=8).pack(side=tk.LEFT)
        self.level_var = tk.StringVar(value=assignment.level.display_name)
        self.level_combo = ttk.Combobox(
            row1,
            textvariable=self.level_var,
            values=[l.display_name for l in NodeLevel],
            state="readonly",
            width=18,
        )
        self.level_combo.pack(side=tk.LEFT, padx=(0, 12))
        self.level_combo.bind("<<ComboboxSelected>>", self._on_level_changed)

        ttk.Label(row1, text="Node:", width=6).pack(side=tk.LEFT)
        self.node_var = tk.StringVar()
        self.node_combo = ttk.Combobox(
            row1,
            textvariable=self.node_var,
            state="readonly",
            width=22,
        )
        self.node_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.node_combo.bind("<<ComboboxSelected>>", self._on_node_changed)

        # Row 2: Hotkey + Remove
        row2 = ttk.Frame(self.frame)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text="Hotkey:", width=8).pack(side=tk.LEFT)
        hotkey_display = format_hotkey(assignment.hotkey) if assignment.hotkey else ""
        self.hotkey_var = tk.StringVar(value=hotkey_display)
        self.hotkey_entry = ttk.Entry(
            row2, textvariable=self.hotkey_var, width=14,
            state="readonly", justify="center",
        )
        self.hotkey_entry.pack(side=tk.LEFT, padx=(0, 4))

        self.record_btn = ttk.Button(row2, text="Record", width=8, command=self._start_recording)
        self.record_btn.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Button(row2, text="Remove", width=8, command=self._remove).pack(side=tk.RIGHT)

        # Populate node dropdown
        self._refresh_nodes()
        if assignment.node_label:
            self._select_node_by_label(assignment.node_label)

    def _on_level_changed(self, event=None):
        new_level = NodeLevel.from_display_name(self.level_var.get())
        self.assignment.level = new_level
        self._refresh_nodes()
        self.assignment.node_index = 0
        self.assignment.node_label = ""
        self.node_var.set("")
        self.app.save()

    def _on_node_changed(self, event=None):
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
        """Refresh node dropdown for the current level."""
        level = NodeLevel.from_display_name(self.level_var.get())
        nodes = self.app.resolve_conn.get_nodes_for_level(level)
        values = [f"{n['index']} - {n['label']}" for n in nodes]
        self.node_combo["values"] = values
        if not values:
            self.node_combo["values"] = ["(no nodes available)"]

    def _select_node_by_label(self, label: str):
        """Try to select a node by its label in the dropdown."""
        for val in self.node_combo["values"]:
            if label in val:
                self.node_var.set(val)
                return
        idx_str = f"{self.assignment.node_index} - "
        for val in self.node_combo["values"]:
            if val.startswith(idx_str):
                self.node_var.set(val)
                return

    def _start_recording(self):
        self.record_btn.configure(text="Press key...")
        self.app.start_hotkey_recording(self)

    def finish_recording(self, combo: str):
        """Called when a key combo is captured during recording."""
        self.record_btn.configure(text="Record")

        if self.app.profile.is_hotkey_taken(combo, exclude=self.assignment):
            messagebox.showwarning(
                "Hotkey Conflict",
                f"'{format_hotkey(combo)}' is already assigned to another node.\n"
                "Please choose a different key.",
            )
            return

        self.assignment.hotkey = combo
        self.hotkey_var.set(format_hotkey(combo))
        self.app.save()

    def cancel_recording(self):
        self.record_btn.configure(text="Record")

    def _remove(self):
        self.app.remove_assignment(self)

    def destroy(self):
        self.frame.destroy()


class NodeToggleApp:
    """Main application UI."""

    def __init__(self, root: tk.Tk, resolve_conn: ResolveConnection, profile: AssignmentProfile):
        self.root = root
        self.resolve_conn = resolve_conn
        self.profile = profile
        self.event_queue: queue.Queue = queue.Queue()
        self._recording_row: Optional[AssignmentRow] = None
        self._rows: list[AssignmentRow] = []

        self.root.title("maxlamm Node Toggle")
        self.root.geometry("540x500")
        self.root.minsize(500, 300)

        self._build_ui()
        self._load_existing_assignments()
        self.root.after(50, self._process_queue)

    def _build_ui(self):
        # Status bar
        status_frame = ttk.Frame(self.root, padding=8)
        status_frame.pack(fill=tk.X)

        self.status_var = tk.StringVar(value="Connecting...")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor=tk.W)

        self.timeline_var = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.timeline_var, foreground="gray").pack(anchor=tk.W)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # Preset bar
        preset_frame = ttk.Frame(self.root, padding=(8, 4))
        preset_frame.pack(fill=tk.X)

        ttk.Label(preset_frame, text="Preset:").pack(side=tk.LEFT)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(
            preset_frame, textvariable=self.preset_var,
            state="readonly", width=18,
        )
        self.preset_combo.pack(side=tk.LEFT, padx=(4, 4))
        self._refresh_preset_list()

        ttk.Button(preset_frame, text="Load", width=6, command=self._load_preset).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_frame, text="Save", width=6, command=self._save_preset).pack(side=tk.LEFT, padx=2)
        ttk.Button(preset_frame, text="Delete", width=6, command=self._delete_preset).pack(side=tk.LEFT, padx=2)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # Toolbar
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="+ Add Assignment", command=self._add_assignment).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Refresh Nodes", command=self._refresh_all_nodes).pack(side=tk.RIGHT)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # Scrollable assignments area
        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)

        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")
        ))
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor=tk.NW)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * e.delta, "units"))

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _load_existing_assignments(self):
        """Create UI rows for saved assignments."""
        for assignment in self.profile.assignments:
            row = AssignmentRow(self.scroll_frame, self, assignment)
            self._rows.append(row)

    def _clear_all_rows(self):
        """Remove all assignment rows from the UI."""
        for row in self._rows:
            row.destroy()
        self._rows.clear()

    def _rebuild_rows(self):
        """Clear and rebuild all rows from current profile."""
        self._clear_all_rows()
        self._load_existing_assignments()

    def _add_assignment(self):
        """Add a new empty assignment."""
        assignment = NodeAssignment(
            level=NodeLevel.TIMELINE,
            node_index=0,
            node_label="",
        )
        self.profile.add(assignment)
        row = AssignmentRow(self.scroll_frame, self, assignment)
        self._rows.append(row)
        self.save()

    def remove_assignment(self, row: AssignmentRow):
        """Remove an assignment row."""
        self.profile.remove(row.assignment)
        self._rows.remove(row)
        row.destroy()
        self.save()

    def _refresh_all_nodes(self):
        """Re-query nodes from Resolve and update all dropdowns."""
        self.resolve_conn.refresh_context()
        for row in self._rows:
            row._refresh_nodes()
            if row.assignment.node_label:
                row._select_node_by_label(row.assignment.node_label)
        self.update_status_bar()

    # --- Preset management ---

    def _refresh_preset_list(self):
        presets = list_presets()
        self.preset_combo["values"] = presets
        if presets and not self.preset_var.get():
            self.preset_var.set(presets[0])

    def _save_preset(self):
        name = simpledialog.askstring("Save Preset", "Preset name:", parent=self.root)
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
        """Enter recording mode for a specific row."""
        if self._recording_row and self._recording_row is not row:
            self._recording_row.cancel_recording()
        self._recording_row = row

    def finish_hotkey_recording(self, combo: str):
        """Called from hotkey manager when a key combo is captured."""
        if self._recording_row:
            row = self._recording_row
            self._recording_row = None
            row.finish_recording(combo)

    @property
    def is_recording(self) -> bool:
        return self._recording_row is not None

    def save(self):
        """Save current profile to disk."""
        save_config(self.profile)

    def update_status_bar(self):
        """Update connection status display."""
        if self.resolve_conn.connected:
            project = self.resolve_conn.get_project_name()
            self.status_var.set(f"Connected to DaVinci Resolve \u2014 {project}")
            timeline = self.resolve_conn.get_timeline_name()
            if timeline:
                self.timeline_var.set(f"Timeline: {timeline}")
            else:
                self.timeline_var.set("No timeline selected")
        else:
            self.status_var.set("Not connected to DaVinci Resolve")
            self.timeline_var.set("Make sure Resolve Studio is running")

    def schedule_ui_update(self, func, *args):
        """Thread-safe: schedule a function to run on the main thread."""
        self.event_queue.put((func, args))

    def _process_queue(self):
        """Process pending UI updates from other threads."""
        while not self.event_queue.empty():
            try:
                func, args = self.event_queue.get_nowait()
                func(*args)
            except queue.Empty:
                break
        self.root.after(50, self._process_queue)
