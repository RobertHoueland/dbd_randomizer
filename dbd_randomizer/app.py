"""Desktop application entry point and orchestration."""

from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSettings, QStandardPaths, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .artwork import downloads
from .core import POOL_KINDS, ROLES, Loadout, roll, with_equipment
from .data_service import DataService, RefreshCancelled, Snapshot
from .widgets import EquipmentToggle, LoadoutCard, PoolDialog, label


class RefreshThread(QThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, service: DataService, parent=None):
        super().__init__(parent)
        self.service = service

    def run(self):
        # Only the download runs here; signals hand UI updates back to the GUI thread.
        try:
            self.loaded.emit(self.service.refresh(cancelled=self.isInterruptionRequested))
        except RefreshCancelled:
            pass
        except Exception as error:
            # Keep the existing roster and always allow QThread.run to return cleanly.
            self.failed.emit(f"Refresh failed: {error}. Your existing roster is still available.")


class MainWindow(QMainWindow):
    def __init__(self, service: DataService | None = None, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle("Dead by Daylight · Loadout Randomizer")
        self.setWindowIcon(QIcon(str(files("dbd_randomizer").joinpath("app.ico"))))
        self.setMinimumSize(1000, 700)
        self.resize(1240, 940)
        self.setStyleSheet(files("dbd_randomizer").joinpath("style.qss").read_text("utf-8"))
        self.settings = settings if settings is not None else QSettings()
        self.service = service or DataService(
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
        )
        self.snapshot = self.service.load()
        self.catalog = self.snapshot.catalog
        self.role = self.settings.value("role", "survivor")
        if self.role not in ROLES:
            self.role = "survivor"
        self.exclusions = self.read_exclusions()
        self.current: Loadout | None = None
        self.history: list[Loadout] = []
        self.history_times: list[datetime] = []
        self.worker: RefreshThread | None = None
        self.close_after_refresh = False
        self.build_ui()
        geometry = self.settings.value("geometry")
        if isinstance(geometry, (QByteArray, bytes, bytearray)):
            self.restoreGeometry(geometry)
        self.update_pool_summary()
        self.update_source()
        self.generate()
        if self.snapshot.warning:
            self.notify(self.snapshot.warning, error=True)
        for key, callback in (
            ("Space", self.generate),
            ("Ctrl+Shift+C", self.copy_build),
            ("Escape", self.edit_pool),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(callback)

    def read_exclusions(self):
        def defaults():
            return {
                role: {kind: self.catalog.default_exclusions(kind, role) for kind in POOL_KINDS}
                for role in ROLES
            }

        # Store exclusions rather than an allowlist so new regular entries join the
        # pool automatically. Event items are the opt-in exception below.
        default = defaults()
        # Older versions implicitly included every event item. Only explicit opt-ins
        # saved by this version override the new default, including after a refresh.
        try:
            opt_ins = json.loads(self.settings.value("event_item_opt_ins", "[]"))
            if not isinstance(opt_ins, list) or not all(isinstance(i, str) for i in opt_ins):
                raise ValueError("Invalid saved event item choices")
        except (ValueError, TypeError):
            opt_ins = []
        try:
            raw = json.loads(self.settings.value("exclusions", "{}"))
            for role in ROLES:
                for kind in POOL_KINDS:
                    ids = raw.get(role, {}).get(kind, [])
                    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                        raise ValueError("Invalid saved pool")
                    default[role][kind] = set(ids)
                # Roster removals must not strand the user with an unusable saved pool.
                if (
                    not self.catalog.pool("characters", role, default[role]["characters"])
                    or len(self.catalog.pool("perks", role, default[role]["perks"])) < 4
                ):
                    default[role]["characters"] = set()
                    default[role]["perks"] = set()
                default[role]["items"].update(
                    self.catalog.default_exclusions("items", role) - set(opt_ins)
                )
        except (ValueError, TypeError, AttributeError):
            return defaults()
        return default

    def build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll)
        root = QWidget()
        root.setObjectName("canvas")
        scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 24, 30, 12)
        layout.setSpacing(18)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        brand.setSpacing(5)
        brand.addWidget(label("DEAD BY DAYLIGHT", "brand"))
        brand.addWidget(label("THE LOADOUT RANDOMIZER", "eyebrow"))
        header.addLayout(brand)
        header.addStretch()
        self.source_label = label("", "sourceBadge")
        header.addWidget(self.source_label)
        self.refresh_button = QPushButton("Refresh roster")
        self.refresh_button.setToolTip("Download a new roster from dbd.tricky.lol (four requests).")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        intro = QHBoxLayout()
        title = QVBoxLayout()
        title.setSpacing(6)
        title.addWidget(label("Leave your build to fate.", "heroTitle"))
        intro.addLayout(title, 1)
        role_switch = QFrame()
        role_switch.setObjectName("roleSwitch")
        roles = QHBoxLayout(role_switch)
        roles.setContentsMargins(5, 5, 5, 5)
        roles.setSpacing(4)
        self.role_group = QButtonGroup(self)
        self.role_buttons = {}
        for role in ROLES:
            button = QPushButton(role.title())
            button.setObjectName("roleButton")
            button.setProperty("role", role)
            button.setCheckable(True)
            button.setChecked(role == self.role)
            button.setMinimumWidth(100)
            button.clicked.connect(lambda _, value=role: self.change_role(value))
            self.role_group.addButton(button)
            self.role_buttons[role] = button
            roles.addWidget(button)
        intro.addWidget(role_switch)
        layout.addLayout(intro)

        body = QHBoxLayout()
        body.setSpacing(22)
        build_column = QVBoxLayout()
        build_column.setSpacing(14)
        build_header = QHBoxLayout()
        self.build_heading = label("YOUR SURVIVOR BUILD", "eyebrow")
        build_header.addWidget(self.build_heading)
        build_header.addStretch()
        self.unlock_button = QPushButton("Unlock all")
        self.unlock_button.setObjectName("unlockButton")
        self.unlock_button.clicked.connect(self.unlock_all)
        build_header.addWidget(self.unlock_button)
        build_column.addLayout(build_header)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = [LoadoutCard(slot) for slot in range(5)]
        for card in self.cards:
            card.lock_changed.connect(lambda card=card: self.sync_locks(card))
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        grid.addWidget(self.cards[0], 0, 0, 2, 1)
        for slot in range(1, 5):
            grid.addWidget(self.cards[slot], (slot - 1) // 2, (slot - 1) % 2 + 1)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        grid.setRowMinimumHeight(0, 220)
        grid.setRowMinimumHeight(1, 220)
        build_column.addLayout(grid, 1)

        self.equipment_panel = QWidget()
        equipment_layout = QHBoxLayout(self.equipment_panel)
        equipment_layout.setContentsMargins(0, 0, 0, 0)
        equipment_layout.setSpacing(12)
        self.equipment_cards = [LoadoutCard(slot) for slot in range(5, 8)]
        for card in self.equipment_cards:
            card.lock_changed.connect(lambda card=card: self.sync_locks(card))
            card.setMinimumHeight(220)
            equipment_layout.addWidget(card, 1)
        self.equipment_panel.hide()
        build_column.addWidget(self.equipment_panel)

        controls = QFrame()
        controls.setObjectName("controls")
        control_layout = QVBoxLayout(controls)
        control_layout.setContentsMargins(18, 16, 18, 16)
        control_layout.setSpacing(12)
        self.equipment_toggle = EquipmentToggle("&Include items and add-ons")
        self.equipment_toggle.setToolTip(
            "Off: character and perks only. On: a Survivor item with up to two compatible "
            "add-ons, or up to two add-ons for the chosen Killer. Toggling preserves your "
            "character and perks. Unlocked equipment rerolls with each new build. "
            "Turning this off clears equipment locks."
        )
        self.equipment_toggle.setChecked(
            str(self.settings.value("include_equipment", "false")).lower() == "true"
        )
        self.equipment_toggle.toggled.connect(self.change_equipment)
        intro.insertWidget(1, self.equipment_toggle)
        intro.insertSpacing(2, 16)
        primary_row = QHBoxLayout()
        self.roll_button = QPushButton("Roll a new build   ↗")
        self.roll_button.setObjectName("primaryButton")
        self.roll_button.setMinimumHeight(48)
        self.roll_button.setToolTip("Randomize unlocked slots · Space")
        self.roll_button.clicked.connect(self.generate)
        primary_row.addWidget(self.roll_button, 1)
        self.copy_button = QPushButton("Copy build")
        self.copy_button.setMinimumHeight(48)
        self.copy_button.clicked.connect(self.copy_build)
        primary_row.addWidget(self.copy_button)
        control_layout.addLayout(primary_row)
        build_column.addWidget(controls)
        body.addLayout(build_column, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 22, 20, 20)
        side.setSpacing(14)
        side.addWidget(label("YOUR SELECTION POOL", "eyebrow"))
        self.pool_count = label("", "poolCount", True)
        side.addWidget(self.pool_count)
        side.addWidget(label("Only roll what you want to play.", "muted", True))
        self.pool_button = QPushButton("Customize pool")
        self.pool_button.setToolTip("Customize your selection pool · Escape")
        self.pool_button.clicked.connect(self.edit_pool)
        side.addWidget(self.pool_button)
        side.addSpacing(10)
        side.addWidget(label("RECENT BUILDS", "eyebrow"))
        side.addWidget(label("Select a build to bring it back.", "muted", True))
        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.setMinimumHeight(160)
        self.history_list.itemClicked.connect(self.restore_history)
        self.history_list.itemActivated.connect(self.restore_history)
        side.addWidget(self.history_list, 1)
        side.addWidget(label("Space  roll  ·  Esc  pool", "shortcut", True))
        body.addWidget(sidebar)
        content = QVBoxLayout()
        content.setSpacing(8)
        content.addLayout(body, 1)
        layout.addLayout(content, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.hide()
        content.addWidget(self.progress)
        self.notice = label("", "notice", True)
        self.notice.setMinimumHeight(22)
        self.notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.notice.hide()
        content.addWidget(self.notice)
        footer = QHBoxLayout()
        footer.addWidget(
            label(
                "Unofficial fan project · Not affiliated with Behaviour Interactive",
                "footer",
                True,
            ),
            1,
        )
        content.addLayout(footer)
        self.update_locks()

    def notify(self, message: str, error=False):
        self.notice.setText(message)
        self.notice.setVisible(bool(message))
        self.notice.setProperty("error", error)
        # Qt does not reapply property-based stylesheet rules when a property changes.
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)

    def update_source(self):
        self.source_label.setText("●  " + self.snapshot.source)

    def update_pool_summary(self):
        exclusions = self.exclusions[self.role]
        characters = len(self.catalog.pool("characters", self.role, exclusions["characters"]))
        perks = len(self.catalog.pool("perks", self.role, exclusions["perks"]))
        summary = f"{characters} characters\n{perks} perks"
        if self.equipment_toggle.isChecked():
            if self.role == "survivor":
                count = len(self.catalog.pool("items", self.role, exclusions["items"]))
                summary += f"\n{count} items"
            count = len(self.catalog.pool("addons", self.role, exclusions["addons"]))
            summary += f"\n{count} add-ons"
        self.pool_count.setText(summary)
        self.build_heading.setText(f"YOUR {self.role.upper()} BUILD")

    def sync_locks(self, card):
        parent = self.equipment_cards[0] if self.role == "survivor" else self.cards[0]
        if card.slot >= 6 and card.lock.isChecked():
            parent.lock.setChecked(True)
        elif card is parent and not card.lock.isChecked():
            for addon in self.equipment_cards[1:]:
                addon.lock.setChecked(False)
        self.update_locks()

    def update_locks(self):
        all_cards = self.cards + self.equipment_cards
        self.unlock_button.setEnabled(any(card.lock.isChecked() for card in all_cards))
        active = list(self.cards)
        if self.equipment_toggle.isChecked():
            active += [card for card in self.equipment_cards if card.entry is not None]
        self.roll_button.setEnabled(any(not card.lock.isChecked() for card in active))

    def unlock_all(self):
        for card in self.cards + self.equipment_cards:
            card.lock.setChecked(False)

    def change_role(self, role):
        if role == self.role:
            return
        self.role = role
        self.current = None
        self.unlock_all()
        self.update_pool_summary()
        self.save_settings()
        self.generate()

    def change_equipment(self, enabled):
        if not enabled:
            for card in self.equipment_cards:
                card.lock.setChecked(False)
        self.update_pool_summary()
        self.update_locks()
        self.generate()
        self.save_settings()

    def generate(self):
        locks = frozenset(
            card.slot for card in self.cards + self.equipment_cards if card.lock.isChecked()
        )
        include_equipment = self.equipment_toggle.isChecked()
        mode_changed = self.current and self.current.include_equipment != include_equipment
        if len(locks) == 5 and not include_equipment and not mode_changed:
            self.notify("All slots are locked. Unlock a slot to roll something new.")
            return
        seed = secrets.token_hex(16)
        exclusions = self.exclusions[self.role]
        try:
            if mode_changed:
                # A checkbox change only edits equipment, even if the displayed
                # character/perks have since been excluded from the next-roll pool.
                result = with_equipment(
                    self.catalog,
                    self.current,
                    include_equipment,
                    exclusions["items"],
                    exclusions["addons"],
                )
            else:
                result = roll(
                    self.catalog,
                    self.role,
                    seed,
                    exclusions["characters"],
                    exclusions["perks"],
                    self.current,
                    locks,
                    include_equipment=include_equipment,
                    excluded_items=exclusions["items"],
                    excluded_addons=exclusions["addons"],
                )
        except ValueError as error:
            # A failed mode change must not leave controls contradicting the displayed build.
            if mode_changed:
                self.set_equipment_mode(self.current.include_equipment)
            elif self.current is None and include_equipment:
                # A saved empty item pool must not prevent startup or role switching.
                self.set_equipment_mode(False)
                self.generate()
                self.save_settings()
            self.notify(str(error), error=True)
            return
        self.show_build(result)
        self.history.insert(0, result)
        self.history_times.insert(0, datetime.now().astimezone())
        self.history = self.history[:20]
        self.history_times = self.history_times[:20]
        self.history_list.clear()
        for index, build in enumerate(self.history):
            rolled_at = self.history_times[index]
            item = QListWidgetItem(
                f"{build.character.name}\n{build.role.title()} · {rolled_at:%H:%M:%S}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(f"Rolled {rolled_at:%Y-%m-%d %H:%M:%S %Z}\n\n{build.text()}")
            self.history_list.addItem(item)
        self.notify("")

    def set_equipment_mode(self, enabled):
        # Restoring a build or rolling back a failed toggle must not trigger another roll.
        self.equipment_toggle.blockSignals(True)
        self.equipment_toggle.setChecked(enabled)
        self.equipment_toggle.blockSignals(False)
        self.update_pool_summary()
        self.update_locks()

    def show_build(self, build):
        self.current = build
        self.set_equipment_mode(build.include_equipment)
        for card, entry in zip(self.cards, (build.character, *build.perks)):
            card.set_entry(entry)
        self.equipment_panel.setVisible(build.include_equipment)
        self.equipment_cards[0].setVisible(build.item is not None)
        if build.item:
            self.equipment_cards[0].set_entry(build.item)
        else:
            self.equipment_cards[0].set_empty()
        for index, card in enumerate(self.equipment_cards[1:]):
            if index < len(build.addons):
                card.set_entry(build.addons[index])
            else:
                card.set_empty()
        self.update_locks()
        self.copy_button.setEnabled(True)

    def restore_history(self, item):
        build = self.history[item.data(Qt.ItemDataRole.UserRole)]
        self.role = build.role
        self.role_buttons[self.role].setChecked(True)
        self.unlock_all()
        self.show_build(build)
        self.update_pool_summary()
        self.save_settings()
        self.notify(f"Restored {build.character.name}. Current pool is unchanged.")

    def copy_build(self):
        if self.current:
            QApplication.clipboard().setText(self.current.text())
            self.notify("Build copied to clipboard. See you in the fog.")

    def edit_pool(self):
        # A dialog edits one catalog snapshot; don't let it save stale choices over a refresh.
        if self.worker is not None:
            self.notify("Wait for the roster refresh to finish before changing the selection pool.")
            return
        if not self.pool_button.isEnabled():
            return
        original_text = self.pool_button.text()
        self.pool_button.setEnabled(False)
        self.pool_button.setText("⌛ Loading pool…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # Paint before the synchronous dialog/icon setup blocks the GUI thread.
            # Avoid processEvents(), which could dispatch unrelated actions mid-setup.
            self.pool_button.repaint()
            dialog = PoolDialog(self.catalog, self.role, self.exclusions[self.role], self)
        finally:
            QApplication.restoreOverrideCursor()
            self.pool_button.setText(original_text)
            self.pool_button.setEnabled(True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.exclusions[self.role] = dialog.exclusions
            self.save_settings()
            self.update_pool_summary()
            # A changed pool applies on the next roll; never silently mutate the shown build.
            for card in self.cards + self.equipment_cards:
                kind = (
                    "characters" if card.slot == 0 else "perks" if card.slot <= 4
                    else "items" if card.slot == 5 else "addons"
                )
                if card.entry and card.entry.id in dialog.exclusions[kind]:
                    card.lock.setChecked(False)
            self.notify(
                "Selection saved. Excluded slots unlocked; the new pool applies on your next roll."
            )

    def refresh(self):
        if self.worker is not None:
            return
        self.refresh_button.setEnabled(False)
        self.pool_button.setEnabled(False)
        self.progress.show()
        self.notify("Refreshing the roster… You can keep rolling while it downloads.")
        self.worker = RefreshThread(self.service, self)
        self.worker.loaded.connect(self.apply_snapshot)
        self.worker.failed.connect(lambda message: self.notify(message, error=True))
        self.worker.finished.connect(self.refresh_finished)
        self.worker.start()

    def apply_snapshot(self, snapshot: Snapshot):
        self.snapshot = snapshot
        self.catalog = snapshot.catalog
        self.exclusions = self.read_exclusions()
        # Old builds hold Entry objects from the previous catalog. Drop them rather
        # than carry removed entries or outdated compatibility data into the new roster.
        self.unlock_all()
        self.current = None
        self.history.clear()
        self.history_times.clear()
        self.history_list.clear()
        self.update_source()
        self.update_pool_summary()
        self.generate()
        self.notify("Roster updated. Started a fresh build and cleared old locks and history.")

    def refresh_finished(self):
        self.progress.hide()
        self.refresh_button.setEnabled(True)
        self.pool_button.setEnabled(True)
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        if self.close_after_refresh:
            self.close()

    def save_settings(self):
        self.settings.setValue("role", self.role)
        self.settings.setValue("include_equipment", self.equipment_toggle.isChecked())
        self.settings.setValue(
            "event_item_opt_ins",
            json.dumps(
                sorted(
                    self.catalog.default_exclusions("items", "survivor")
                    - self.exclusions["survivor"]["items"]
                )
            ),
        )
        self.settings.setValue(
            "exclusions",
            json.dumps(
                {
                    role: {kind: sorted(ids) for kind, ids in pools.items()}
                    for role, pools in self.exclusions.items()
                }
            ),
        )
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.sync()

    def closeEvent(self, event):
        if self.worker is not None:
            # Destroying a running QThread is unsafe. Defer closing until it finishes,
            # without blocking the GUI while the current socket operation times out.
            self.close_after_refresh = True
            self.worker.requestInterruption()
            self.notify("Cancelling the roster request before closing…")
            event.ignore()
            return
        self.save_settings()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DBD Randomizer")
    app.setOrganizationName("DBDRandomizer")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    downloads().enabled = True
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
