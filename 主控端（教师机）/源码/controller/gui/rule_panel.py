"""
白名单 / 黑名单规则管理面板
每条规则：名称 + 域名 + 启用复选框
双击「名称」或「域名」单元格可直接编辑，回车或失焦时保存。
白名单添加对话框带「自动发现依赖」按钮，可批量导入网页引用的资源域名。
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QTabWidget, QDialog, QFormLayout, QLineEdit,
    QMessageBox, QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem,
    QProgressDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread

from controller.db.database import Database
from controller.dep_discover import discover_dependencies

COL_CHECK  = 0
COL_NAME   = 1
COL_DOMAIN = 2
COLS = ["启用", "名称", "域名"]


class _DiscoverThread(QThread):
    """后台抓取目标网页 + 解析依赖域名，避免阻塞 UI。"""
    done = pyqtSignal(list, str)   # (domains, error)

    def __init__(self, target: str, parent=None):
        super().__init__(parent)
        self._target = target

    def run(self):
        domains, err = discover_dependencies(self._target)
        self.done.emit(domains, err)


class _DepSelectDialog(QDialog):
    """依赖发现结果的多选确认对话框：默认全选，老师可勾选。"""
    def __init__(self, base_name: str, domains: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"自动发现依赖 — {base_name}")
        self.setModal(True)
        self.setMinimumSize(440, 380)
        self._base_name = base_name

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"共发现 {len(domains)} 个相关域名，勾选要加入白名单的条目：\n"
            "（动态加载的资源扫不到，必要时用 F12 抓包补全）"
        ))

        self._list = QListWidget()
        for d in domains:
            item = QListWidgetItem(d)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._list.addItem(item)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_all  = QPushButton("全选")
        btn_none = QPushButton("全不选")
        btn_all.clicked.connect(lambda: self._toggle_all(True))
        btn_none.clicked.connect(lambda: self._toggle_all(False))
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        btn_ok     = QPushButton("加入白名单")
        btn_cancel = QPushButton("取消")
        btn_ok.setStyleSheet("background:#27ae60;color:white;padding:4px 18px;")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _toggle_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)

    def selected_domains(self) -> list[str]:
        out: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out


class _AddDialog(QDialog):
    def __init__(self, title: str, parent=None, allow_discover: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self._discovered: list[str] = []   # 发现的依赖域名列表（接受时由调用方读取）

        layout = QFormLayout(self)
        self._name   = QLineEdit()
        self._domain = QLineEdit()
        self._name.setPlaceholderText("例如：百度")
        self._domain.setPlaceholderText("例如：baidu.com 或 *.baidu.com")
        layout.addRow("名称:", self._name)
        layout.addRow("域名:", self._domain)

        if allow_discover:
            self._btn_discover = QPushButton("🔍  自动发现依赖")
            self._btn_discover.setStyleSheet(
                "background:#8e44ad;color:white;padding:5px 12px;border-radius:3px;"
            )
            self._btn_discover.clicked.connect(self._do_discover)
            tip = QLabel("点击后会抓取该网站的首页并解析里面引用的资源域名")
            tip.setStyleSheet("color:gray;font-size:11px;")
            layout.addRow("", self._btn_discover)
            layout.addRow("", tip)

        btns = QHBoxLayout()
        btn_ok     = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        btn_ok.setStyleSheet("background:#3498db;color:white;padding:4px 16px;")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addRow(btns)
        self._name.returnPressed.connect(self._domain.setFocus)
        self._domain.returnPressed.connect(self.accept)

    @property
    def name(self) -> str:
        return self._name.text().strip()

    @property
    def domain(self) -> str:
        return self._domain.text().strip()

    @property
    def discovered_domains(self) -> list[str]:
        return list(self._discovered)

    def _do_discover(self):
        target = self._domain.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "请先在「域名」里填入网站，例如 doubao.com")
            return

        progress = QProgressDialog(f"正在抓取 {target} 并解析依赖...", "取消", 0, 0, self)
        progress.setWindowTitle("自动发现依赖")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        thread = _DiscoverThread(target, self)
        result: dict = {}

        def on_done(domains: list, err: str):
            result["domains"] = domains
            result["err"] = err
            progress.close()
            thread.deleteLater()

        thread.done.connect(on_done)
        thread.start()

        # 同步等待（progress dialog 已经把 UI 响应让出去了）
        while thread.isRunning():
            if progress.wasCanceled():
                thread.terminate()
                thread.wait(1000)
                return
            QThread.msleep(50)
            from PyQt6.QtWidgets import QApplication as _App
            _App.processEvents()

        err = result.get("err", "")
        domains = result.get("domains", [])
        if err:
            QMessageBox.warning(self, "抓取失败", f"无法发现依赖：{err}")
            return
        if not domains:
            QMessageBox.information(self, "提示", "没有发现额外的外部域名")
            return

        dlg = _DepSelectDialog(target, domains, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.selected_domains()
        if not selected:
            return
        # 标记已发现 + 关闭对话框，让上层一次性批量插入
        self._discovered = selected
        if not self._name.text().strip():
            # 用主域作为名称默认值
            base = target.replace("https://", "").replace("http://", "").rstrip("/")
            self._name.setText(base)
        self.accept()


class _RuleTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, db: Database, list_fn, add_fn, set_enabled_fn, update_fn,
                 del_fn, add_dialog_title: str, allow_discover: bool = False,
                 parent=None):
        super().__init__(parent)
        self._db = db
        self._list_fn = list_fn
        self._add_fn = add_fn
        self._set_enabled_fn = set_enabled_fn
        self._update_fn = update_fn
        self._del_fn = del_fn
        self._add_dialog_title = add_dialog_title
        self._allow_discover = allow_discover
        self._build_ui()
        self.reload()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_CHECK, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # 允许双击编辑（具体哪些列可编辑通过 item flags 控制）
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table.setAlternatingRowColors(True)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ 添加条目")
        btn_del = QPushButton("删除选中")
        btn_add.setStyleSheet("background:#3498db;color:white;padding:4px 14px;")
        btn_del.setStyleSheet("background:#e74c3c;color:white;padding:4px 14px;")
        btn_add.clicked.connect(self._add_entry)
        btn_del.clicked.connect(self._del_entry)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        tip = QLabel("提示：双击「名称」或「域名」单元格可直接修改")
        tip.setStyleSheet("color:gray;font-size:11px;")
        btn_row.addWidget(tip)
        layout.addLayout(btn_row)

    def _on_item_changed(self, item: QTableWidgetItem):
        row = item.row()
        col = item.column()
        domain_item = self._table.item(row, COL_DOMAIN)
        if domain_item is None:
            return
        row_id = domain_item.data(Qt.ItemDataRole.UserRole)
        if row_id is None:
            return

        if col == COL_CHECK:
            enabled = item.checkState() == Qt.CheckState.Checked
            self._set_enabled_fn(row_id, enabled)
            self.changed.emit()
            return

        if col in (COL_NAME, COL_DOMAIN):
            name_item = self._table.item(row, COL_NAME)
            new_name   = (name_item.text() if name_item else "").strip()
            new_domain = domain_item.text().strip().lower()
            if not new_name or not new_domain:
                QMessageBox.warning(self, "提示", "名称和域名均不能为空")
                self.reload()
                return
            ok = self._update_fn(row_id, new_name, new_domain)
            if not ok:
                QMessageBox.warning(
                    self, "提示",
                    f"域名 “{new_domain}” 与现有条目冲突，已撤销修改"
                )
                self.reload()
                return
            self.changed.emit()

    def _add_entry(self):
        dlg = _AddDialog(self._add_dialog_title, self, allow_discover=self._allow_discover)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, domain = dlg.name, dlg.domain

        discovered = dlg.discovered_domains
        if discovered:
            # 「自动发现依赖」模式：批量插入多条
            added_n  = 0
            skipped  = []
            for d in discovered:
                d_clean = d.strip().lower()
                if not d_clean:
                    continue
                entry_name = f"{name} - {d_clean}" if name else d_clean
                if self._add_fn(entry_name, d_clean):
                    added_n += 1
                else:
                    skipped.append(d_clean)
            self.reload()
            self.changed.emit()
            msg = f"已添加 {added_n} 条域名"
            if skipped:
                msg += f"，{len(skipped)} 条已存在被跳过"
            QMessageBox.information(self, "完成", msg)
            return

        # 普通单条添加
        if not name or not domain:
            QMessageBox.warning(self, "提示", "名称和域名均不能为空")
            return
        if not self._add_fn(name, domain):
            QMessageBox.warning(self, "提示", "该域名已存在")
            return
        self.reload()
        self.changed.emit()

    def _del_entry(self):
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        if not rows:
            return
        reply = QMessageBox.question(self, "确认", f"删除选中的 {len(rows)} 条记录？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            domain_item = self._table.item(row, COL_DOMAIN)
            if domain_item:
                row_id = domain_item.data(Qt.ItemDataRole.UserRole)
                if row_id is not None:
                    self._del_fn(row_id)
        self.reload()
        self.changed.emit()

    def reload(self):
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for entry in self._list_fn():
            row = self._table.rowCount()
            self._table.insertRow(row)

            chk = QTableWidgetItem()
            # CHECK 列：可勾选不可编辑
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(
                Qt.CheckState.Checked if entry["enabled"] else Qt.CheckState.Unchecked
            )
            self._table.setItem(row, COL_CHECK, chk)

            # NAME / DOMAIN 列：可编辑
            editable = (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled |
                        Qt.ItemFlag.ItemIsEditable)
            name_item = QTableWidgetItem(entry["name"])
            name_item.setFlags(editable)
            self._table.setItem(row, COL_NAME, name_item)

            domain_item = QTableWidgetItem(entry["domain"])
            domain_item.setFlags(editable)
            domain_item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self._table.setItem(row, COL_DOMAIN, domain_item)
        self._table.blockSignals(False)


class RulePanel(QWidget):
    sig_rules_changed = pyqtSignal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()

        self._whitelist_tab = _RuleTab(
            self.db,
            self.db.list_whitelist,
            self.db.add_whitelist,
            self.db.set_whitelist_enabled,
            self.db.update_whitelist,
            self.db.delete_whitelist,
            "添加白名单条目",
            allow_discover=True,
        )
        self._whitelist_tab.changed.connect(self.sig_rules_changed)
        tabs.addTab(self._whitelist_tab, "白名单")

        self._blacklist_tab = _RuleTab(
            self.db,
            self.db.list_blacklist,
            self.db.add_blacklist,
            self.db.set_blacklist_enabled,
            self.db.update_blacklist,
            self.db.delete_blacklist,
            "添加黑名单条目",
        )
        self._blacklist_tab.changed.connect(self.sig_rules_changed)
        tabs.addTab(self._blacklist_tab, "黑名单")

        layout.addWidget(tabs)

    def reload(self):
        self._whitelist_tab.reload()
        self._blacklist_tab.reload()
