@echo off
title 被控端安装

rem 自动申请管理员(点一次 UAC 是,装服务必须;新窗口会停留)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
set "LOG=%~dp0install_agent.log"

echo [%date% %time%] 安装开始 目录=%~dp0> "%LOG%"

if not exist "被控端.exe" (
    echo [错误] 这个文件夹里没有 被控端.exe>> "%LOG%"
    echo.
    echo [错误] 这个文件夹里没有 被控端.exe
    echo 请把 被控端.exe  config.json  install_agent.bat 放在同一个文件夹,
    echo 并先把压缩包解压出来再运行。
    echo.
    timeout /t 20
    exit /b 1
)

echo 正在安装被控端服务,请稍候...
被控端.exe stop   >> "%LOG%" 2>&1
被控端.exe remove >> "%LOG%" 2>&1
被控端.exe install >> "%LOG%" 2>&1
被控端.exe start   >> "%LOG%" 2>&1

sc query NetControlAgent | findstr /i "STATE" >> "%LOG%" 2>&1
echo [%date% %time%] 安装结束>> "%LOG%"

echo.
echo ===== 安装日志(已保存到 install_agent.log) =====
type "%LOG%"
echo =================================================
echo.
sc query NetControlAgent | findstr /i "RUNNING" >nul && echo 结果: 安装成功 服务 RUNNING || echo 结果: 未运行,请看上方日志
echo.
echo 窗口 20 秒后自动关闭,也可按任意键关闭
timeout /t 20
