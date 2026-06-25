@echo off
chcp 65001 >nul
title CTR 卸载

rem 自动以管理员重启（弹一次 UAC；旧窗口会停在此）
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"

echo ========================================
echo  CTR 卸载（管理员）
echo ========================================
echo.

if exist "CTR.exe" (
    echo [*] 停止服务...
    CTR.exe stop >nul 2>&1
    timeout /t 2 /nobreak >nul
    echo [*] 强杀残留进程（连子进程）...
    taskkill /f /t /im CTR.exe >nul 2>&1
    echo [*] 卸载服务注册...
    CTR.exe remove
    sc query NetControlAgent >nul 2>&1 && sc delete NetControlAgent >nul 2>&1
) else (
    echo [!] 未找到 CTR.exe，用 sc 直接删服务...
    taskkill /f /t /im CTR.exe >nul 2>&1
    sc stop   NetControlAgent >nul 2>&1
    sc delete NetControlAgent
)

echo.
sc query NetControlAgent >nul 2>&1 && echo [结果] 服务仍存在，请看上方提示 || echo [结果] 已卸载，NetControlAgent 不存在
echo.
echo 提示: 若卸载前网络处于过滤/断网，请先在主控端点"允许上网"恢复，
echo       再卸载，否则学生机可能残留路由/防火墙改动。
echo.
echo 窗口 15 秒后自动关闭，也可按任意键关闭
timeout /t 15
