"""
主控端主窗口
左侧：在线被控端列表
右侧：标签页（规则管理 / 设置）
底部：日志输出
"""
import asyncio
import hashlib
import logging
import os
import sys
import threading

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QTabWidget, QTextEdit, QStatusBar, QLabel, QGroupBox,
    QLineEdit, QPushButton, QFormLayout, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QTextCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from controller.db.database import Database
from controller.server.ws_server import ControllerServer, scan_ip_range
from controller.server.api_server import ControlAPIServer
from controller.gui.machine_panel import MachinePanel
from controller.gui.rule_panel import RulePanel
from shared.protocol import MODE_WHITELIST, MODE_BLACKLIST

logger = logging.getLogger("main_window")


class QtLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def emit(self, record):
        self._cb(self.format(record))


class Signals(QObject):
    agents_changed = pyqtSignal()
    log_msg        = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    # 外部 HTTP 接口 → Qt 主线程（跨线程用排队连接，线程安全）
    api_enable     = pyqtSignal()
    api_disable    = pyqtSignal()
    api_enable_ip  = pyqtSignal(str)   # 按 IP 开单台（学习平台调用）
    api_disable_ip = pyqtSignal(str)   # 按 IP 禁单台（学习平台同步状态调用）


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db     = Database()
        self.server = ControllerServer(
            on_agent_change=self._on_agent_change,
            on_agent_reconnect=self._on_reconnect_restore,
            initial_states=self.db.get_all_machine_states(),
        )
        self._signals = Signals()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server_thread: threading.Thread | None = None
        self._api_server: ControlAPIServer | None = None

        self._build_ui()
        self._setup_logging()
        self._start_server()
        self._start_api_server()

        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_machines)
        self._refresh_timer.start(2000)

        # 防抖：多台机器同时发心跳时，合并为一次 UI 刷新，避免事件队列堆积导致卡顿
        self._refresh_debounce = QTimer()
        self._refresh_debounce.setSingleShot(True)
        self._refresh_debounce.setInterval(150)
        self._refresh_debounce.timeout.connect(self._refresh_machines)
        self._signals.agents_changed.connect(self._refresh_debounce.start)
        self._signals.log_msg.connect(self._append_log)
        self._signals.status_changed.connect(self._status_label.setText)
        self._signals.api_enable.connect(self._on_api_enable)
        self._signals.api_disable.connect(self._on_api_disable)
        self._signals.api_enable_ip.connect(self._on_api_enable_ip)
        self._signals.api_disable_ip.connect(self._on_api_disable_ip)

    # ── UI 构建 ───────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("局域网网络控制 - 主控端")
        self.resize(1240, 760)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        vsplit = QSplitter(Qt.Orientation.Vertical)

        top_split = QSplitter(Qt.Orientation.Horizontal)

        self._machine_panel = MachinePanel()
        self._machine_panel.sig_allow_all.connect(self._on_allow_all)
        self._machine_panel.sig_start_whitelist.connect(self._on_start_whitelist)
        self._machine_panel.sig_start_blacklist.connect(self._on_start_blacklist)
        self._machine_panel.sig_disconnect.connect(self._on_disconnect)
        self._machine_panel.sig_scan.connect(self._on_scan)
        top_split.addWidget(self._machine_panel)

        right_tabs = QTabWidget()
        self._rule_panel = RulePanel(self.db)
        right_tabs.addTab(self._rule_panel, "规则管理")
        right_tabs.addTab(self._build_settings_tab(), "设置")
        top_split.addWidget(right_tabs)
        top_split.setSizes([660, 520])
        vsplit.addWidget(top_split)

        log_box = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_box)
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 9))
        self._log_view.setMaximumHeight(160)
        log_layout.addWidget(self._log_view)
        vsplit.addWidget(log_box)
        vsplit.setSizes([560, 160])

        main_layout.addWidget(vsplit)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("服务器启动中...")
        self._status_bar.addWidget(self._status_label)

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setVerticalSpacing(10)

        self._input_port       = QLineEdit(self.db.get_setting("controller_port", "8765"))
        self._input_dns        = QLineEdit(self.db.get_setting("upstream_dns", "114.114.114.114"))
        self._input_lan        = QLineEdit(self.db.get_setting("lan_subnets", "192.168.1.0/24"))
        self._input_tray_pwd   = QLineEdit()
        self._input_unlock_pwd = QLineEdit()
        self._input_tray_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._input_unlock_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._input_tray_pwd.setPlaceholderText("留空则不修改")
        self._input_unlock_pwd.setPlaceholderText("留空则不修改")

        # 对外 HTTP 控制接口（供其他程序一键开网/禁网）
        self._input_api_host  = QLineEdit(self.db.get_setting("api_host", "127.0.0.1"))
        self._input_api_port  = QLineEdit(self.db.get_setting("api_port", "8770"))
        self._input_api_token = QLineEdit(self.db.get_setting("api_token", ""))
        self._input_api_host.setPlaceholderText("127.0.0.1（仅本机）/ 0.0.0.0（开放局域网）")
        self._input_api_token.setPlaceholderText("留空则不校验；开放局域网时务必设置")

        layout.addRow("主控端端口:", self._input_port)
        layout.addRow("上游 DNS:", self._input_dns)
        layout.addRow("局域网段（逗号分隔）:", self._input_lan)
        layout.addRow("被控端托盘退出密码:", self._input_tray_pwd)
        layout.addRow("被控端锁屏解锁密码:", self._input_unlock_pwd)
        layout.addRow("控制接口地址:", self._input_api_host)
        layout.addRow("控制接口端口:", self._input_api_port)
        layout.addRow("控制接口令牌:", self._input_api_token)

        tip = QLabel(
            "修改端口后需重启主控端生效\n"
            "局域网段用于放行内网通信，不会被过滤器拦截\n"
            "密码修改后保存即在下次下发规则时生效\n"
            "控制接口供其他程序一键开网/禁网，改动后需重启主控端生效；"
            "地址设为 0.0.0.0 开放局域网时务必设置令牌"
        )
        tip.setStyleSheet("color:gray;font-size:11px;")
        tip.setWordWrap(True)
        layout.addRow(tip)

        btn_save = QPushButton("保存设置")
        btn_save.setStyleSheet("background:#27ae60;color:white;padding:6px 20px;")
        btn_save.clicked.connect(self._save_settings)
        layout.addRow(btn_save)
        return w

    # ── 日志 ──────────────────────────────────────────────────────

    def _setup_logging(self):
        handler = QtLogHandler(self._signals.log_msg.emit)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%H:%M:%S")
        )
        logging.getLogger().addHandler(handler)

    def _append_log(self, msg: str):
        self._log_view.append(msg)
        self._log_view.moveCursor(QTextCursor.MoveOperation.End)

    # ── 服务器 ────────────────────────────────────────────────────

    def _start_server(self):
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._async_main())

        self._server_thread = threading.Thread(target=run_loop, daemon=True)
        self._server_thread.start()

    async def _async_main(self):
        port = int(self.db.get_setting("controller_port", "8765"))
        try:
            await self.server.start()
        except Exception as e:
            self._signals.log_msg.emit(f"服务器启动失败: {e}")
            self._signals.status_changed.emit(f"服务器启动失败: {e}")
            return
        self._signals.log_msg.emit(f"服务器已启动，监听端口 {port}")
        self._signals.status_changed.emit(f"服务器运行中 | 端口 {port}")
        await asyncio.Future()

    # ── 外部 HTTP 控制接口 ────────────────────────────────────────

    def _start_api_server(self):
        """启动对外 HTTP 接口，供其他程序一键开网 / 禁网。

        监听参数从设置读取（api_host / api_port / api_token），
        默认仅监听 127.0.0.1:8770，无令牌。启动失败不影响主程序。
        """
        host  = self.db.get_setting("api_host", "127.0.0.1")
        token = self.db.get_setting("api_token", "")
        try:
            port = int(self.db.get_setting("api_port", "8770"))
        except ValueError:
            port = 8770
        try:
            self._api_server = ControlAPIServer(
                host=host, port=port, token=token,
                # 回调在 API 线程中执行，只 emit 信号（排队到 Qt 主线程），线程安全
                on_enable=self._signals.api_enable.emit,
                on_disable=self._signals.api_disable.emit,
                on_enable_ip=self._signals.api_enable_ip.emit,
                on_disable_ip=self._signals.api_disable_ip.emit,
                get_status=self.server.get_agents,
            )
            self._api_server.start()
            self._signals.log_msg.emit(
                f"控制接口已启动: http://{host}:{port}  "
                f"（开网 /api/network/enable，禁网 /api/network/disable）"
            )
        except Exception as e:
            self._api_server = None
            self._signals.log_msg.emit(f"控制接口启动失败: {e}")

    def _on_api_enable(self):
        """外部接口触发的『一键开网』，等价于对全部被控端点击「允许上网」。"""
        self._append_log("[API] 收到『一键开网』请求")
        self._on_allow_all([])

    def _on_api_disable(self):
        """外部接口触发的『一键禁网』，等价于对全部被控端点击「禁止上网」。"""
        self._append_log("[API] 收到『一键禁网』请求")
        self._on_disconnect([])

    def _on_api_enable_ip(self, ip: str):
        """外部接口（学习平台）触发的『按 IP 开网』，等价于对该机器点击「允许上网」。"""
        self._append_log(f"[API] 收到『开网』请求: {ip}")
        self._on_allow_all([ip])

    def _on_api_disable_ip(self, ip: str):
        """外部接口（学习平台）触发的『按 IP 禁网』，等价于对该机器点击「禁止上网」。"""
        self._append_log(f"[API] 收到『禁网』请求: {ip}")
        self._on_disconnect([ip])

    def _on_agent_change(self):
        self._signals.agents_changed.emit()

    async def _on_reconnect_restore(self, ip: str, state: str):
        """被控端重连（还原卡重启）后自动恢复断开前的网络状态。"""
        logger.info(f"[重连恢复] {ip} 恢复断开前状态: {state}")
        lan_subnets, upstream = self._get_lan_upstream()
        tray_hash, unlock_hash = self._get_pwd_hashes()
        if state == "whitelist":
            domains = self.db.get_enabled_whitelist()
            if domains:
                await self.server.push_rules(
                    domains, lan_subnets, upstream,
                    mode=MODE_WHITELIST, target_ip=ip,
                    tray_pwd_hash=tray_hash, unlock_pwd_hash=unlock_hash,
                )
                await self.server.set_filter(True, MODE_WHITELIST, ip)
        elif state == "blacklist":
            domains = self.db.get_enabled_blacklist()
            if domains:
                await self.server.push_rules(
                    domains, lan_subnets, upstream,
                    mode=MODE_BLACKLIST, target_ip=ip,
                    tray_pwd_hash=tray_hash, unlock_pwd_hash=unlock_hash,
                )
                await self.server.set_filter(True, MODE_BLACKLIST, ip)
        elif state == "disconnect":
            await self.server.disconnect_internet(ip)
        else:
            # normal 或未知：明确放行（被控端开机默认断网，需主控端确认才上网）
            await self.server.reconnect_internet(ip)
        self._signals.log_msg.emit(f"[重连恢复] {ip} 已重新应用状态: {state}")

    def _refresh_machines(self):
        self._machine_panel.refresh(self.server.get_agents())

    # ── 异步调度 ──────────────────────────────────────────────────

    def _run_async(self, coro):
        if self._loop:
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _get_lan_upstream(self) -> tuple[list[str], str]:
        lan_raw     = self.db.get_setting("lan_subnets", "192.168.1.0/24")
        upstream    = self.db.get_setting("upstream_dns", "114.114.114.114")
        lan_subnets = [s.strip() for s in lan_raw.split(",") if s.strip()]
        return lan_subnets, upstream

    # ── 操作响应 ──────────────────────────────────────────────────

    def _get_pwd_hashes(self) -> tuple[str, str]:
        tray_hash   = self.db.get_setting("tray_password_hash", "")
        unlock_hash = self.db.get_setting("unlock_password", "")
        return tray_hash, unlock_hash

    def _on_start_whitelist(self, ips: list[str]):
        domains = self.db.get_enabled_whitelist()
        if not domains:
            QMessageBox.warning(self, "提示", "白名单为空，请先在「规则管理 → 白名单」中添加域名")
            return
        lan_subnets, upstream = self._get_lan_upstream()
        tray_hash, unlock_hash = self._get_pwd_hashes()
        targets = ips if ips else [None]

        async def _do():
            for ip in targets:
                await self.server.push_rules(
                    domains, lan_subnets, upstream,
                    mode=MODE_WHITELIST, target_ip=ip,
                    tray_pwd_hash=tray_hash,
                    unlock_pwd_hash=unlock_hash,
                )
                await self.server.set_filter(True, MODE_WHITELIST, ip)

        self._run_async(_do())
        # 保存状态，用于被控端重连后自动恢复
        for ip in (ips if ips else self.server.get_online_ips()):
            self.server.update_saved_state(ip, "whitelist")
            self.db.save_machine_state(ip, "whitelist")
        n = "全部" if not ips else f"{len(ips)} 台"
        self._append_log(
            f"[操作] 已向 {n} 被控端启动白名单过滤（{len(domains)} 条域名）"
        )

    def _on_start_blacklist(self, ips: list[str]):
        domains = self.db.get_enabled_blacklist()
        if not domains:
            QMessageBox.warning(self, "提示", "黑名单为空，请先在「规则管理 → 黑名单」中添加域名")
            return
        lan_subnets, upstream = self._get_lan_upstream()
        tray_hash, unlock_hash = self._get_pwd_hashes()
        targets = ips if ips else [None]

        async def _do():
            for ip in targets:
                await self.server.push_rules(
                    domains, lan_subnets, upstream,
                    mode=MODE_BLACKLIST, target_ip=ip,
                    tray_pwd_hash=tray_hash,
                    unlock_pwd_hash=unlock_hash,
                )
                await self.server.set_filter(True, MODE_BLACKLIST, ip)

        self._run_async(_do())
        # 保存状态，用于被控端重连后自动恢复
        for ip in (ips if ips else self.server.get_online_ips()):
            self.server.update_saved_state(ip, "blacklist")
            self.db.save_machine_state(ip, "blacklist")
        n = "全部" if not ips else f"{len(ips)} 台"
        self._append_log(
            f"[操作] 已向 {n} 被控端启动黑名单过滤（{len(domains)} 条域名）"
        )

    def _on_disconnect(self, ips: list[str]):
        targets = ips if ips else [None]

        async def _do():
            for ip in targets:
                await self.server.disconnect_internet(ip)

        self._run_async(_do())
        # 保存状态，用于被控端重连后自动恢复
        for ip in (ips if ips else self.server.get_online_ips()):
            self.server.update_saved_state(ip, "disconnect")
            self.db.save_machine_state(ip, "disconnect")
        n = "全部" if not ips else f"{len(ips)} 台"
        self._append_log(f"[操作] 已向 {n} 被控端发送「禁止上网」（局域网保留）")

    def _on_allow_all(self, ips: list[str]):
        """全部允许上网：先停止过滤、再恢复路由，覆盖任何当前状态。"""
        targets = ips if ips else [None]

        async def _do():
            for ip in targets:
                # set_filter(False) 让 agent 进入 NORMAL 状态（_do_restore 会清过滤）
                await self.server.set_filter(False, MODE_WHITELIST, ip)
                # 再发 reconnect 兜底，确保从 disconnect 状态切回时路由也恢复
                await self.server.reconnect_internet(ip)

        self._run_async(_do())
        # 保存状态，用于被控端重连后自动恢复
        for ip in (ips if ips else self.server.get_online_ips()):
            self.server.update_saved_state(ip, "normal")
            self.db.save_machine_state(ip, "normal")
        n = "全部" if not ips else f"{len(ips)} 台"
        self._append_log(f"[操作] 已向 {n} 被控端发送「全部允许上网」")

    def _on_scan(self, subnet: str):
        self._append_log(f"[扫描] 正在扫描 {subnet} ...")
        port = int(self.db.get_setting("controller_port", "8765"))

        async def _do():
            found = await scan_ip_range(subnet, port)
            msg = f"[扫描] 发现 {len(found)} 台在线被控端: {', '.join(found) or '无'}"
            self._signals.log_msg.emit(msg)

        self._run_async(_do())

    def _save_settings(self):
        self.db.set_setting("controller_port", self._input_port.text().strip())
        self.db.set_setting("upstream_dns",    self._input_dns.text().strip())
        self.db.set_setting("lan_subnets",     self._input_lan.text().strip())
        self.db.set_setting("api_host",        self._input_api_host.text().strip() or "127.0.0.1")
        self.db.set_setting("api_port",        self._input_api_port.text().strip() or "8770")
        self.db.set_setting("api_token",       self._input_api_token.text().strip())

        tray_pwd = self._input_tray_pwd.text().strip()
        if tray_pwd:
            self.db.set_setting(
                "tray_password_hash",
                hashlib.sha256(tray_pwd.encode()).hexdigest()
            )
            self._input_tray_pwd.clear()

        unlock_pwd = self._input_unlock_pwd.text().strip()
        if unlock_pwd:
            self.db.set_setting(
                "unlock_password",
                hashlib.sha256(unlock_pwd.encode()).hexdigest()
            )
            self._input_unlock_pwd.clear()

        QMessageBox.information(
            self, "保存成功",
            "设置已保存\n端口修改后需重启主控端生效"
        )

    def closeEvent(self, event):
        if self._api_server:
            self._api_server.stop()
        self._run_async(self.server.stop())
        event.accept()
