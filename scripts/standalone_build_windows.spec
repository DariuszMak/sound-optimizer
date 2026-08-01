# -*- mode: python ; coding: utf-8 -*-
import glob
from pathlib import Path

block_cipher = None

# SPECPATH is injected by PyInstaller = absolute path of the folder
# containing this .spec file (i.e. ..\scripts). Anchor everything to it
# so paths resolve correctly no matter what directory `pyinstaller` is
# actually invoked from.
ROOT = Path(SPECPATH).resolve().parent

ffmpeg_binaries = [(f, 'ffmpeg') for f in glob.glob(str(ROOT / 'referential' / 'ffmpeg' / '*'))]

if not ffmpeg_binaries:
    raise SystemExit(
        f"No ffmpeg binaries found at {ROOT / 'referential' / 'ffmpeg'} - "
        "check the folder exists and contains ffmpeg.exe / ffprobe.exe before building."
    )

a = Analysis(
    [str(ROOT / 'src' / 'main.py')],
    pathex=[str(ROOT / 'src')],
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
#         splash,
    [],
    exclude_binaries=True,
    name='GUI_client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=str(ROOT / 'images' / 'icons' / 'program_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
#    splash.binaries,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GUI_client_Windows'
)
