# maxlamm Node Toggle

A macOS tool that connects to DaVinci Resolve Studio via its Scripting API and toggles color correction nodes on/off using configurable global hotkeys.

## Project Structure

```
main.py              # Entry point — wires UI, hotkey listener, and Resolve connection
resolve_api.py       # DaVinci Resolve Scripting API wrapper (connection, node queries, toggle)
hotkey_manager.py    # Global hotkey capture via pynput + typing detection (macOS Accessibility API)
ui.py                # TKinter GUI — assignment rows, preset management, hotkey recording
data_model.py        # Data model (NodeLevel, NodeAssignment, AssignmentProfile) + JSON persistence
requirements.txt     # Python dependencies
node-toggle.icns     # macOS app icon
node-toggle.png      # App icon (PNG, bundled as data file by PyInstaller)
maxlamm_Node_Toggle.spec  # PyInstaller build spec
```

## Tech Stack

- **Python 3.13** (Homebrew) with TKinter GUI
- **pynput** for global keyboard event capture (wraps macOS Quartz event taps)
- **pyobjc** (ApplicationServices) for Accessibility API text field detection
- **DaVinciResolveScript** — Resolve's official scripting bridge (loaded from `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/`)

## Setup & Run

```bash
# Create venv and install dependencies
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Run
.venv/bin/python3.13 main.py
```

## Build macOS App

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller maxlamm_Node_Toggle.spec --noconfirm
# Output: dist/maxlamm Node Toggle.app
```

## Architecture

### Threading Model

- **Main thread**: TKinter event loop (`root.mainloop()`)
- **Daemon thread**: pynput `keyboard.Listener` — captures global key events via Quartz event tap
- **Thread safety**: UI updates from the listener thread are marshalled via `queue.Queue` + `root.after(50ms)` polling. Never call tkinter methods from the listener thread.

### DaVinci Resolve API

All node operations go through `resolve_api.py`. Key API calls:

| Level | Graph Access |
|-------|-------------|
| Timeline | `timeline.GetNodeGraph()` |
| Clip | `timelineItem.GetNodeGraph()` |
| Group Pre-Clip | `colorGroup.GetPreClipNodeGraph()` |
| Group Post-Clip | `colorGroup.GetPostClipNodeGraph()` |

Graph methods used: `GetNumNodes()`, `GetNodeLabel(nodeIndex)`, `SetNodeEnabled(nodeIndex, isEnabled)`. All node indices are **1-based**.

**Important**: There is no `GetNodeEnabled()` method in the Resolve API. The toggle state is tracked internally (`_toggle_state` on `NodeAssignment`) and can get out of sync if nodes are toggled manually in Resolve.

### Hotkey System

- Supports single keys (`t`) and modifier combos (`cmd+1`, `ctrl+shift+f`)
- Hotkeys are normalized for comparison: modifiers sorted in order `ctrl > alt > shift > cmd`, all lowercase
- **Typing detection** for plain keys (no modifier):
  1. Accessibility API check — if a text field is focused, hotkey is ignored
  2. Burst detection — rapid keystrokes within 80ms are considered typing
- Modifier combos skip typing detection (always intentional)

### Persistence

- Config: `~/.node_toggle/config.json` — current assignments, auto-saved on every change
- Presets: `~/.node_toggle/presets/<name>.json` — named preset files

## Requirements

- **macOS** (Apple Silicon)
- **DaVinci Resolve Studio** (free version lacks Scripting API)
- **Accessibility permissions**: System Settings > Privacy & Security > Accessibility
- Resolve preference: "External scripting using" must be set to **Local** or **Network**

## Common Tasks

- **Add a new node level**: Add to `NodeLevel` enum in `data_model.py`, add graph access in `resolve_api.py._get_node_graph()`
- **Change typing detection sensitivity**: Adjust `burst_threshold_ms` and `burst_count` in `TypingDetector.__init__()` in `hotkey_manager.py`
- **Add new persistence fields**: Update `NodeAssignment.to_dict()` / `from_dict()` in `data_model.py`
