"""
网线拔出锁屏 - 全屏覆盖，需密码或网线恢复才能解锁
60 秒内未解锁则关机
"""
import hashlib
import subprocess
import sys
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont


class LockScreen(QWidget):
    def __init__(self, password_hash: str):
        super().__init__()
        self.password_hash  = password_hash
        self.remaining      = 60
        self._network_back  = False   # 网络监控线程写入
        self._shutdown_done = False

        self._build_ui()
        self._start_timer()
        self._start_network_monitor()

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet("QWidget { background-color: #000080; }")
        self.showFullScreen()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(18)

        def lbl(text, size, color="white", bold=False):
            w = QLabel(text)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            f = QFont("微软雅黑", size)
            if bold:
                f.setBold(True)
            w.setFont(f)
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addStretch(2)
        layout.addWidget(lbl("！  网 线 已 被 拔 出  ！", 40, "#FFFFFF", True))
        layout.addSpacing(10)

        self._countdown_lbl = lbl(
            "请在 60 秒内恢复网线，或输入解锁密码，否则计算机将自动关机",
            15, "#FFFF00"
        )
        self._countdown_lbl.setWordWrap(True)
        layout.addWidget(self._countdown_lbl)

        layout.addSpacing(20)
        layout.addWidget(lbl("网线已被拔出，请输入解锁密码：", 18))

        self._pwd = QLineEdit()
        self._pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._pwd.setFixedSize(320, 46)
        self._pwd.setFont(QFont("微软雅黑", 15))
        self._pwd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pwd.setStyleSheet(
            "background: white; color: black; border-radius: 4px; padding: 4px;"
        )
        self._pwd.returnPressed.connect(self._verify)
        layout.addWidget(self._pwd, alignment=Qt.AlignmentFlag.AlignCenter)

        btn = QPushButton("确认解锁")
        btn.setFixedSize(200, 46)
        btn.setFont(QFont("微软雅黑", 14))
        btn.setStyleSheet(
            "background: #4CAF50; color: white; border-radius: 4px;"
        )
        btn.clicked.connect(self._verify)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._err_lbl = lbl("", 13, "#FF6666")
        layout.addWidget(self._err_lbl)

        layout.addStretch(2)

    def _start_timer(self):
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _tick(self):
        if self._network_back:
            self._timer.stop()
            QApplication.quit()
            return

        self.remaining -= 1
        self._countdown_lbl.setText(
            f"请在 {self.remaining} 秒内恢复网线，或输入解锁密码，否则计算机将自动关机"
        )

        if self.remaining <= 0 and not self._shutdown_done:
            self._shutdown_done = True
            self._timer.stop()
            subprocess.run(["shutdown", "/s", "/t", "0"])

    def _verify(self):
        pwd = self._pwd.text()
        if hashlib.sha256(pwd.encode()).hexdigest() == self.password_hash:
            self._timer.stop()
            QApplication.quit()
        else:
            self._err_lbl.setText("密码错误，请重试")
            self._pwd.clear()
            self._pwd.setFocus()

    def _start_network_monitor(self):
        def monitor():
            import time
            time.sleep(4)   # 给锁屏显示一点时间再开始检查
            while not self._network_back:
                time.sleep(3)
                try:
                    r = subprocess.run(
                        ['powershell', '-Command',
                         '(Get-NetAdapter | Where-Object {'
                         '$_.Status -eq "Up" -and $_.Name -notmatch "Loopback"}).Count'],
                        capture_output=True, text=True, timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    s = r.stdout.strip()
                    if s.isdigit() and int(s) > 0:
                        self._network_back = True
                except Exception:
                    pass

        threading.Thread(target=monitor, daemon=True).start()

    def keyPressEvent(self, event):
        # 屏蔽 Esc / Alt+F4
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F4):
            return
        super().keyPressEvent(event)


def run_lock_screen(password_hash: str):
    app = QApplication(sys.argv[:1])
    screen = LockScreen(password_hash)
    screen.show()
    sys.exit(app.exec())
