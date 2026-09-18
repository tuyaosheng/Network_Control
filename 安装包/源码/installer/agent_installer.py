"""
被控端一键安装器 - 双击自动提权（UAC），装服务并写日志。

逻辑上和 install_agent.bat 完全一致，区别是用 PyInstaller 的管理员清单
（uac_admin=True）代替 bat 里 "net session 判断 + 重新用 RunAs 拉起自己"
的老办法，双击就弹一次系统自带的 UAC 确认框，不需要手动右键选择
"以管理员身份运行"。

要求：和 CTR.exe、config.json 放在同一个文件夹下运行。
"""
import ctypes
import datetime
import os
import subprocess
import sys

SERVICE_NAME = "NetControlAgent"


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _run(args, logf) -> None:
    logf.write(f"$ {' '.join(args)}\n")
    logf.flush()
    subprocess.run(args, stdout=logf, stderr=logf)


def _log(logf, msg: str) -> None:
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    logf.write(line + "\n")


def main() -> int:
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("网络控制器学生端")
    except Exception:
        pass

    base_dir = _base_dir()
    ctr_exe = os.path.join(base_dir, "CTR.exe")
    log_path = os.path.join(base_dir, "install_agent.log")

    with open(log_path, "a", encoding="utf-8") as logf:
        _log(logf, f"安装开始 目录={base_dir}")

        if not os.path.exists(ctr_exe):
            _log(logf, "[错误] 当前文件夹里没有 CTR.exe")
            print()
            print("[错误] 当前文件夹里没有 CTR.exe")
            print("请把 CTR.exe、config.json 和这个安装程序放在同一个文件夹，")
            print("并先把压缩包整体解压再运行。")
            input("\n按回车键关闭...")
            return 1

        print("正在安装 CTR 服务，请稍候...")

        # 升级场景：旧版可能正处于断网/白名单状态，停止时要等它把默认路由加回来再 remove。
        # 先解除旧版的失败自动重启策略，否则旧服务可能在 remove 后被 SCM 拉起来。
        _run(["sc", "failure", SERVICE_NAME, "reset=", "0", "actions=", ""], logf)
        _run([ctr_exe, "--wait", "40", "stop"], logf)
        _run([ctr_exe, "remove"], logf)
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
    print(f"===== 安装日志（已保存到 {os.path.basename(log_path)}） =====")
    with open(log_path, encoding="utf-8") as f:
        print(f.read())
    print("=================================================")
    print()
    print("结果: 安装成功 服务 RUNNING" if running else "结果: 未运行，请看上方日志")
    print()
    input("按回车键关闭...")
    return 0 if running else 1


if __name__ == "__main__":
    sys.exit(main())
