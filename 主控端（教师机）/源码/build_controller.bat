@echo off
cd /d "%~dp0"
echo ========================================
echo  打包主控端（教师机）
echo ========================================
echo.

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [+] 正在安装 PyInstaller...
    pip install pyinstaller
)

echo [+] 开始打包...
pyinstaller controller.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [!] 打包失败，请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo ========================================
echo  打包完成！
echo  输出文件: dist\主控端.exe
echo  数据库和日志将自动在 exe 同目录生成
echo ========================================
pause
