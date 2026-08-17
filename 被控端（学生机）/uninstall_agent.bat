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

rem 必须先解除「失败自动重启」策略并禁用自启，否则后面的 taskkill /f 在 SCM 看来
rem 就是服务崩溃，30 秒后又会把它拉起来，导致 remove 删不掉、卸载假成功。
echo [*] 解除自动重启策略 + 禁用自启...
sc config  NetControlAgent start= disabled >nul 2>&1
sc failure NetControlAgent reset= 0 actions= "" >nul 2>&1

if exist "CTR.exe" (
    echo [*] 停止服务，并等待它恢复网络（删过的默认路由要加回来，约 10 秒）...
    rem --wait 必须写在 stop 前面：pywin32 用 getopt 解析，遇到第一个非选项参数就停止解析。
    rem 不带 --wait 时 stop 只发一个停止信号就立刻返回，2 秒后的 taskkill 会把正在跑的
    rem _do_restore() 拦腰砍断——默认路由恢复排在最后一步，学生机会永久断网。
    CTR.exe --wait 40 stop
    echo [*] 强杀残留进程（连子进程）...
    taskkill /f /t /im CTR.exe >nul 2>&1
    echo [*] 卸载服务注册...
    CTR.exe remove
    sc query NetControlAgent >nul 2>&1 && sc delete NetControlAgent >nul 2>&1
) else (
    echo [!] 未找到 CTR.exe，用 sc 直接删服务...
    sc stop NetControlAgent >nul 2>&1
    echo [*] 等待服务停止并恢复网络...
    ping -n 16 127.0.0.1 >nul
    taskkill /f /t /im CTR.exe >nul 2>&1
    sc delete NetControlAgent
)

echo.
sc query NetControlAgent >nul 2>&1 && echo [结果] 服务仍存在，请看上方提示 || echo [结果] 已卸载，NetControlAgent 不存在
echo.
echo 提示: 若卸载前网络处于过滤/断网，请先在主控端点"允许上网"恢复，
echo       再卸载，否则学生机可能残留路由/防火墙改动。
echo.
echo 窗口 15 秒后自动关闭，也可按任意键关闭
rem timeout 需要控制台，批量部署时会挂死；用 ping 代替延时
ping -n 16 127.0.0.1 >nul
