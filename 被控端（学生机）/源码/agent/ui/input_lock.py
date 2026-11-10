"""
键盘鼠标锁定 - 独立进程，由被控端服务注入到用户桌面运行（入口：CTR.exe --input-lock <agent_pid>）

原理：在用户桌面安装 WH_KEYBOARD_LL / WH_MOUSE_LL 低级钩子，回调一律返回 1 吞掉输入。
- Ctrl+Alt+Del 由系统安全桌面处理，钩子拦不住，这是有意保留的逃生口
- 解锁 = 被控端杀掉本进程（按命令行 --input-lock 匹配），与锁屏进程同一套机制
- 被控端进程退出（崩溃 / 服务被停）时本进程自行退出，不会把学生机永久锁死
"""
import ctypes
import ctypes.wintypes as wt
import sys

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x102

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD


def _swallow(nCode, wParam, lParam):
    # nCode < 0 必须交给下一个钩子；>=0 一律吞掉
    if nCode < 0:
        return user32.CallNextHookEx(None, nCode, wParam, lParam)
    return 1


# 回调对象必须持有引用，否则被 GC 后钩子调用到野指针会让进程崩溃
_kb_proc = HOOKPROC(_swallow)
_ms_proc = HOOKPROC(_swallow)


def _install_hooks():
    hmod = kernel32.GetModuleHandleW(None)
    kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kb_proc, hmod, 0)
    ms = user32.SetWindowsHookExW(WH_MOUSE_LL, _ms_proc, hmod, 0)
    if not kb or not ms:
        raise OSError(f"安装输入钩子失败: {ctypes.get_last_error()}")
    return kb, ms


def _agent_alive_fn(agent_pid: int):
    """返回「被控端是否还活着」的检查函数；打不开句柄（权限不足）时无法监视，视为一直活着。"""
    if not agent_pid:
        return lambda: True
    h = kernel32.OpenProcess(SYNCHRONIZE, False, agent_pid)
    if not h:
        return lambda: True
    return lambda: kernel32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT


def run_input_lock(agent_pid: int = 0):
    kb, ms = _install_hooks()
    alive = _agent_alive_fn(agent_pid)

    try:
        from PyQt6.QtWidgets import QApplication, QLabel
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QFont
    except Exception:
        QApplication = None

    if QApplication is not None:
        app = QApplication(sys.argv)
        banner = QLabel("🔒 键盘和鼠标已被教师锁定")
        banner.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        banner.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        banner.setFont(QFont("微软雅黑", 14))
        banner.setStyleSheet("background:#c0392b;color:white;padding:8px 24px;")
        banner.adjustSize()
        screen = app.primaryScreen().geometry()
        banner.move(screen.x() + (screen.width() - banner.width()) // 2, screen.y() + 8)
        banner.show()

        timer = QTimer()
        timer.timeout.connect(lambda: None if alive() else app.quit())
        timer.start(2000)
        app.exec()
    else:
        # 没有 Qt 时退化成纯 Win32 消息循环（钩子必须有消息循环才会被回调）
        msg = wt.MSG()
        while alive():
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                kernel32.Sleep(50)

    user32.UnhookWindowsHookEx(kb)
    user32.UnhookWindowsHookEx(ms)
