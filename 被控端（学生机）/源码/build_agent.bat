@echo off
cd /d "%~dp0"
echo ========================================
echo  打包被控端（学生机）
echo ========================================
echo.

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [+] 正在安装 PyInstaller...
    pip install pyinstaller
)

echo [+] 开始打包...
pyinstaller agent.spec --clean --noconfirm

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
echo    被控端.exe
echo    config.json
echo.
echo  部署到学生机步骤：
echo  1. 用记事本打开 dist\config.json
echo     把 controller_url 里的 IP 改成教师机 IP
echo  2. 把 被控端.exe 和 config.json 复制到学生机
echo     （比如放到 C:\NetControl\ 里）
echo  3. 在学生机上以管理员身份运行：
echo     被控端.exe install
echo     被控端.exe start
echo ========================================
pause
