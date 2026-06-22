@echo off
title 被控端卸载

rem 自动申请管理员(点一次 UAC 是;新窗口会停留)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"

echo ========================================
echo  被控端卸载(管理员)
echo ========================================
echo.

if exist "被控端.exe" (
    echo [*] 停止服务...
    被控端.exe stop >nul 2>&1
    timeout /t 2 /nobreak >nul
    echo [*] 卸载服务...
    被控端.exe remove
    sc query NetControlAgent >nul 2>&1 && sc delete NetControlAgent >nul 2>&1
) else (
    echo [!] 未找到 被控端.exe,用 sc 直接删除服务...
    sc stop   NetControlAgent >nul 2>&1
    sc delete NetControlAgent
)

echo.
sc query NetControlAgent >nul 2>&1 && echo [结果] 服务仍存在,请看上方输出 || echo [结果] 已卸载,NetControlAgent 不存在
echo.
echo 提示: 若卸载前网络处于过滤/断网,请先在主控端点"允许上网"恢复,
echo       以免学生机残留路由/防火墙规则。
echo.
echo 窗口 15 秒后自动关闭,也可按任意键关闭
timeout /t 15
