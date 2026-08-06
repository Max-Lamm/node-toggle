# Node Toggle

A lightweight macOS utility for toggling DaVinci Resolve color correction nodes with global hotkeys.

![Screenshot](screenshot.png)

## Features

- **Global Hotkeys** — Toggle nodes on/off even when Resolve is not in focus
- **Multiple Node Levels** — Supports Timeline, Clip, Group Pre-Clip, and Group Post-Clip nodes
- **Preset System** — Save, load, and delete hotkey configurations
- **Auto-Detection** — Automatically connects to DaVinci Resolve with live status polling
- **Live Node Discovery** — Populates node dropdowns directly from the Resolve scripting API
- **Smart Typing Detection** — Suppresses hotkey triggers during fast typing bursts to prevent accidental toggles

## Requirements

- macOS
- Python 3.13+
- DaVinci Resolve Studio (with scripting enabled)
- Accessibility permissions granted (System Settings > Privacy & Security > Accessibility)

## Installation

```bash
git clone https://github.com/Max-Lamm/node-toggle.git
cd node-toggle
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
source .venv/bin/activate
python main.py
```

1. Make sure DaVinci Resolve Studio is running — the app auto-detects the connection
2. Click **+ Add Assignment** to create a new hotkey mapping
3. Select a **Level** (Timeline, Clip, Group Pre-Clip, or Group Post-Clip)
4. Select a **Node** from the dropdown (populated from Resolve)
5. Click **Record** and press the desired key combination
6. Use **Presets** to save and switch between different configurations

## Build

Build a standalone macOS app bundle with PyInstaller:

```bash
source .venv/bin/activate
pip install pyinstaller
pyinstaller maxlamm_Node_Toggle.spec --noconfirm
```

Output: `dist/maxlamm Node Toggle.app`

The build spec (`maxlamm_Node_Toggle.spec`) targets Apple Silicon (`arm64`) and
bundles the app icon (`node-toggle.icns`) plus the pyobjc/pynput hidden imports
required for global hotkey capture.

The built app needs its own Accessibility **and** Input Monitoring permission,
grant both under System Settings > Privacy & Security on first launch.

The app is ad-hoc signed (no Apple Developer ID), so every rebuild produces a
new code signature hash. macOS ties TCC (Accessibility/Input Monitoring)
approval to that hash, so a permission granted to a previous build silently
stops applying to the new one — the app looks "enabled" in System Settings
but the toggle doesn't actually cover the freshly built binary. If hotkeys
stop working after a rebuild, reset and re-grant:

```bash
tccutil reset Accessibility com.maxlamm.node-toggle
tccutil reset ListenEvent com.maxlamm.node-toggle
```

Then relaunch the app and re-approve both prompts. Set `NODE_TOGGLE_DEBUG=1`
before launching to write a permissions snapshot to
`~/.node_toggle/diagnose.log` if the status line doesn't clear up.

## Configuration

All configuration is stored in `~/.node_toggle/`:

| Path | Description |
|------|-------------|
| `config.json` | Current assignment profile |
| `presets/*.json` | Saved presets |

## License

MIT
