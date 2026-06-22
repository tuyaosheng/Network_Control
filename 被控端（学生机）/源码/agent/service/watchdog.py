"""
守护进程 - 监控主服务进程，被杀死后自动重启
作为独立进程运行，与主服务互相监控
"""
import time
import subprocess
import sys
import os
import logging

logger = logging.getLogger("watchdog")

SERVICE_NAME = "NetControlAgent"
CHECK_INTERVAL = 10  # 秒


def is_service_running() -> bool:
    result = subprocess.run(
        ["sc", "query", SERVICE_NAME],
        capture_output=True, text=True
    )
    return "RUNNING" in result.stdout


def restart_service():
    logger.warning("检测到服务停止，尝试重启...")
    subprocess.run(["sc", "start", SERVICE_NAME], capture_output=True)


def run_watchdog():
    logger.info("守护进程已启动")
    while True:
        try:
            if not is_service_running():
                restart_service()
        except Exception as e:
            logger.error(f"守护进程检测异常: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_watchdog()
