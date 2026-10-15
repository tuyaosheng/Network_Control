@echo off
cd /d "%~dp0"
echo ========================================
echo  打包被控端（学生机）
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
"%PY%" -m PyInstaller agent.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [!] 打包失败，请检查上方错误信息
    pause
    exit /b 1
)

echo [+] 复制 config.json 到 dist\...
copy /y "agent\config.json" "dist\config.json"

echo.
echo ========================================
echo  打包完成！dist\ 目录里已有两个文件：
echo    CTR.exe
echo    config.json
echo.
echo  部署到学生机步骤：
echo  1. 用记事本打开 dist\config.json
echo     把 controller_url 里的 IP 改成教师机 IP
echo  2. 把 CTR.exe 和 config.json 复制到学生机
echo     （比如放到 C:\NetControl\ 里）
echo  3. 在学生机上以管理员身份运行：
echo     CTR.exe install
echo     CTR.exe start
echo ========================================
pause
