"""Data model and config persistence for Node Toggle."""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class NodeLevel(Enum):
    TIMELINE = "timeline"
    CLIP = "clip"
    GROUP_PRE_CLIP = "group_pre_clip"
    GROUP_POST_CLIP = "group_post_clip"

    @property
    def display_name(self) -> str:
        return {
            NodeLevel.TIMELINE: "Timeline",
            NodeLevel.CLIP: "Clip",
            NodeLevel.GROUP_PRE_CLIP: "Group Pre-Clip",
            NodeLevel.GROUP_POST_CLIP: "Group Post-Clip",
        }[self]

    @classmethod
    def from_display_name(cls, name: str) -> "NodeLevel":
        for level in cls:
            if level.display_name == name:
                return level
        raise ValueError(f"Unknown level: {name}")


@dataclass
class NodeAssignment:
    """A single node-to-hotkey binding."""
    level: NodeLevel
    node_index: int          # 1-based, as per Resolve API
    node_label: str
    hotkey: Optional[str] = None  # e.g. "t", "cmd+1", "ctrl+shift+t"
    _toggle_state: bool = field(default=True, repr=False)  # internal toggle tracker

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "node_index": self.node_index,
            "node_label": self.node_label,
            "hotkey": self.hotkey,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NodeAssignment":
        return cls(
            level=NodeLevel(data["level"]),
            node_index=data["node_index"],
            node_label=data["node_label"],
            hotkey=data.get("hotkey"),
        )


def _normalize_hotkey(hotkey: str) -> str:
    """Normalize for comparison: lowercase, sorted modifiers."""
    parts = [p.strip().lower() for p in hotkey.split("+")]
    mod_order = ["ctrl", "alt", "shift", "cmd"]
    mods = sorted([p for p in parts if p in mod_order], key=mod_order.index)
    keys = [p for p in parts if p not in mod_order]
    return "+".join(mods + keys)


@dataclass
class AssignmentProfile:
    """All assignments across all levels."""
    assignments: list[NodeAssignment] = field(default_factory=list)

    def get_by_hotkey(self, hotkey: str) -> Optional[NodeAssignment]:
        """Return the assignment bound to a given hotkey, or None."""
        normalized = _normalize_hotkey(hotkey)
        for a in self.assignments:
            if a.hotkey and _normalize_hotkey(a.hotkey) == normalized:
                return a
        return None

    def get_by_level(self, level: NodeLevel) -> list[NodeAssignment]:
        """Return all assignments for a given node level."""
        return [a for a in self.assignments if a.level == level]

    def is_hotkey_taken(self, hotkey: str, exclude: Optional[NodeAssignment] = None) -> bool:
        """Check if a hotkey is already assigned."""
        normalized = _normalize_hotkey(hotkey)
        for a in self.assignments:
            if a is exclude:
                continue
            if a.hotkey and _normalize_hotkey(a.hotkey) == normalized:
                return True
        return False

    def add(self, assignment: NodeAssignment):
        self.assignments.append(assignment)

    def remove(self, assignment: NodeAssignment):
        self.assignments.remove(assignment)


# --- Config persistence ---

CONFIG_DIR = Path.home() / ".node_toggle"
CONFIG_FILE = CONFIG_DIR / "config.json"
PRESETS_DIR = CONFIG_DIR / "presets"


def load_config() -> AssignmentProfile:
    """Load saved assignments from disk."""
    if not CONFIG_FILE.exists():
        return AssignmentProfile()
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        assignments = [NodeAssignment.from_dict(a) for a in data.get("assignments", [])]
        return AssignmentProfile(assignments=assignments)
    except (json.JSONDecodeError, KeyError, ValueError):
        return AssignmentProfile()


def save_config(profile: AssignmentProfile):
    """Save assignments to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "assignments": [a.to_dict() for a in profile.assignments],
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


# --- Preset system ---

def list_presets() -> list[str]:
    """Return list of saved preset names."""
    if not PRESETS_DIR.exists():
        return []
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def save_preset(name: str, profile: AssignmentProfile):
    """Save current assignments as a named preset."""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "assignments": [a.to_dict() for a in profile.assignments],
    }
    filepath = PRESETS_DIR / f"{name}.json"
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def load_preset(name: str) -> AssignmentProfile:
    """Load a named preset."""
    filepath = PRESETS_DIR / f"{name}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Preset '{name}' not found")
    with open(filepath, "r") as f:
        data = json.load(f)
    assignments = [NodeAssignment.from_dict(a) for a in data.get("assignments", [])]
    return AssignmentProfile(assignments=assignments)


def delete_preset(name: str):
    """Delete a named preset."""
    filepath = PRESETS_DIR / f"{name}.json"
    if filepath.exists():
        filepath.unlink()
