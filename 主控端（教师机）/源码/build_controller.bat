@echo off
cd /d "%~dp0"
echo ========================================
echo  打包主控端（教师机）
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

echo [+] 开始打包...
"%PY%" -m PyInstaller controller.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [!] 打包失败，请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo ========================================
echo  打包完成！
echo  输出文件: dist\网络控制器主控端.exe
echo  数据库和日志将自动在 exe 同目录生成
echo ========================================
pause
