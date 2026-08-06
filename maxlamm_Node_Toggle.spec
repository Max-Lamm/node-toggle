# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('node-toggle.png', '.')],
    hiddenimports=[
        'pynput.keyboard._darwin',
        'pynput._util.darwin',
        'AppKit',
        'Foundation',
        'ApplicationServices',
        'HIServices',
        'Quartz',
        'objc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='maxlamm Node Toggle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch='arm64',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='maxlamm Node Toggle',
)

app = BUNDLE(
    coll,
    name='maxlamm Node Toggle.app',
    icon='node-toggle.icns',
    bundle_identifier='com.maxlamm.node-toggle',
    info_plist={
        'CFBundleDisplayName': 'maxlamm Node Toggle',
        'CFBundleShortVersionString': '2.0.0',
        'NSHighResolutionCapable': True,
        'NSAccessibilityUsageDescription': 'Node Toggle needs Accessibility access to capture global hotkeys.',
        'NSInputMonitoringUsageDescription': 'Node Toggle needs Input Monitoring access to capture global hotkeys.',
    },
)
