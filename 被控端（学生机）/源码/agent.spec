# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

root = os.path.dirname(os.path.abspath(SPEC))

ws_datas, ws_binaries, ws_hidden = collect_all('websockets')
pystray_datas, pystray_binaries, pystray_hidden = collect_all('pystray')
dnslib_datas, dnslib_binaries, dnslib_hidden = collect_all('dnslib')

a = Analysis(
    [os.path.join(root, 'agent', 'service', 'windows_service.py')],
    pathex=[root],
    binaries=ws_binaries + pystray_binaries + dnslib_binaries,
    datas=ws_datas + pystray_datas + dnslib_datas,
    hiddenimports=ws_hidden + pystray_hidden + dnslib_hidden + [
        # pywin32 — win32timezone 是高频遗漏项，必须显式声明
        'win32service',
        'win32serviceutil',
        'servicemanager',
        'win32event',
        'win32timezone',
        'win32api',
        'win32con',
        'win32security',
        'win32ts',
        'win32process',
        'win32profile',
        'winerror',
        # agent 内部模块（_run() 中动态 import，PyInstaller 静态扫描不到）
        'agent.main',
        'agent.filter.dns_server',
        'agent.filter.firewall',
        'agent.client.ws_client',
        'agent.tray.tray_icon',
        'agent.ui',
        'agent.ui.lock_screen',
        'shared.protocol',
        'shared.paths',
        # PIL（托盘图标）
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        # PyQt6（密码对话框）
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.sip',
        # stdlib
        'asyncio',
        'ipaddress',
        'hashlib',
        'subprocess',
        'socket',
        'threading',
        'sqlite3',
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
    name='被控端',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 不要求管理员清单：服务由 SCM 以 SYSTEM 启动不受影响；安装走已提权的 install_agent.bat；
    # 而锁屏要 CreateProcessAsUser 注入【用户会话】，exe 若要求提升会报 740「需要提升」、注入失败。
    uac_admin=False,
)
