"""Reusable loadout cards and selection-pool editor."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .artwork import downloads, entry_pixmap
from .core import POOL_KINDS, Catalog, Entry


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    # Names and descriptions come from upstream; never let QLabel guess they're HTML.
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class EquipmentToggle(QCheckBox):
    """A full-width checkbox button with a crisp, theme-independent check mark."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("equipmentToggle")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def hitButton(self, position):
        # QCheckBox normally ignores clicks in the space beyond its label.
        return self.rect().contains(position)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, self
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#203010" if self.isEnabled() else "#9896aa"), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(
                        indicator.x() + indicator.width() * x,
                        indicator.y() + indicator.height() * y,
                    )
                    for x, y in ((0.25, 0.51), (0.43, 0.69), (0.76, 0.32))
                ]
            )
        )


class Emblem(QWidget):
    """Cached game artwork with a fallback while downloads are unavailable."""

    def __init__(self, large=False):
        super().__init__()
        self.large = large
        self.setFixedHeight(180 if large else 76)
        if not large:
            self.setFixedWidth(76)
        self.initials = "?"
        self.pixmap = None
        self.role = "survivor"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.pixmap is not None and not self.pixmap.isNull():
            size = self.pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(
                (self.width() - size.width()) / 2,
                (self.height() - size.height()) / 2,
                size.width(),
                size.height(),
            )
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
            return
        cx, cy = self.width() / 2, self.height() / 2
        size = 65 if self.large else 35
        painter.setPen(QPen(QColor("#705784"), 1))
        background = "#43252d" if self.role == "killer" else "#20384e"
        painter.setBrush(QColor(background if self.large else "#352440"))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx, cy - size),
                    QPointF(cx + size, cy),
                    QPointF(cx, cy + size),
                    QPointF(cx - size, cy),
                ]
            )
        )
        if self.large:
            painter.setPen(QPen(QColor("#efa39c" if self.role == "killer" else "#8cc7f0"), 4))
            for offset in (-18, -6, 6, 18):
                painter.drawLine(
                    QPointF(cx + offset + 3, cy - 22), QPointF(cx + offset - 3, cy + 22)
                )
            painter.setPen(QPen(QColor("#d8b985"), 3))
            painter.drawLine(QPointF(cx - 27, cy + 13), QPointF(cx + 27, cy - 12))
        else:
            painter.setPen(QColor("#d5c2ed"))
            painter.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.initials)


