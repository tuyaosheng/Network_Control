# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

root = os.path.dirname(os.path.abspath(SPEC))

ws_datas, ws_binaries, ws_hidden = collect_all('websockets')

a = Analysis(
    [os.path.join(root, 'controller', 'main.py')],
    pathex=[root],
    binaries=ws_binaries,
    datas=ws_datas,
    hiddenimports=ws_hidden + [
        'PyQt6.sip',
        'PyQt6.QtPrintSupport',
        'shared.paths',
        'controller.db.database',
        'controller.server.ws_server',
        'controller.gui.main_window',
        'controller.gui.machine_panel',
        'controller.gui.rule_panel',
        'controller.dep_discover',
        'shared.protocol',
        'sqlite3',
        'ipaddress',
        'asyncio',
        'requests',
        'bs4',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='主控端',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
)
