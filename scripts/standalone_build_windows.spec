# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

ROOT = Path(__file__).resolve().parent.parent

ffmpeg_dir = ROOT / "referential" / "ffmpeg"
ffmpeg_binaries = [
    (str(file), "ffmpeg")
    for file in ffmpeg_dir.iterdir()
    if file.is_file()
]

a = Analysis(
    [str(ROOT / "src" / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=ffmpeg_binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GUI_client",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=str(ROOT / "images" / "icons" / "program_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GUI_client_Windows",
)