class LoadoutCard(QFrame):
    lock_changed = pyqtSignal()

    def __init__(self, slot: int):
        super().__init__()
        self.slot = slot
        self.kind = (
            "characters"
            if slot == 0
            else ("perks" if slot <= 4 else "items" if slot == 5 else "addons")
        )
        self.entry = None
        downloads().ready.connect(self.artwork_ready)
        self.setObjectName("characterCard" if slot == 0 else "perkCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        top = QHBoxLayout()
        title = (
            "CHARACTER"
            if slot == 0
            else (
                f"PERK  /  0{slot}"
                if slot <= 4
                else "ITEM"
                if slot == 5
                else f"ADD-ON  /  0{slot - 5}"
            )
        )
        top.addWidget(label(title, "eyebrow"))
        top.addStretch()
        self.lock = QPushButton("Lock")
        self.lock.setObjectName("lockButton")
        self.lock.setCheckable(True)
        self.lock.setEnabled(False)
        slot_name = (
            "character" if slot == 0 else f"perk {slot}" if slot <= 4
            else "item" if slot == 5 else f"add-on {slot - 5}"
        )
        self.lock.setAccessibleName(f"Lock {slot_name}")
        self.lock.toggled.connect(self._lock_changed)
        top.addWidget(self.lock)
        self.lock.setToolTip("Keep this slot when rolling. Add-ons also lock their item or Killer.")
        layout.addLayout(top)
        self.faces = QStackedWidget()
        layout.addWidget(self.faces, 1)
        front = QWidget()
        front_layout = QVBoxLayout(front)
        front_layout.setContentsMargins(0, 0, 0, 0)
        front_layout.setSpacing(12)
        self.faces.addWidget(front)
        self.emblem = Emblem(slot == 0)
        self.name_label = label(
            "Let fate decide" if slot == 0 else "Unknown perk",
            "characterName" if slot == 0 else "perkName",
            True,
        )
        if slot == 0:
            front_layout.addStretch()
            front_layout.addWidget(self.emblem)
            self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            front_layout.addWidget(self.name_label)
        else:
            heading = QHBoxLayout()
            heading.setSpacing(14)
            heading.addWidget(self.emblem)
            heading.addWidget(self.name_label, 1)
            front_layout.addLayout(heading)
        self.description = label(
            "Your next trial starts with a little uncertainty."
            if slot == 0
            else "Roll a build to reveal this perk.",
            "description",
            True,
        )
        if slot == 0:
            self.description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        front_layout.addWidget(self.description)
        front_layout.addStretch()
        back = QWidget()
        back_layout = QVBoxLayout(back)
        back_layout.setContentsMargins(0, 0, 0, 0)
        self.back_title = label("", "perkName", True)
        back_layout.addWidget(self.back_title)
        self.full_description = QTextBrowser()
        self.full_description.setObjectName("cardDescription")
        self.full_description.setMinimumSize(0, 0)
        # Long descriptions should scroll inside the card, not inflate the whole grid.
        self.full_description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.full_description.setToolTip(
            "Descriptions use the highest perk tier. [in-game value] means unresolved tuning."
        )
        back_layout.addWidget(self.full_description, 1)
        self.faces.addWidget(back)
        self.details = QPushButton("Flip for details  ↻")
        self.details.setObjectName("textButton")
        self.details.setEnabled(False)
        self.details.clicked.connect(self.show_details)
        layout.addWidget(self.details, alignment=Qt.AlignmentFlag.AlignLeft)

    def _lock_changed(self, checked):
        self.lock.setText("Locked" if checked else "Lock")
        self.setProperty("locked", checked)
        self.style().unpolish(self)
        self.style().polish(self)
        self.lock_changed.emit()

    def artwork_ready(self, kind, entry_id):
        # The user may have rerolled while this download was in flight.
        if self.entry is not None and kind == self.kind and entry_id == self.entry.id:
            self.emblem.pixmap = entry_pixmap(kind, entry_id)
            self.emblem.setToolTip(self.entry.name)
            self.emblem.update()

    def set_entry(self, entry: Entry):
        changed = self.entry != entry
        self.entry = entry
        # Keep details open for an unchanged/locked entry, but reveal a newly rolled one.
        if changed:
            self.faces.setCurrentIndex(0)
            self.details.setText("Flip for details  ↻")
        self.back_title.setText(entry.name)
        self.full_description.setPlainText(entry.description or "No description available.")
        self.full_description.setAccessibleName(f"{entry.name} full description")
        self.name_label.setText(entry.name)
        self.emblem.initials = "".join(word[0] for word in entry.name.split()[:2]).upper()
        self.emblem.role = entry.role
        self.emblem.pixmap = entry_pixmap(self.kind, entry.id)
        self.emblem.setAccessibleName(f"{entry.name} artwork")
        self.emblem.setToolTip(
            entry.name if not self.emblem.pixmap.isNull() else "Artwork not yet available"
        )
        self.emblem.update()
        self.setProperty("role", entry.role)
        self.style().unpolish(self)
        self.style().polish(self)
        description = " ".join(entry.description.split()) or "No description available."
        maximum = 185 if self.slot == 0 else 115
        if len(description) > maximum:
            description = description[:maximum].rsplit(" ", 1)[0] + "…"
        self.description.setText(description)
        self.details.setEnabled(True)
        self.lock.setEnabled(True)

    def set_empty(self):
        self.lock.setChecked(False)
        self.entry = None
        self.faces.setCurrentIndex(0)
        self.details.setText("Flip for details  ↻")
        self.details.setEnabled(False)
        self.lock.setEnabled(False)
        self.name_label.setText("No add-on")
        self.description.setText("No more compatible add-ons in your selection pool.")
        self.back_title.clear()
        self.full_description.clear()
        self.emblem.pixmap = None
        self.emblem.initials = "—"
        self.emblem.setToolTip("")
        self.emblem.setAccessibleName("No add-on")
        self.emblem.update()

    def show_details(self):
        if not self.entry:
            return
        show_back = self.faces.currentIndex() == 0
        self.faces.setCurrentIndex(1 if show_back else 0)
        self.details.setText("Back to build  ↶" if show_back else "Flip for details  ↻")


class PoolCheckDelegate(QStyledItemDelegate):
    """Make the full row a check target without double-toggling the checkbox."""

    def editorEvent(self, event, model, option, index):
        # Handle mouse toggles on release only; letting Qt also handle the press
        # would toggle checkbox clicks twice while row clicks toggle once.
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if event.button() == Qt.MouseButton.LeftButton:
                return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if option.rect.contains(event.position().toPoint()) and (
                index.flags() & Qt.ItemFlag.ItemIsEnabled
                and index.flags() & Qt.ItemFlag.ItemIsUserCheckable
            ):
                checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
                return model.setData(
                    index,
                    Qt.CheckState.Unchecked.value if checked else Qt.CheckState.Checked.value,
                    Qt.ItemDataRole.CheckStateRole,
                )
            return False
        # Preserve Qt's Space-key toggle and accessibility check-state semantics.
        return super().editorEvent(event, model, option, index)


class PoolDialog(QDialog):
    def artwork_ready(self, kind, entry_id):
        listing = self.lists.get(kind)
        if listing is not None:
            for row in range(listing.count()):
                item = listing.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == entry_id:
                    item.setIcon(QIcon(entry_pixmap(kind, entry_id)))
                    break

    def __init__(self, catalog: Catalog, role: str, exclusions: dict[str, set[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{role.title()} selection pool")
        self.resize(620, 650)
        self.catalog, self.role = catalog, role
        # Copy the sets too: Cancel must not leak edits into the window's active pool.
        self.exclusions = {
            kind: set(exclusions.get(kind, catalog.default_exclusions(kind, role)))
            for kind in POOL_KINDS
        }
        self.lists = {}
        downloads().ready.connect(self.artwork_ready)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(
            label(
                "Uncheck characters, perks or equipment you don't want to roll.\n"
                "Your selection is saved separately for each role.\n"
                "Holiday and event items are off by default; check them to opt in.",
                "poolInstructions",
                True,
            )
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search characters, perks and equipment…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search selection pool")
        self.search.textChanged.connect(self.filter_items)
        layout.addWidget(self.search)
        self.tabs = QTabWidget()
        for kind in POOL_KINDS:
            if kind == "items" and role == "killer":
                continue
            listing = QListWidget()
            listing.setAlternatingRowColors(True)
            listing.setItemDelegate(PoolCheckDelegate(listing))
            listing.setIconSize(QSize(36, 36))
            for entry in catalog.pool(kind, role):
                item = QListWidgetItem(entry.name)
                item.setData(Qt.ItemDataRole.UserRole, entry.id)
                item.setIcon(QIcon(entry_pixmap(kind, entry.id)))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Unchecked
                    if entry.id in self.exclusions[kind]
                    else Qt.CheckState.Checked
                )
                if kind == "addons":
                    compatible = (
                        entry.item_type
                        if role == "survivor"
                        else ", ".join(
                            character.name
                            for character in catalog.pool("characters", role)
                            if character.power in entry.parents
                        )
                    )
                    item.setText(f"{entry.name} · {compatible}")
                item.setToolTip(entry.description)
                if kind == "items" and entry.event:
                    item.setText(f"{entry.name} · Event item")
                    item.setToolTip(
                        "Limited-time event item — excluded by default.\n\n" + entry.description
                    )
                listing.addItem(item)
            listing.itemChanged.connect(self.update_count)
            self.lists[kind] = listing
            self.tabs.addTab(listing, "Add-ons" if kind == "addons" else kind.title())
        layout.addWidget(self.tabs)
        actions = QHBoxLayout()
        for text, checked in (("Select all", True), ("Clear all", False)):
            button = QPushButton(text)
            button.setToolTip("Apply to all entries in this tab, including hidden search results.")
            button.clicked.connect(lambda _, value=checked: self.set_all(value))
            actions.addWidget(button)
        layout.addLayout(actions)
        self.count = label("", "muted", True)
        layout.addWidget(self.count)
        self.error = label("", "error", True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_count()

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride and event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Escape,
        ):
            # Keep Space for typing/checking and Escape for cancelling this dialog.
            event.accept()
            return True
        return super().event(event)

    def filter_items(self, query):
        for listing in self.lists.values():
            for i in range(listing.count()):
                item = listing.item(i)
                item.setHidden(query.casefold() not in item.text().casefold())

    def set_all(self, checked):
        listing = self.tabs.currentWidget()
        # Recount once after the bulk edit instead of rescanning for every changed row.
        # Search only hides rows; Select/Clear all deliberately affects the entire tab.
        listing.blockSignals(True)
        for i in range(listing.count()):
            item = listing.item(i)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        listing.blockSignals(False)
        self.update_count()

    def selected_count(self, kind):
        listing = self.lists[kind]
        return sum(
            listing.item(i).checkState() == Qt.CheckState.Checked for i in range(listing.count())
        )

    def update_count(self):
        self.count.setText(
            "  ·  ".join(
                f"{self.selected_count(kind)} {'add-ons' if kind == 'addons' else kind}"
                for kind in self.lists
            )
            + " selected"
        )

    def save(self):
        # Only the base build is mandatory. Empty equipment pools can be saved for
        # character/perk-only mode; roll() validates them when equipment is requested.
        if self.selected_count("characters") < 1 or self.selected_count("perks") < 4:
            self.error.setText("Keep at least 1 character and 4 perks selected.")
            return
        for kind, listing in self.lists.items():
            self.exclusions[kind] = {
                listing.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(listing.count())
                if listing.item(i).checkState() == Qt.CheckState.Unchecked
            }
        self.accept()
