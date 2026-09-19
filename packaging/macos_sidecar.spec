# -*- mode: python ; coding: utf-8 -*-
"""Arm64 one-file sidecar consumed as a fixed Tauri application resource."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


repo_root = Path(SPECPATH).resolve().parent

# The application deliberately uses Live's Finder-resolved installed Claude
# Code executable: that exact path supplies both auth evidence and SDK turns.
# A one-file extracted copy cannot retain the installed runtime's macOS
# Keychain identity, so exclude it rather than shipping an unusable duplicate.
binaries = []
provider_datas = collect_data_files(
    "dialektike",
    includes=[
        "providers/*.json",
        "providers/descriptors/*.json",
    ],
)
datas = [
    *collect_data_files(
        "claude_agent_sdk",
        excludes=["_bundled/claude"],
    ),
    *provider_datas,
]
hiddenimports = sorted(
    set(
        collect_submodules("claude_agent_sdk")
        + collect_submodules("core")
        + collect_submodules("dialektike")
    )
)

analysis = Analysis(
    [str(repo_root / "packaging" / "macos_sidecar_entry.py")],
    pathex=[str(repo_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="dialektike-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
