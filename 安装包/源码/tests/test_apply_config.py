import json
import sqlite3

import pytest

from installer.apply_config import (
    build_agent_config,
    compute_subnet,
    main,
    parse_args,
    sha256_hex,
    write_agent_config,
    write_controller_db,
)

ADMIN123_HASH = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"


def test_sha256_hex_matches_known_default_password():
    assert sha256_hex("admin123") == ADMIN123_HASH


@pytest.mark.parametrize(
    "ip, netmask, expected",
    [
        ("192.168.1.100", "255.255.255.0", "192.168.1.0/24"),
        ("10.0.5.37", "255.255.0.0", "10.0.0.0/16"),
        ("172.16.0.1", "255.255.255.255", "172.16.0.1/32"),
    ],
)
def test_compute_subnet(ip, netmask, expected):
    assert compute_subnet(ip, netmask) == expected


def test_compute_subnet_rejects_invalid_ip():
    with pytest.raises(ValueError):
        compute_subnet("not-an-ip", "255.255.255.0")


def test_parse_args_requires_all_mandatory_fields():
    args = parse_args([
        "--controller-dir", "C:\\ctrl",
        "--agent-dir", "C:\\agent",
        "--ip", "192.168.1.100",
        "--password", "admin123",
    ])
    assert args.controller_dir == "C:\\ctrl"
    assert args.netmask == "255.255.255.0"


def test_parse_args_missing_required_raises(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--controller-dir", "C:\\ctrl"])


def test_build_agent_config_shape():
    cfg = build_agent_config("192.168.1.100", "192.168.1.0/24", "deadbeef")
    assert cfg["controller_url"] == "ws://192.168.1.100:8765"
    assert cfg["tray_password_hash"] == "deadbeef"
    assert cfg["unlock_password_hash"] == "deadbeef"
    assert cfg["lan_subnets"] == ["192.168.1.0/24"]
    assert cfg["tray_visible"] is True


def test_write_agent_config_writes_valid_json(tmp_path):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    write_agent_config(str(agent_dir), "192.168.1.100", "192.168.1.0/24", "deadbeef")

    with open(agent_dir / "config.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["controller_url"] == "ws://192.168.1.100:8765"
    assert data["unlock_password_hash"] == "deadbeef"


def test_write_controller_db_sets_expected_settings(tmp_path):
    controller_dir = tmp_path / "controller"
    controller_dir.mkdir()
    write_controller_db(str(controller_dir), "192.168.1.0/24", "deadbeef")

    conn = sqlite3.connect(controller_dir / "controller.db")
    rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    conn.close()

    assert rows["lan_subnets"] == "192.168.1.0/24"
    assert rows["tray_password_hash"] == "deadbeef"
    assert rows["unlock_password"] == "deadbeef"
    # 未被向导覆盖的字段仍保留 Database 初始化时写入的默认值
    assert rows["controller_port"] == "8765"


def test_main_end_to_end(tmp_path):
    controller_dir = tmp_path / "主控端"
    agent_dir = tmp_path / "被控端"
    exit_code = main([
        "--controller-dir", str(controller_dir),
        "--agent-dir", str(agent_dir),
        "--ip", "192.168.1.100",
        "--password", "admin123",
    ])
    assert exit_code == 0

    conn = sqlite3.connect(controller_dir / "controller.db")
    rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    conn.close()
    assert rows["tray_password_hash"] == ADMIN123_HASH

    with open(agent_dir / "config.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data["lan_subnets"] == ["192.168.1.0/24"]


def test_main_rejects_invalid_ip(tmp_path, capsys):
    exit_code = main([
        "--controller-dir", str(tmp_path / "c"),
        "--agent-dir", str(tmp_path / "a"),
        "--ip", "not-an-ip",
        "--password", "admin123",
    ])
    assert exit_code == 1
    assert "无效 IP" in capsys.readouterr().err


def test_main_rejects_empty_password(tmp_path, capsys):
    exit_code = main([
        "--controller-dir", str(tmp_path / "c"),
        "--agent-dir", str(tmp_path / "a"),
        "--ip", "192.168.1.100",
        "--password", "",
    ])
    assert exit_code == 1
    assert "密码不能为空" in capsys.readouterr().err
