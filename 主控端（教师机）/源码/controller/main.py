"""
主控端入口
"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shared.paths import get_app_dir

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
from controller.gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
