"""
SQLite 数据库 - 白名单/黑名单规则、机器记录、设置
"""
import sqlite3
import os
import sys
import threading
from datetime import datetime

from shared.paths import get_app_dir

DB_PATH = os.path.join(get_app_dir(), "controller.db")


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._conn()
            # 删除旧的分组表结构（如果存在）
            conn.execute("DROP TABLE IF EXISTS domains")
            conn.execute("DROP TABLE IF EXISTS domain_groups")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    name    TEXT NOT NULL,
                    domain  TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS blacklist (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    name    TEXT NOT NULL,
                    domain  TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS machines (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip        TEXT NOT NULL UNIQUE,
                    hostname  TEXT DEFAULT '',
                    mac       TEXT DEFAULT '',
                    last_seen TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS machine_states (
                    ip         TEXT PRIMARY KEY,
                    net_state  TEXT NOT NULL DEFAULT 'normal',
                    updated_at TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );

                INSERT OR IGNORE INTO settings VALUES ('controller_port',    '8765');
                INSERT OR IGNORE INTO settings VALUES ('upstream_dns',       '114.114.114.114');
                INSERT OR IGNORE INTO settings VALUES ('lan_subnets',        '192.168.1.0/24');
                INSERT OR IGNORE INTO settings VALUES ('tray_password_hash', '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9');
                INSERT OR IGNORE INTO settings VALUES ('unlock_password',    '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9');
            """)
            conn.commit()
            conn.close()

    # ── 白名单 ───────────────────────────────────────────────────

    def list_whitelist(self) -> list[dict]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT id, name, domain, enabled FROM whitelist ORDER BY name"
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def add_whitelist(self, name: str, domain: str) -> bool:
        domain = domain.strip().lower()
        if not domain:
            return False
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO whitelist (name, domain, enabled) VALUES (?,?,1)",
                    (name.strip(), domain)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def set_whitelist_enabled(self, entry_id: int, enabled: bool):
        with self._lock:
            conn = self._conn()
            conn.execute(
                "UPDATE whitelist SET enabled=? WHERE id=?",
                (1 if enabled else 0, entry_id)
            )
            conn.commit()
            conn.close()

    def update_whitelist(self, entry_id: int, name: str, domain: str) -> bool:
        """更新白名单条目的名称和域名，域名冲突时返回 False。"""
        domain = domain.strip().lower()
        if not domain:
            return False
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "UPDATE whitelist SET name=?, domain=? WHERE id=?",
                    (name.strip(), domain, entry_id)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def delete_whitelist(self, entry_id: int):
        with self._lock:
            conn = self._conn()
            conn.execute("DELETE FROM whitelist WHERE id=?", (entry_id,))
            conn.commit()
            conn.close()

    def get_enabled_whitelist(self) -> list[str]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT domain FROM whitelist WHERE enabled=1 ORDER BY domain"
            ).fetchall()
            conn.close()
        return [r["domain"] for r in rows]

    # ── 黑名单 ───────────────────────────────────────────────────

    def list_blacklist(self) -> list[dict]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT id, name, domain, enabled FROM blacklist ORDER BY name"
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def add_blacklist(self, name: str, domain: str) -> bool:
        domain = domain.strip().lower()
        if not domain:
            return False
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO blacklist (name, domain, enabled) VALUES (?,?,1)",
                    (name.strip(), domain)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def set_blacklist_enabled(self, entry_id: int, enabled: bool):
        with self._lock:
            conn = self._conn()
            conn.execute(
                "UPDATE blacklist SET enabled=? WHERE id=?",
                (1 if enabled else 0, entry_id)
            )
            conn.commit()
            conn.close()

    def update_blacklist(self, entry_id: int, name: str, domain: str) -> bool:
        """更新黑名单条目的名称和域名，域名冲突时返回 False。"""
        domain = domain.strip().lower()
        if not domain:
            return False
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "UPDATE blacklist SET name=?, domain=? WHERE id=?",
                    (name.strip(), domain, entry_id)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def delete_blacklist(self, entry_id: int):
        with self._lock:
            conn = self._conn()
            conn.execute("DELETE FROM blacklist WHERE id=?", (entry_id,))
            conn.commit()
            conn.close()

    def get_enabled_blacklist(self) -> list[str]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT domain FROM blacklist WHERE enabled=1 ORDER BY domain"
            ).fetchall()
            conn.close()
        return [r["domain"] for r in rows]

    # ── 机器状态持久化 ───────────────────────────────────────────

    def save_machine_state(self, ip: str, net_state: str):
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT OR REPLACE INTO machine_states (ip, net_state, updated_at) VALUES (?,?,?)",
                (ip, net_state, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            conn.close()

    def get_all_machine_states(self) -> dict:
        """返回 {ip: net_state} 字典，用于主控端重启后恢复各机器的上次状态。"""
        with self._lock:
            conn = self._conn()
            rows = conn.execute("SELECT ip, net_state FROM machine_states").fetchall()
            conn.close()
        return {r["ip"]: r["net_state"] for r in rows}

    # ── 机器记录 ─────────────────────────────────────────────────

    def upsert_machine(self, ip: str, hostname: str, mac: str):
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO machines (ip, hostname, mac, last_seen) VALUES (?,?,?,?) "
                "ON CONFLICT(ip) DO UPDATE SET hostname=excluded.hostname, "
                "mac=excluded.mac, last_seen=excluded.last_seen",
                (ip, hostname, mac, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            conn.close()

    # ── 设置 ─────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            conn = self._conn()
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            conn.close()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                (key, value)
            )
            conn.commit()
            conn.close()
