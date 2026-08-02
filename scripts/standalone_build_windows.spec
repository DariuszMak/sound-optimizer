# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

a = Analysis(
    ['..\\src\\main.py'],
    pathex=['..\\src'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt6",
        "PyQt6.sip",
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Sound_optimizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon='..\\images\\icons\\program_icon.ico',
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
    name='Sound_optimizer_Windows'
)
