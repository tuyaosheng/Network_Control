"""
安装时配置生成器 - 由 Inno Setup 安装向导在文件复制完成后静默调用一次。

用法：
    apply_config.exe --controller-dir <主控端安装目录> --agent-dir <被控端安装目录>
                      --ip <教师机IP> [--netmask <点分掩码，默认 255.255.255.0>]
                      --password <退出/解锁密码明文>
                      [--agent-template <学生端安装器模板 exe>]

把向导收集到的信息写成：
  - <controller-dir>\\controller.db 里的 lan_subnets / tray_password_hash / unlock_password
  - 被控端配置（controller_url / lan_subnets / 两个密码哈希）：
      给了 --agent-template → 配置追加进 <agent-dir>\\网络控制器学生端.exe 末尾（单文件部署）
      没给              → 写成 <agent-dir>\\config.json（旧的手动部署方式）
"""
import argparse
import hashlib
import ipaddress
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controller.db.database import Database
from installer.payload import write_with_config

CONTROLLER_PORT = "8765"
UPSTREAM_DNS = "114.114.114.114"
AGENT_INSTALLER_NAME = "网络控制器学生端.exe"


def sha256_hex(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def compute_subnet(ip: str, netmask: str) -> str:
    """IP + 点分掩码 -> 网络地址 CIDR，如 192.168.1.100 + 255.255.255.0 -> 192.168.1.0/24。"""
    iface = ipaddress.ip_interface(f"{ip}/{netmask}")
    return str(iface.network)


def write_controller_db(controller_dir: str, subnet: str, password_hash: str) -> None:
    db_path = os.path.join(controller_dir, "controller.db")
    db = Database(path=db_path)
    db.set_setting("lan_subnets", subnet)
    db.set_setting("tray_password_hash", password_hash)
    db.set_setting("unlock_password", password_hash)


def build_agent_config(ip: str, subnet: str, password_hash: str) -> dict:
    return {
        "controller_url": f"ws://{ip}:{CONTROLLER_PORT}",
        "upstream_dns": UPSTREAM_DNS,
        "tray_visible": True,
        "tray_password_hash": password_hash,
        "unlock_password_hash": password_hash,
        "lan_subnets": [subnet],
    }


def write_agent_config(agent_dir: str, ip: str, subnet: str, password_hash: str) -> None:
    config = build_agent_config(ip, subnet, password_hash)
    config_path = os.path.join(agent_dir, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def write_agent_installer(template: str, agent_dir: str, ip: str, subnet: str,
                          password_hash: str) -> str:
    """生成带内嵌配置的学生端安装器，返回输出路径。"""
    config = build_agent_config(ip, subnet, password_hash)
    out_path = os.path.join(agent_dir, AGENT_INSTALLER_NAME)
    write_with_config(template, out_path, config)
    return out_path


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安装时生成主控端/被控端配置")
    parser.add_argument("--controller-dir", required=True)
    parser.add_argument("--agent-dir", required=True)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--netmask", default="255.255.255.0")
    parser.add_argument("--password", required=True)
    parser.add_argument("--agent-template", default="",
                        help="学生端安装器模板 exe；给出时生成单文件学生端安装器，不再写 config.json")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        ipaddress.ip_address(args.ip)
    except ValueError:
        print(f"[apply_config] 无效 IP 地址: {args.ip}", file=sys.stderr)
        return 1

    if not args.password:
        print("[apply_config] 密码不能为空", file=sys.stderr)
        return 1

    try:
        subnet = compute_subnet(args.ip, args.netmask)
    except ValueError as e:
        print(f"[apply_config] 网段计算失败: {e}", file=sys.stderr)
        return 1

    password_hash = sha256_hex(args.password)

    try:
        os.makedirs(args.controller_dir, exist_ok=True)
        os.makedirs(args.agent_dir, exist_ok=True)
        write_controller_db(args.controller_dir, subnet, password_hash)
        if args.agent_template:
            write_agent_installer(args.agent_template, args.agent_dir,
                                  args.ip, subnet, password_hash)
        else:
            write_agent_config(args.agent_dir, args.ip, subnet, password_hash)
    except OSError as e:
        print(f"[apply_config] 写入配置失败: {e}", file=sys.stderr)
        return 1

    print(f"[apply_config] 配置完成：网段 {subnet}，主控端 -> {args.controller_dir}，被控端 -> {args.agent_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
