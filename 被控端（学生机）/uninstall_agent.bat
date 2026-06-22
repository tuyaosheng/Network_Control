@echo off
chcp 65001 >nul
:: ============================================================
::  被控端卸载脚本（双击即可，会自动申请管理员权限）
:: ============================================================

:: ── 自动提权 ──
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] 需要管理员权限，正在申请（请在弹窗中点"是"）...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"

echo ========================================
echo  被控端卸载（管理员）
echo ========================================
echo.

if not exist "被控端.exe" (
    echo [!] 未找到 被控端.exe，尝试用 sc 直接删除服务...
    sc stop   NetControlAgent >nul 2>&1
    sc delete NetControlAgent
    goto done
)

echo [+] 正在停止服务...
被控端.exe stop >nul 2>&1
timeout /t 2 >nul

echo [+] 正在卸载服务...
被控端.exe remove
if errorlevel 1 (
    echo [!] 卸载可能未完成，尝试用 sc 强制删除...
    sc delete NetControlAgent
)

:done
echo.
echo ========================================
echo  完成！NetControlAgent 服务已卸载。
echo  注意：网络状态若仍处于过滤/断网，请先在主控端点"允许上网"恢复，
echo        再卸载，避免学生机残留路由/防火墙规则。
echo ========================================
pause
