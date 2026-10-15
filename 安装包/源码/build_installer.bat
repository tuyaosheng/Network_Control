@echo off
cd /d "%~dp0"
echo ========================================
echo  打包主控端安装程序（教师机）
echo ========================================
echo.

rem 只用项目自带 .venv 打包，不回退到全局环境：
rem 全局环境的 websockets 13 及以上会让主控端运行时报错，多余的包还会让安装包超过 GitHub 100MB 上限
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [!] 未找到项目虚拟环境：.venv\Scripts\python.exe
    echo     请先在项目根目录创建虚拟环境并安装依赖：
    echo       python -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
    echo     本脚本不会使用全局 Python 打包。
    pause
    exit /b 1
)
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [!] .venv 中没有安装 PyInstaller，请先执行：
    echo       .venv\Scripts\python.exe -m pip install pyinstaller
    pause
    exit /b 1
)
echo [+] 使用虚拟环境: %PY%

echo [+] 打包主控端...
"%PY%" -m PyInstaller controller.spec --clean --noconfirm
if errorlevel 1 (
    echo [!] 主控端打包失败
    pause
    exit /b 1
)

echo [+] 打包被控端...
"%PY%" -m PyInstaller agent.spec --clean --noconfirm
if errorlevel 1 (
    echo [!] 被控端打包失败
    pause
    exit /b 1
)

echo [+] 打包配置生成器...
"%PY%" -m PyInstaller installer\apply_config.spec --clean --noconfirm
if errorlevel 1 (
    echo [!] 配置生成器打包失败
    pause
    exit /b 1
)

echo [+] 打包被控端一键安装器...
"%PY%" -m PyInstaller installer\agent_installer.spec --clean --noconfirm
if errorlevel 1 (
    echo [!] 被控端一键安装器打包失败
    pause
    exit /b 1
)

echo [+] 查找 Inno Setup 编译器 (ISCC.exe)...
set ISCC=
where ISCC.exe >nul 2>&1
if not errorlevel 1 (
    set ISCC=ISCC.exe
) else if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
) else if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
) else if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
) else if exist "E:\Inno Setup 7\ISCC.exe" (
    set "ISCC=E:\Inno Setup 7\ISCC.exe"
)

if "%ISCC%"=="" (
    echo     常见路径未找到，尝试从注册表查找已安装的 Inno Setup...
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$k = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue ^| Where-Object { $_.DisplayName -like '*Inno Setup*' -and $_.InstallLocation } ^| Select-Object -First 1 -ExpandProperty InstallLocation; if ($k) { Join-Path $k 'ISCC.exe' }"`) do set "ISCC=%%P"
)

if not "%ISCC%"=="" if not exist "%ISCC%" set ISCC=

if "%ISCC%"=="" (
    echo.
    echo [!] 未找到 Inno Setup，请先安装：https://jrsoftware.org/isdl.php
    echo     安装完成后重新运行本脚本
    pause
    exit /b 1
)

echo     使用: %ISCC%
echo [+] 编译安装程序...
"%ISCC%" installer\setup.iss
if errorlevel 1 (
    echo [!] 安装程序编译失败，请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo ========================================
echo  打包完成！
echo  输出文件: dist\网络控制器CTR安装程序.exe
echo ========================================
pause
