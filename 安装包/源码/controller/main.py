"""
主控端入口
"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shared.paths import get_app_dir, get_resource_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(get_app_dir(), "controller.log"),
            encoding="utf-8"
        )
    ]
)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from controller.gui.main_window import MainWindow

APP_NAME = "网络控制器主控端"
_MUTEX_NAME = "Local\\NetControl_Controller_SingleInstance"
_instance_mutex = None   # 保持句柄到进程结束，进程退出时系统自动释放


def _ensure_single_instance() -> bool:
    """同一用户会话只允许一个主控端：两个实例会同时占用 8770 控制接口（Windows 允许重复绑定），
    外部调用可能落到连不上任何被控端的那个实例上。
    已有实例时把它的窗口提到前台，返回 False。"""
    global _instance_mutex
    import ctypes
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _instance_mutex = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if kernel32.GetLastError() != 183:   # ERROR_ALREADY_EXISTS
        return True

    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, APP_NAME)
    if hwnd:
        user32.ShowWindow(ctypes.c_void_p(hwnd), 9)   # SW_RESTORE：最小化时还原
        user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    else:
        user32.MessageBoxW(None, "网络控制器主控端已经在运行。", APP_NAME, 0x40)
    return False


def main():
    if not _ensure_single_instance():
        return
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    icon_path = os.path.join(get_resource_dir(), "controller", "assets", "app.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.show()
    code = app.exec()
    # 窗口关闭时 closeEvent 已停服务、等 DB 写完。这里直接结束进程，不走 Python 的退出清理：
    # 后台的 asyncio / HTTP / 线程池线程在退出清理阶段可能互相等待，导致窗口关了进程还在。
    logging.shutdown()
    os._exit(code)


if __name__ == "__main__":
    main()
