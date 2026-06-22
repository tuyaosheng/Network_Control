"""
被控端列表面板 - 4 个网络状态按钮 + 表头全选 checkbox
按钮逻辑：
  - 未勾选任何 / 全部勾选 → 应用到所有在线被控端
  - 勾选了部分 → 只应用到勾选的被控端
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView,
    QLineEdit, QFrame, QDialog, QListWidget, QMenu, QStyle, QStyleOptionButton,
    QApplication
)
import ipaddress as _ipmod

from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter

NET_STATE_DISPLAY = {
    "normal":     ("正常",      QColor(120, 120, 120)),
    "whitelist":  ("白名单过滤", QColor(0, 160, 0)),
    "blacklist":  ("黑名单过滤", QColor(0, 100, 200)),
    "disconnect": ("已断网",    QColor(200, 0, 0)),
    "offline":    ("已断开",    QColor(180, 180, 180)),   # 与主控端失去连接
}

_COLOR_OFFLINE_BG = QColor(245, 245, 245)   # 离线行背景色

_STATE_SORT_ORDER = {
    "normal": 0, "whitelist": 1, "blacklist": 2, "disconnect": 3, "offline": 4,
}

COL_CHECK  = 0
COL_IP     = 1
COL_HOST   = 2
COL_STATE  = 3
COL_CONN   = 4
COL_LAST   = 5
COL_BROWSE = 6
COLS = ["", "IP 地址", "主机名", "网络状态", "连接时间", "最后心跳", "最近访问"]


class _CheckBoxHeader(QHeaderView):
    """表头第一列绘制一个可点击的全选 checkbox。"""
    sig_toggle = pyqtSignal()   # 用户点击了 checkbox

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._check_state = Qt.CheckState.Unchecked
        self.setSectionsClickable(True)
        self.sectionClicked.connect(self._on_section_clicked)

    def set_check_state(self, state: Qt.CheckState):
        if self._check_state != state:
            self._check_state = state
            self.viewport().update()

    def _on_section_clicked(self, section: int):
        if section == COL_CHECK:
            self.sig_toggle.emit()

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int):
        super().paintSection(painter, rect, logicalIndex)
        if logicalIndex != COL_CHECK:
            return
        opt = QStyleOptionButton()
        size = 16
        opt.rect = QRect(
            rect.x() + (rect.width() - size) // 2,
            rect.y() + (rect.height() - size) // 2,
            size, size
        )
        if self._check_state == Qt.CheckState.Checked:
            opt.state = QStyle.StateFlag.State_On | QStyle.StateFlag.State_Enabled
        elif self._check_state == Qt.CheckState.PartiallyChecked:
            opt.state = QStyle.StateFlag.State_NoChange | QStyle.StateFlag.State_Enabled
        else:
            opt.state = QStyle.StateFlag.State_Off | QStyle.StateFlag.State_Enabled
        QApplication.style().drawControl(
            QStyle.ControlElement.CE_CheckBox, opt, painter
        )


class _BrowseDialog(QDialog):
    def __init__(self, ip: str, domains: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"浏览记录 — {ip}")
        self.setMinimumSize(420, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"最近访问记录（最多 30 条，最新在上）— {ip}"))
        lst = QListWidget()
        if domains:
            for d in reversed(domains):
                if isinstance(d, dict):
                    ts     = d.get("ts", "")
                    domain = d.get("domain", "")
                    lst.addItem(f"[{ts}]  {domain}")
                else:
                    lst.addItem(str(d))
        else:
            lst.addItem("暂无记录")
        layout.addWidget(lst)
        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)


class MachinePanel(QWidget):
    sig_allow_all       = pyqtSignal(list)   # 全部允许上网（恢复正常）
    sig_start_whitelist = pyqtSignal(list)   # 启动白名单过滤
    sig_start_blacklist = pyqtSignal(list)   # 启动黑名单过滤
    sig_disconnect      = pyqtSignal(list)   # 禁止上网（保留局域网）
    sig_scan            = pyqtSignal(str)    # 扫描 IP 段

    def __init__(self, parent=None):
        super().__init__(parent)
        self._agents: list[dict] = []
        self._checked_ips: set[str] = set()
        self._sort_col: int = COL_IP   # 默认按 IP 排序
        self._sort_asc: bool = True
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # ── 4 个状态按钮 ────────────────────────────────────────────
        action_bar = QFrame()
        action_bar.setStyleSheet("QFrame{background:#1a1a2e;border-radius:6px;}")
        ab = QHBoxLayout(action_bar)
        ab.setContentsMargins(10, 6, 10, 6)
        ab.setSpacing(10)

        btn_allow      = QPushButton("✅  全部允许上网")
        btn_whitelist  = QPushButton("▶  启动白名单")
        btn_blacklist  = QPushButton("▶  启动黑名单")
        btn_disconnect = QPushButton("⛔  禁止上网")
        for btn, col in [
            (btn_allow,      "#27ae60"),
            (btn_whitelist,  "#1e8449"),
            (btn_blacklist,  "#2471a3"),
            (btn_disconnect, "#c0392b"),
        ]:
            btn.setStyleSheet(
                f"background:{col};color:white;font-weight:bold;"
                "padding:8px 18px;border-radius:4px;font-size:13px;"
            )
            btn.setMinimumHeight(36)

        btn_allow.clicked.connect(
            lambda: self._emit_targeted(self.sig_allow_all))
        btn_whitelist.clicked.connect(
            lambda: self._emit_targeted(self.sig_start_whitelist))
        btn_blacklist.clicked.connect(
            lambda: self._emit_targeted(self.sig_start_blacklist))
        btn_disconnect.clicked.connect(
            lambda: self._emit_targeted(self.sig_disconnect))

        for w in (btn_allow, btn_whitelist, btn_blacklist, btn_disconnect):
            ab.addWidget(w)
        ab.addStretch()

        # ── 扫描行 ──────────────────────────────────────────────────
        self._label_count = QLabel("在线: 0 台")
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        self._label_count.setFont(f)

        scan_row = QHBoxLayout()
        self._scan_input = QLineEdit()
        self._scan_input.setPlaceholderText("IP段，如 192.168.1.0/24")
        self._scan_input.setFixedWidth(200)
        btn_scan = QPushButton("扫描局域网")
        btn_scan.clicked.connect(self._do_scan)
        scan_row.addWidget(QLabel("IP段:"))
        scan_row.addWidget(self._scan_input)
        scan_row.addWidget(btn_scan)
        scan_row.addSpacing(12)
        scan_row.addStretch()
        scan_row.addWidget(self._label_count)

        # ── 被控端表格 ────────────────────────────────────────────────
        self._table = QTableWidget(0, len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        # 自定义表头（COL_CHECK 列绘制全选 checkbox）
        self._header = _CheckBoxHeader(self._table)
        self._table.setHorizontalHeader(self._header)
        self._header.sig_toggle.connect(self._toggle_select_all)

        self._header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._header.setSectionResizeMode(COL_CHECK,  QHeaderView.ResizeMode.Fixed)
        self._header.setSectionResizeMode(COL_IP,     QHeaderView.ResizeMode.ResizeToContents)
        self._header.setSectionResizeMode(COL_CONN,   QHeaderView.ResizeMode.ResizeToContents)
        self._header.setSectionResizeMode(COL_LAST,   QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(COL_CHECK, 36)

        # 排序指示器（▲▼）
        self._header.setSortIndicatorShown(True)
        self._header.setSortIndicator(COL_IP, Qt.SortOrder.AscendingOrder)
        self._header.sectionClicked.connect(self._on_col_clicked)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.itemChanged.connect(self._on_checkbox_changed)

        layout.addWidget(action_bar)
        layout.addLayout(scan_row)
        layout.addWidget(self._table)

    # ── 勾选逻辑 ─────────────────────────────────────────────────────

    def _on_checkbox_changed(self, item: QTableWidgetItem):
        if item.column() != COL_CHECK:
            return
        ip_item = self._table.item(item.row(), COL_IP)
        if not ip_item:
            return
        ip = ip_item.text()
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_ips.add(ip)
        else:
            self._checked_ips.discard(ip)
        self._update_header_state()

    def _toggle_select_all(self):
        """表头 checkbox 点击：全已选→清空，否则→全选（仅针对在线机器）。"""
        online = self._online_ips()
        if online and self._checked_ips >= online:
            self._deselect_all()
        else:
            self._select_all()

    def _select_all(self):
        self._table.blockSignals(True)
        for row in range(self._table.rowCount()):
            chk = self._table.item(row, COL_CHECK)
            ip_item = self._table.item(row, COL_IP)
            if chk and ip_item and not (chk.flags() & Qt.ItemFlag.ItemIsEnabled == Qt.ItemFlag(0)):
                # 只勾选可用（在线）的行
                if chk.flags() & Qt.ItemFlag.ItemIsEnabled:
                    chk.setCheckState(Qt.CheckState.Checked)
                    self._checked_ips.add(ip_item.text())
        self._table.blockSignals(False)
        self._update_header_state()

    def _deselect_all(self):
        self._table.blockSignals(True)
        for row in range(self._table.rowCount()):
            chk = self._table.item(row, COL_CHECK)
            if chk:
                chk.setCheckState(Qt.CheckState.Unchecked)
        self._checked_ips.clear()
        self._table.blockSignals(False)
        self._update_header_state()

    def _update_header_state(self):
        online = self._online_ips()
        checked_online = self._checked_ips & online
        if not online or not checked_online:
            self._header.set_check_state(Qt.CheckState.Unchecked)
        elif checked_online >= online:
            self._header.set_check_state(Qt.CheckState.Checked)
        else:
            self._header.set_check_state(Qt.CheckState.PartiallyChecked)

    # ── 排序 ─────────────────────────────────────────────────────────

    def _on_col_clicked(self, section: int):
        if section == COL_CHECK:
            return   # checkbox 列由 sig_toggle 处理
        if self._sort_col == section:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = section
            self._sort_asc = True
        self._header.setSortIndicator(
            self._sort_col,
            Qt.SortOrder.AscendingOrder if self._sort_asc else Qt.SortOrder.DescendingOrder,
        )
        self._render()   # 重绘（数据不变，只改顺序）

    def _sort_key(self, a: dict):
        col = self._sort_col
        is_online = a.get("is_online", True)
        state = "offline" if not is_online else a.get("net_state", "normal")

        if col == COL_IP:
            try:
                return int(_ipmod.IPv4Address(a.get("ip", "")))
            except Exception:
                return 0
        if col == COL_HOST:
            return a.get("hostname", "").lower()
        if col == COL_STATE:
            return _STATE_SORT_ORDER.get(state, 99)
        if col == COL_CONN:
            return a.get("connected_at", "")
        if col == COL_LAST:
            return a.get("last_seen", "")
        if col == COL_BROWSE:
            domains = a.get("recent_domains", [])
            if domains:
                last = domains[-1]
                return (last.get("domain", "") if isinstance(last, dict) else str(last)).lower()
            return ""
        return ""

    def _sorted_agents(self) -> list[dict]:
        return sorted(self._agents, key=self._sort_key, reverse=not self._sort_asc)

    def _online_ips(self) -> set[str]:
        """当前在线的被控端 IP 集合（排除已断开的）。"""
        return {a.get("ip") for a in self._agents if a.get("is_online", True)}

    def _emit_targeted(self, signal):
        """
        统一按钮逻辑（仅操作在线机器）：
          - 未勾选 / 全部勾选 → 应用到所有在线（发空列表）
          - 勾选了部分 → 只对勾选的在线机器应用
        """
        online = self._online_ips()
        if not online:
            return
        checked_online = self._checked_ips & online
        if not checked_online or checked_online >= online:
            signal.emit([])
        else:
            signal.emit(list(checked_online))

    # ── 右键菜单 ─────────────────────────────────────────────────────

    def _show_context_menu(self, pos):
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        ip_item = self._table.item(row, COL_IP)
        if not ip_item:
            return
        ip = ip_item.text()
        agent = next((a for a in self._agents if a.get("ip") == ip), None)
        if not agent:
            return
        menu = QMenu(self)
        act_browse = menu.addAction("查看浏览记录")
        act = menu.exec(self._table.viewport().mapToGlobal(pos))
        if act == act_browse:
            dlg = _BrowseDialog(ip, agent.get("recent_domains", []), self)
            dlg.exec()

    # ── 扫描 ─────────────────────────────────────────────────────────

    def _do_scan(self):
        subnet = self._scan_input.text().strip()
        if subnet:
            self.sig_scan.emit(subnet)

    # ── 刷新 ─────────────────────────────────────────────────────────

    def refresh(self, agents: list[dict]):
        self._agents = agents
        self._checked_ips &= self._online_ips()   # 断开的 IP 从勾选中移除
        self._render()

    def _render(self):
        agents = self._sorted_agents()
        self._table.blockSignals(True)
        self._table.setRowCount(len(agents))
        for row, a in enumerate(agents):
            ip        = a.get("ip", "")
            is_online = a.get("is_online", True)
            net_state = "offline" if not is_online else a.get("net_state", "normal")
            label, color = NET_STATE_DISPLAY.get(
                net_state, ("未知", QColor(150, 150, 150))
            )

            chk = QTableWidgetItem()
            if is_online:
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk.setCheckState(
                    Qt.CheckState.Checked if ip in self._checked_ips
                    else Qt.CheckState.Unchecked
                )
            else:
                # 离线行：checkbox 禁用，不可勾选
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable)
                chk.setCheckState(Qt.CheckState.Unchecked)
            self._table.setItem(row, COL_CHECK, chk)

            def _mk(text: str, offline: bool = not is_online) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                if offline:
                    item.setForeground(QColor(160, 160, 160))
                    item.setBackground(_COLOR_OFFLINE_BG)
                return item

            self._table.setItem(row, COL_IP,   _mk(ip))
            self._table.setItem(row, COL_HOST, _mk(a.get("hostname", "")))

            state_item = _mk(f"● {label}")
            state_item.setForeground(color)   # 覆盖颜色以显示正确状态色
            self._table.setItem(row, COL_STATE, state_item)

            self._table.setItem(row, COL_CONN, _mk(a.get("connected_at", "")))
            self._table.setItem(row, COL_LAST, _mk(a.get("last_seen",    "")))

            domains = a.get("recent_domains", [])
            last_txt = "—"
            if domains:
                last = domains[-1]
                last_txt = last.get("domain", "") if isinstance(last, dict) else str(last)
            self._table.setItem(row, COL_BROWSE, _mk(last_txt))

        self._table.blockSignals(False)
        self._update_header_state()

        n_online  = sum(1 for a in agents if a.get("is_online", True))
        n_offline = len(agents) - n_online
        filtering = sum(1 for a in agents if a.get("filter_active") and a.get("is_online", True))
        parts = [f"在线: {n_online} 台"]
        if n_offline:
            parts.append(f"离线: {n_offline} 台")
        parts.append(f"过滤中: {filtering} 台")
        self._label_count.setText(" | ".join(parts))
