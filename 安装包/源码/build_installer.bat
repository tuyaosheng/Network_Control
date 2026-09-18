@echo off
cd /d "%~dp0"
echo ========================================
echo  打包主控端安装程序（教师机）
echo ========================================
echo.

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [+] 正在安装 PyInstaller...
    pip install pyinstaller
)

echo [+] 打包主控端...
pyinstaller controller.spec --clean --noconfirm
if errorlevel 1 (
    echo [!] 主控端打包失败
    pause
    exit /b 1
)

echo [+] 打包被控端...
pyinstaller agent.spec --clean --noconfirm
if errorlevel 1 (
    echo [!] 被控端打包失败
    pause
    exit /b 1
)

echo [+] 打包配置生成器...
pyinstaller installer\apply_config.spec --clean --noconfirm
if errorlevel 1 (
    echo [!] 配置生成器打包失败
    pause
    exit /b 1
)

echo [+] 打包被控端一键安装器...
pyinstaller installer\agent_installer.spec --clean --noconfirm
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
