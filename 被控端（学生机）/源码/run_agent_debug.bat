@echo off
:: 被控端调试模式（以管理员权限运行，控制台可见）
cd /d %~dp0
python agent\main.py
pause
