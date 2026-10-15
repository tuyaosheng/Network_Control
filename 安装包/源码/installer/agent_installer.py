"""
被控端一键安装器 - 单个 exe 即可部署：双击自动提权（UAC），把被控端解压到固定目录并装服务。

exe 内置 CTR.exe 和 uninstall_agent.bat（PyInstaller datas），教师机安装时 apply_config
再把这台教师机对应的 config.json 追加到 exe 末尾（见 installer/payload.py）。
所以复制这一个 exe 到学生机任意位置（桌面、U 盘）双击即可，装完后这个 exe 可以删掉。

安装位置固定为 C:\\Users\\Public\\Documents\\NetControl，服务从这里运行，
和 exe 放在哪里无关。

兼容旧的手动部署方式：exe 末尾没有内嵌配置时，读取同目录下的 config.json；
包内没有 CTR.exe 时（开发调试），使用同目录下的 CTR.exe。
"""
import ctypes
import datetime
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from installer.payload import read_config

SERVICE_NAME = "NetControlAgent"
INSTALL_DIR = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Documents", "NetControl")
UNINSTALL_SCRIPT = "uninstall_agent.bat"


def _exe_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _bundle_dir() -> str:
    """PyInstaller 解压目录（内置的 CTR.exe 在这里）；未打包时退回 exe 所在目录。"""
    return getattr(sys, "_MEIPASS", _exe_dir())


def _find_bundled(name: str) -> str | None:
    for d in (_bundle_dir(), _exe_dir()):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def _load_config() -> dict | None:
    if getattr(sys, "frozen", False):
        cfg = read_config(sys.executable)
        if cfg:
            return cfg
    side = os.path.join(_exe_dir(), "config.json")
    if os.path.exists(side):
        with open(side, encoding="utf-8") as f:
            return json.load(f)
    return None


def _child_env() -> dict:
    # CTR.exe 也是 PyInstaller 单文件程序，让它按独立程序启动，不继承本安装器的解压环境
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _run(args, logf) -> None:
    logf.write(f"$ {' '.join(args)}\n")
    logf.flush()
    subprocess.run(args, stdout=logf, stderr=logf, env=_child_env())


def _log(logf, msg: str) -> None:
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    logf.write(line + "\n")
    logf.flush()


def _copy_with_retry(src: str, dst: str, logf, attempts: int = 10) -> None:
    """旧服务刚停止时文件可能还被占用，稍等重试。"""
    for i in range(attempts):
        try:
            shutil.copyfile(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            _log(logf, f"{os.path.basename(dst)} 被占用，1 秒后重试...")
            time.sleep(1)


def _fail(msg: str, hint: str = "") -> int:
    print()
    print(f"[错误] {msg}")
    if hint:
        print(hint)
    input("\n按回车键关闭...")
    return 1


def main() -> int:
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("网络控制器学生端")
    except Exception:
        pass

    ctr_src = _find_bundled("CTR.exe")
    if not ctr_src:
        return _fail("安装程序里没有找到 CTR.exe",
                     "请使用教师机安装目录「被控端（学生机）」里的安装程序。")

    config = _load_config()
    if not config:
        return _fail("没有找到被控端配置",
                     "请使用教师机安装目录「被控端（学生机）」里的安装程序，\n"
                     "或者把 config.json 和这个安装程序放在同一个文件夹。")

    os.makedirs(INSTALL_DIR, exist_ok=True)
    ctr_exe = os.path.join(INSTALL_DIR, "CTR.exe")
    log_path = os.path.join(INSTALL_DIR, "install_agent.log")

    with open(log_path, "a", encoding="utf-8") as logf:
        _log(logf, f"安装开始 安装目录={INSTALL_DIR} 安装程序={sys.executable}")
        _log(logf, f"主控端地址: {config.get('controller_url', '?')}")
        print("正在安装 CTR 服务，请稍候...")

        # 升级场景：旧版可能正处于断网/白名单状态，停止时要等它把默认路由加回来再 remove。
        # 先解除旧版的失败自动重启策略，否则旧服务可能在 remove 后被 SCM 拉起来。
        # 停止/卸载按服务名操作，用内置的 CTR.exe 即可（旧服务可能装在别的目录，比如桌面）。
        _run(["sc", "failure", SERVICE_NAME, "reset=", "0", "actions=", ""], logf)
        _run([ctr_src, "--wait", "40", "stop"], logf)
        _run([ctr_src, "remove"], logf)
        # 残留的锁屏进程（CTR.exe --lock）会占用安装目录里的 CTR.exe
        _run(["taskkill", "/f", "/t", "/im", "CTR.exe"], logf)

        try:
            _copy_with_retry(ctr_src, ctr_exe, logf)
            uninstall_src = _find_bundled(UNINSTALL_SCRIPT)
            if uninstall_src:
                shutil.copyfile(uninstall_src, os.path.join(INSTALL_DIR, UNINSTALL_SCRIPT))
            with open(os.path.join(INSTALL_DIR, "config.json"), "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except OSError as e:
            _log(logf, f"[错误] 复制文件失败: {e}")
            return _fail(f"复制文件到 {INSTALL_DIR} 失败: {e}")
        _log(logf, "文件已解压到安装目录")

        _run([ctr_exe, "install"], logf)
        _run([ctr_exe, "start"], logf)

        query = subprocess.run(
            ["sc", "query", SERVICE_NAME], capture_output=True, text=True
        )
        for line in query.stdout.splitlines():
            if "STATE" in line.upper():
                logf.write(line + "\n")
        running = "RUNNING" in query.stdout.upper()

        _log(logf, "安装结束")

    print()
    print(f"===== 安装日志（已保存到 {log_path}） =====")
    with open(log_path, encoding="utf-8") as f:
        print(f.read())
    print("=================================================")
    print()
    if running:
        print(f"结果: 安装成功，服务 RUNNING，程序位于 {INSTALL_DIR}")
        print("      这个安装程序已经可以删除。")
    else:
        print("结果: 未运行，请看上方日志")
    print()
    input("按回车键关闭...")
    return 0 if running else 1


if __name__ == "__main__":
    sys.exit(main())
