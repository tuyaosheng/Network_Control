"""
系统托盘图标 - 支持隐藏/显示，退出需密码验证
"""
import threading
import logging
import hashlib
import sys

logger = logging.getLogger("tray")

try:
    import pystray
    from pystray import MenuItem, Menu
    from PIL import Image, ImageDraw
    PYSTRAY_OK = True
except ImportError:
    PYSTRAY_OK = False
    logger.warning("pystray/Pillow 未安装，托盘图标不可用")

try:
    from PyQt6.QtWidgets import QInputDialog, QLineEdit, QApplication
    QT_OK = True
except ImportError:
    QT_OK = False

DEFAULT_PASSWORD_HASH = hashlib.sha256(b"admin123").hexdigest()

STATE_NORMAL     = "normal"
STATE_WHITELIST  = "whitelist"
STATE_BLACKLIST  = "blacklist"
STATE_DISCONNECT = "disconnect"

_STATE_COLORS = {
    STATE_NORMAL:     (100, 100, 100),
    STATE_WHITELIST:  (0, 180, 0),
    STATE_BLACKLIST:  (0, 100, 200),
    STATE_DISCONNECT: (200, 40, 40),
}

_STATE_LABELS = {
    STATE_NORMAL:     "○ 正常上网",
    STATE_WHITELIST:  "● 白名单过滤中",
    STATE_BLACKLIST:  "● 黑名单过滤中",
    STATE_DISCONNECT: "✕ 已断网（保留局域网）",
}


def _make_icon_image(color=(0, 120, 215)):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color)
    draw.rectangle([22, 32, 42, 50], fill=(255, 255, 255))
    draw.arc([26, 22, 38, 36], 200, 340, fill=(255, 255, 255), width=3)
    return img


def _ask_password(prompt="请输入退出密码") -> str | None:
    if not QT_OK:
        return None
    app = QApplication.instance() or QApplication(sys.argv)
    text, ok = QInputDialog.getText(None, "验证", prompt,
                                    QLineEdit.EchoMode.Password)
    return text if ok else None


class AgentTray:
    def __init__(self, password_hash: str = DEFAULT_PASSWORD_HASH,
                 visible: bool = True,
                 on_exit_confirmed=None):
        self.password_hash = password_hash
        self.visible = visible
        self.on_exit_confirmed = on_exit_confirmed
        self._icon = None
        self._thread: threading.Thread | None = None
        self._net_state: str = STATE_NORMAL

    def _check_password(self) -> bool:
        pwd = _ask_password()
        if pwd is None:
            return False
        return hashlib.sha256(pwd.encode()).hexdigest() == self.password_hash

    def _on_exit(self, icon, item):
        if self._check_password():
            icon.stop()
            if self.on_exit_confirmed:
                self.on_exit_confirmed()
        else:
            logger.warning("托盘退出：密码错误")

    def _build_menu(self):
        label = _STATE_LABELS.get(self._net_state, "○ 正常上网")
        return Menu(
            MenuItem(f"网络控制 [{label}]", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("退出（需密码）", self._on_exit),
        )

    def _run_icon(self):
        try:
            self._icon.run()
        except Exception as e:
            logger.warning(f"托盘图标无法显示（可能运行于无桌面会话）: {e}")

    def start(self):
        if not PYSTRAY_OK or not self.visible:
            logger.info("托盘图标已禁用")
            return
        color = _STATE_COLORS.get(self._net_state, (100, 100, 100))
        img = _make_icon_image(color)
        self._icon = pystray.Icon("NetControl", img, "网络控制-被控端",
                                   menu=self._build_menu())
        self._thread = threading.Thread(target=self._run_icon, daemon=True)
        self._thread.start()
        logger.info("托盘图标已启动")

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def set_net_state(self, state: str):
        self._net_state = state
        if self._icon:
            color = _STATE_COLORS.get(state, (100, 100, 100))
            self._icon.icon = _make_icon_image(color)
            self._icon.menu = self._build_menu()
            try:
                self._icon.update_menu()
            except Exception:
                pass
