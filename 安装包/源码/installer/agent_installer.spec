# -*- mode: python ; coding: utf-8 -*-
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

a = Analysis(
    [os.path.join(root, 'installer', 'agent_installer.py')],
    pathex=[root],
    binaries=[],
    # 内置被控端本体和卸载脚本：学生端只需复制这一个 exe（先打包 agent.spec 生成 dist\CTR.exe）
    datas=[
        (os.path.join(root, 'dist', 'CTR.exe'), '.'),
        (os.path.join(root, 'uninstall_agent.bat'), '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt6'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='网络控制器学生端',
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
    uac_admin=True,
    icon=os.path.join(root, 'installer', 'assets', 'student_icon.ico'),
)
