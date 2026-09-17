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


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    icon_path = os.path.join(get_resource_dir(), "controller", "assets", "app.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
