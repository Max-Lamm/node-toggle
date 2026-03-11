"""DaVinci Resolve Scripting API wrapper for node operations."""

import sys
from typing import Optional

from data_model import NodeLevel

# Add Resolve scripting module to path
sys.path.insert(0, "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/")

try:
    import DaVinciResolveScript as dvr_script
except ImportError:
    dvr_script = None


class ResolveConnection:
    """Manages connection to DaVinci Resolve and node operations."""

    def __init__(self):
        self.resolve = None
        self.project = None
        self.timeline = None
        self.current_item = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """Attempt to connect to DaVinci Resolve."""
        if dvr_script is None:
            self._connected = False
            return False
        try:
            self.resolve = dvr_script.scriptapp("Resolve")
            if self.resolve is None:
                self._connected = False
                return False
            pm = self.resolve.GetProjectManager()
            if pm is None:
                self._connected = False
                return False
            self.project = pm.GetCurrentProject()
            self._connected = self.project is not None
            return self._connected
        except Exception:
            self._connected = False
            return False

    def refresh_context(self) -> bool:
        """Refresh timeline and clip context. Call periodically."""
        if not self.resolve:
            return False
        try:
            pm = self.resolve.GetProjectManager()
            if pm is None:
                self._connected = False
                return False
            self.project = pm.GetCurrentProject()
            if not self.project:
                self._connected = False
                return False
            self.timeline = self.project.GetCurrentTimeline()
            if self.timeline:
                self.current_item = self.timeline.GetCurrentVideoItem()
            else:
                self.current_item = None
            self._connected = True
            return True
        except Exception:
            self._connected = False
            return False

    def get_timeline_name(self) -> str:
        """Return current timeline name or empty string."""
        if self.timeline:
            try:
                return self.timeline.GetName() or ""
            except Exception:
                pass
        return ""

    def get_project_name(self) -> str:
        """Return current project name or empty string."""
        if self.project:
            try:
                return self.project.GetName() or ""
            except Exception:
                pass
        return ""

    def _get_node_graph(self, level: NodeLevel):
        """Return the Graph object for a given level, or None."""
        if not self.timeline:
            return None

        try:
            if level == NodeLevel.TIMELINE:
                return self.timeline.GetNodeGraph()

            elif level == NodeLevel.CLIP:
                if self.current_item:
                    return self.current_item.GetNodeGraph()
                return None

            elif level == NodeLevel.GROUP_PRE_CLIP:
                if self.current_item:
                    color_group = self.current_item.GetColorGroup()
                    if color_group:
                        return color_group.GetPreClipNodeGraph()
                return None

            elif level == NodeLevel.GROUP_POST_CLIP:
                if self.current_item:
                    color_group = self.current_item.GetColorGroup()
                    if color_group:
                        return color_group.GetPostClipNodeGraph()
                return None
        except Exception:
            return None

    def get_nodes_for_level(self, level: NodeLevel) -> list[dict]:
        """Return list of {index, label} for all nodes at a level."""
        graph = self._get_node_graph(level)
        if not graph:
            return []

        nodes = []
        try:
            num = graph.GetNumNodes()
            for i in range(1, num + 1):  # 1-based indexing
                label = graph.GetNodeLabel(i)
                nodes.append({
                    "index": i,
                    "label": label if label else f"Node {i}",
                })
        except Exception:
            pass
        return nodes

    def toggle_node(self, level: NodeLevel, node_index: int, enable: bool) -> bool:
        """Enable or disable a specific node. Returns True on success."""
        graph = self._get_node_graph(level)
        if not graph:
            return False
        try:
            return graph.SetNodeEnabled(node_index, enable)
        except Exception:
            return False

    def get_level_available(self, level: NodeLevel) -> bool:
        """Check if a level's node graph is currently accessible."""
        return self._get_node_graph(level) is not None
