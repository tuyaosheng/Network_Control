"""
被控端主入口 - 可直接运行（调试）或通过 Windows 服务运行
"""
import asyncio
import collections
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shared.paths import get_app_dir
from shared.protocol import MODE_WHITELIST, MODE_BLACKLIST, NET_NORMAL, NET_WHITELIST, NET_BLACKLIST, NET_DISCONNECT

from agent.filter.dns_server import LocalDNSServer
from agent.filter.firewall import (
    apply_whitelist_routing, remove_all_rules,
    set_adapter_dns,
    disconnect_internet, reconnect_internet,
    add_host_routes_dynamic,
)
from agent.client.ws_client import AgentWSClient
from agent.tray.tray_icon import AgentTray

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(get_app_dir(), "agent.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger("agent")

CONFIG_FILE = os.path.join(get_app_dir(), "config.json")

DEFAULT_CONFIG = {
    "controller_url":      "ws://192.168.1.100:8765",
    "upstream_dns":        "114.114.114.114",
    "tray_visible":        True,
    "tray_password_hash":  hashlib.sha256(b"admin123").hexdigest(),
    "unlock_password_hash": hashlib.sha256(b"admin123").hexdigest(),
    "lan_subnets":         ["192.168.1.0/24"]
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class AgentCore:
    STATE_NORMAL     = NET_NORMAL
    STATE_WHITELIST  = NET_WHITELIST
    STATE_BLACKLIST  = NET_BLACKLIST
    STATE_DISCONNECT = NET_DISCONNECT

    def __init__(self):
        self.config = load_config()
        self.dns_server: LocalDNSServer | None = None
        self.ws_client: AgentWSClient | None = None
        self.tray: AgentTray | None = None
        self._net_state: str = self.STATE_NORMAL
        self.filter_active = False
        self._filter_mode: str = MODE_WHITELIST
        self._whitelist_domains: list[str] = []
        self._blacklist_domains: list[str] = []
        self._lan_subnets: list[str] = self.config.get("lan_subnets", [])
        self._controller_ip: str = ""
        self._upstream_dns: str = self.config.get("upstream_dns", "114.114.114.114")
        # 浏览记录（DNS 查询日志）
        self._recent_domains: collections.deque = collections.deque(maxlen=50)
        self._domains_lock = threading.Lock()
        # 网络监控
        self._lock_screen_pid: int | None = None
        self._network_was_up: bool = True

    # ── 规则更新 ──────────────────────────────────────────────────

    def _on_update_rules(self, domains, lan_subnets, controller_ip, upstream_dns, mode,
                         tray_pwd_hash="", unlock_pwd_hash=""):
        logger.info(f"收到规则更新: {len(domains)} 条 [{mode}]")
        self._filter_mode = mode
        if mode == MODE_WHITELIST:
            self._whitelist_domains = domains
        else:
            self._blacklist_domains = domains

        self._lan_subnets = lan_subnets or self._lan_subnets
        self._controller_ip = controller_ip
        self._upstream_dns = upstream_dns or self._upstream_dns

        # 远程更新密码（主控端下发了新 hash 才更新，空字符串表示不改）
        cfg_changed = False
        if tray_pwd_hash:
            self.config["tray_password_hash"] = tray_pwd_hash
            if self.tray:
                self.tray.password_hash = tray_pwd_hash
            cfg_changed = True
        if unlock_pwd_hash:
            self.config["unlock_password_hash"] = unlock_pwd_hash
            cfg_changed = True
        if cfg_changed:
            save_config(self.config)
            logger.info("密码已从主控端更新并写入 config.json")

        # 当前正在过滤中：热更新规则
        if self.dns_server and self.dns_server.running:
            if self._net_state == self.STATE_WHITELIST and mode == MODE_WHITELIST:
                self.dns_server.update_domains(domains)
                # 白名单是动态加路由，规则变化不用重跑 routing，DNS 服务器会按新规则匹配
            elif self._net_state == self.STATE_BLACKLIST and mode == MODE_BLACKLIST:
                self.dns_server.update_domains(domains)

    def _on_set_filter(self, enabled: bool, mode: str):
        logger.info(f"过滤器: {'启用' if enabled else '禁用'} 模式={mode}")
        if enabled:
            state = self.STATE_WHITELIST if mode == MODE_WHITELIST else self.STATE_BLACKLIST
        else:
            state = self.STATE_NORMAL
        self._set_state(state)

    def _on_disconnect(self):
        self._set_state(self.STATE_DISCONNECT)

    def _on_reconnect(self):
        self._set_state(self.STATE_NORMAL)

    # ── 状态机 ────────────────────────────────────────────────────

    def _set_state(self, new_state: str):
        old = self._net_state
        self._net_state = new_state
        self.filter_active = new_state in (self.STATE_WHITELIST, self.STATE_BLACKLIST)

        if self.tray:
            self.tray.set_net_state(new_state)

        dispatch = {
            self.STATE_NORMAL:     self._do_restore,
            self.STATE_WHITELIST:  self._do_enable_whitelist,
            self.STATE_BLACKLIST:  self._do_enable_blacklist,
            self.STATE_DISCONNECT: self._do_disconnect,
        }
        dispatch.get(new_state, self._do_restore)()
        logger.info(f"状态: {old} → {new_state}")

    def _do_enable_whitelist(self):
        self._stop_dns()
        self.dns_server = LocalDNSServer(
            domains=self._whitelist_domains,
            upstream_dns=self._upstream_dns,
            mode=MODE_WHITELIST,
            on_query=self._on_query_domain,
            # DNS 服务器每次解析白名单域名后，把上游返回的 IP 实时加进路由表
            # 这样 CDN 每次返回的不同 IP 都能被放行，浏览器拿到的 IP 一定可达
            on_resolved_ips=add_host_routes_dynamic,
        )
        self.dns_server.start()
        set_adapter_dns("127.0.0.1")
        apply_whitelist_routing(
            self._whitelist_domains, self._lan_subnets,
            self._controller_ip, self._upstream_dns
        )

    def _do_enable_blacklist(self):
        self._stop_dns()
        reconnect_internet()   # 恢复可能被白名单/断网模式删除的默认路由
        remove_all_rules()     # 黑名单只用 DNS 拦截，清理任何残留防火墙规则
        self.dns_server = LocalDNSServer(
            domains=self._blacklist_domains,
            upstream_dns=self._upstream_dns,
            mode=MODE_BLACKLIST,
            on_query=self._on_query_domain
        )
        self.dns_server.start()
        set_adapter_dns("127.0.0.1")

    def _do_disconnect(self):
        self._stop_dns()
        set_adapter_dns(self._upstream_dns)
        remove_all_rules()       # 清掉白名单模式可能留下的防火墙规则
        disconnect_internet()    # 删除默认网关路由，彻底断网、局域网保留

    def _do_restore(self):
        self._stop_dns()
        set_adapter_dns(self._upstream_dns)
        remove_all_rules()
        reconnect_internet()     # 恢复默认网关路由

    def _stop_dns(self):
        if self.dns_server and self.dns_server.running:
            self.dns_server.stop()
        self.dns_server = None

    # ── 浏览监控 ─────────────────────────────────────────────────

    def _on_query_domain(self, domain: str):
        with self._domains_lock:
            self._recent_domains.append({
                "domain": domain,
                "ts": datetime.now().strftime("%H:%M:%S")
            })

    def _get_recent_domains(self) -> list:
        with self._domains_lock:
            return list(self._recent_domains)

    # ── 状态上报 ─────────────────────────────────────────────────

    def _get_status(self) -> dict:
        return {
            "filter_active": self.filter_active,
            "net_state":     self._net_state,
            "dns_running":   self.dns_server.running if self.dns_server else False,
            "rule_count":    len(self._whitelist_domains) + len(self._blacklist_domains),
        }

    # ── 网络监控（拔网线检测）────────────────────────────────────

    async def _monitor_network(self):
        await asyncio.sleep(5)  # 启动后等待一会儿再开始监控
        while True:
            await asyncio.sleep(3)
            try:
                up = await asyncio.get_event_loop().run_in_executor(
                    None, self._check_network_up
                )
                if not up and self._network_was_up:
                    self._network_was_up = False
                    logger.warning("检测到网线断开，启动锁屏")
                    self._lock_screen_pid = self._launch_lock_screen()
                elif up and not self._network_was_up:
                    self._network_was_up = True
                    logger.info("网络已恢复，关闭锁屏")
                    self._close_lock_screen()

                # 网线仍断开但锁屏进程已退出：重启锁屏
                if not self._network_was_up and self._lock_screen_pid:
                    if not self._is_process_alive(self._lock_screen_pid):
                        logger.info("锁屏进程退出，重新启动")
                        self._lock_screen_pid = self._launch_lock_screen()
            except Exception as e:
                logger.debug(f"网络监控异常: {e}")

    def _check_network_up(self) -> bool:
        try:
            result = subprocess.run(
                ['powershell', '-Command',
                 '(Get-NetAdapter | Where-Object {$_.Status -eq "Up" -and $_.Name -notmatch "Loopback"}).Count'],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            s = result.stdout.strip()
            return int(s) > 0 if s.isdigit() else True
        except Exception:
            return True

    def _close_lock_screen(self):
        """网络恢复时由 agent 主动关闭锁屏进程（比锁屏自检测更可靠，跨会话强杀）。"""
        pid = self._lock_screen_pid
        self._lock_screen_pid = None
        if not pid:
            return
        try:
            import win32api, win32con, win32process
            h = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
            win32process.TerminateProcess(h, 0)
            win32api.CloseHandle(h)
            logger.info(f"已关闭锁屏进程 PID={pid}")
        except Exception as e:
            logger.warning(f"OpenProcess/Terminate 关闭锁屏失败({e})，改用 taskkill")
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception as e2:
                logger.warning(f"taskkill 关闭锁屏也失败 PID={pid}: {e2}")

    def _launch_lock_screen(self) -> int | None:
        unlock_hash = self.config.get("unlock_password_hash",
                                       hashlib.sha256(b"admin123").hexdigest())
        exe = sys.executable

        # 服务模式（SYSTEM 权限）：通过 WTS API 跨 Session 在用户桌面启动锁屏
        try:
            import win32ts
            import win32process
            import win32security
            import win32con
            import win32api

            session_id = win32ts.WTSGetActiveConsoleSessionId()
            if session_id == 0xFFFFFFFF:
                raise RuntimeError("无活动用户会话")

            user_token = win32ts.WTSQueryUserToken(session_id)
            # pywin32 签名: DuplicateTokenEx(ExistingToken, ImpersonationLevel,
            #   DesiredAccess, TokenType, TokenAttributes=None)
            primary_token = win32security.DuplicateTokenEx(
                user_token,
                win32security.SecurityImpersonation,  # ImpersonationLevel
                win32con.TOKEN_ALL_ACCESS,            # DesiredAccess
                win32security.TokenPrimary,           # TokenType
            )
            si = win32process.STARTUPINFO()
            si.lpDesktop = "winsta0\\default"
            cmd = f'"{exe}" --lock "{unlock_hash}"'

            # 必须传【用户】环境块：否则子进程继承 SYSTEM 环境，PyInstaller 单文件解压到
            # SYSTEM 的 %TEMP%（用户令牌无权写）、Qt 取不到用户环境，锁屏进程会一启动就秒退。
            import win32profile
            try:
                env = win32profile.CreateEnvironmentBlock(user_token, False)
            except Exception:
                env = None
            workdir = os.path.dirname(exe) or None
            CREATE_UNICODE_ENVIRONMENT = 0x00000400
            info = win32process.CreateProcessAsUser(
                primary_token, None, cmd, None, None, False,
                win32con.NORMAL_PRIORITY_CLASS | CREATE_UNICODE_ENVIRONMENT,
                env, workdir, si
            )
            pid = info[2]
            win32api.CloseHandle(info[0])
            win32api.CloseHandle(info[1])
            logger.info(f"锁屏进程已启动 PID={pid}")
            return pid
        except Exception as e:
            # debug 模式或非 SYSTEM 权限（1314）：已在用户 Session 中，直接 Popen
            logger.warning(f"WTS 方式启动锁屏失败({e})，降级为当前会话直接启动")

        try:
            proc = subprocess.Popen(
                [exe, "--lock", unlock_hash],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            logger.info(f"锁屏进程已启动(降级模式) PID={proc.pid}")
            return proc.pid
        except Exception as e2:
            logger.error(f"启动锁屏失败: {e2}")
            return None

    def _is_process_alive(self, pid: int) -> bool:
        try:
            import win32api
            import win32process
            import win32con
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
            code = win32process.GetExitCodeProcess(handle)
            win32api.CloseHandle(handle)
            return code == 259  # STILL_ACTIVE
        except Exception:
            return False

    # ── 托盘退出 ─────────────────────────────────────────────────

    def _on_exit_confirmed(self):
        logger.info("用户通过托盘密码验证，退出程序")
        self._do_restore()
        os._exit(0)

    # ── 主循环 ───────────────────────────────────────────────────

    async def run(self):
        logger.info("被控端启动")

        self.tray = AgentTray(
            password_hash=self.config.get("tray_password_hash",
                                          DEFAULT_CONFIG["tray_password_hash"]),
            visible=self.config.get("tray_visible", True),
            on_exit_confirmed=self._on_exit_confirmed
        )
        self.tray.start()

        self.ws_client = AgentWSClient(
            controller_url=self.config["controller_url"],
            on_update_rules=self._on_update_rules,
            on_set_filter=self._on_set_filter,
            on_disconnect=self._on_disconnect,
            on_reconnect=self._on_reconnect,
            get_status_fn=self._get_status,
            get_browsing_fn=self._get_recent_domains
        )

        try:
            await asyncio.gather(
                self.ws_client.run(),
                self._monitor_network()
            )
        finally:
            self._do_restore()
            self.tray.stop()

    def stop(self):
        if self.ws_client:
            self.ws_client.stop()
        self._do_restore()


if __name__ == "__main__":
    core = AgentCore()
    asyncio.run(core.run())
