import sys
import os


def get_app_dir() -> str:
    """打包后返回 exe 所在目录，开发时返回项目根目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # shared/paths.py -> shared/ -> project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_dir() -> str:
    """只读资源（图标等）所在根目录：打包后为 PyInstaller 解压临时目录，开发时为项目根目录。"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
