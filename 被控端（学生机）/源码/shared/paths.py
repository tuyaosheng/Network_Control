import sys
import os


def get_app_dir() -> str:
    """打包后返回 exe 所在目录，开发时返回项目根目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # shared/paths.py -> shared/ -> project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
