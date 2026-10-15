"""
学生端安装器的内嵌配置 - 把 config.json 追加到 exe 末尾，做成"单个文件即可部署"。

每台教师机的配置（教师机 IP / 网段 / 密码哈希）是安装时才知道的，无法在打包时写进去，
所以由 apply_config 在安装时把配置追加到学生端安装器 exe 的末尾：

    [原始 exe 字节][config JSON (UTF-8)][JSON 长度: 8 字节小端][MAGIC: 8 字节]

PyInstaller 单文件 exe 允许末尾追加数据（启动时从文件尾向前搜索自己的归档标记），
安装器运行时读自身 sys.executable 的末尾即可取回配置。
"""
import json
import os
import shutil
import struct

MAGIC = b"NCCFGv1!"
_FOOTER_LEN = 8 + len(MAGIC)
_MAX_CONFIG_LEN = 1024 * 1024


def write_with_config(template_path: str, out_path: str, config: dict) -> None:
    """复制 template_path 到 out_path，并在末尾追加 config。"""
    raw = json.dumps(config, ensure_ascii=False).encode("utf-8")
    tmp_path = out_path + ".tmp"
    shutil.copyfile(template_path, tmp_path)
    with open(tmp_path, "ab") as f:
        f.write(raw)
        f.write(struct.pack("<Q", len(raw)))
        f.write(MAGIC)
    os.replace(tmp_path, out_path)


def read_config(exe_path: str) -> dict | None:
    """读取 exe 末尾追加的配置；没有追加过则返回 None。"""
    try:
        size = os.path.getsize(exe_path)
        if size < _FOOTER_LEN:
            return None
        with open(exe_path, "rb") as f:
            f.seek(size - _FOOTER_LEN)
            footer = f.read(_FOOTER_LEN)
            if footer[8:] != MAGIC:
                return None
            (length,) = struct.unpack("<Q", footer[:8])
            if length <= 0 or length > _MAX_CONFIG_LEN or length > size - _FOOTER_LEN:
                return None
            f.seek(size - _FOOTER_LEN - length)
            return json.loads(f.read(length).decode("utf-8"))
    except (OSError, ValueError):
        return None
