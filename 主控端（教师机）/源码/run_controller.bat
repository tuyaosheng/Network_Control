@echo off
:: 启动主控端（教师机，普通权限即可）
cd /d %~dp0
python controller\main.py
pause
