"""Grafische Oberfläche (PySide6 / Qt 6)."""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import (QDate, QEvent, QLocale, QLibraryInfo, QRectF, QSettings, QStandardPaths, Qt,
                            QThread, QTimer, QTranslator, QUrl, Signal)
from PySide6.QtGui import (QAction, QBrush, QColor, QDesktopServices, QFont, QFontDatabase,
                           QIcon, QPainter, QPainterPath, QPalette, QPen, QTextDocument)
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCalendarWidget, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QInputDialog, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from . import __version__, i18n
from .analysis import (AVAIL, DRIVE, REST, UNKNOWN, WORK, Result, Settings, analyze,
                       coverage, remaining)
from .archive import Archive, DuplicateError, VuDownload
from .ddd import DddError
from .vault import LockedError, Vault, VaultError, WrongSecret, available as crypto_available
from .vu import (VuError, overspeed, parse_speed, parse_vu, speed_days, speed_series,
                 speed_stats)
from .demo import build_demo, build_demo_vu
from .i18n import event_name, fmt_date, fmt_dt, fmt_dur, fmt_finding, tr
from .pcsc import PCSC, PCSCError
from .tachocard import CardError, download_card, probe

UTC = dt.timezone.utc
APP_ID = "io.github.tachoarchiv.TachoArchiv"

# Farben orientieren sich an der Bedeutung, nicht an Dekoration:
# Lenken kräftig, Arbeit warm, Bereitschaft kühl, Ruhe zurückhaltend.
ACT_COLOR = {
    DRIVE: QColor("#1f4e8c"),
    WORK: QColor("#c77d0a"),
    AVAIL: QColor("#2f8a7e"),
    REST: QColor("#9fb4a0"),
    UNKNOWN: QColor("#c9c9c9"),
}
ACT_LEVEL = {REST: 0.22, UNKNOWN: 0.12, AVAIL: 0.48, WORK: 0.72, DRIVE: 1.0}
FERRY_COLOR = QColor("#6b3fa0")      # Fähr-/Zugüberfahrt, bewusst außerhalb der Aktivitätsfarben
SEV_COLOR = {"violation": QColor("#b3261e"), "warning": QColor("#8a5a00"), "info": QColor("#35607a")}
# Flächen für markierte Tage: hell genug, dass die Zahlen darauf lesbar bleiben
SEV_TINT = {"violation": QColor("#fbe3e0"), "warning": QColor("#fbf0dc")}
# Signaturzustände: nur „passt nicht" ist ein Fehler, alles andere heißt „nicht geprüft"
SIG_COLOR = {"ok": QColor("#2f6b3a"), "failed": QColor("#b3261e"),
             "partial": QColor("#8a5a00"), "no_root": QColor("#8a5a00"),
             "unsupported": QColor("#8a5a00")}
PERIODS = [("period_all", None), ("period_control", None), ("period_28", 28), ("period_365", 365)]


# --------------------------------------------------------------------------- Widgets

class DayBar(QWidget):
    """Stufendiagramm eines Tages wie auf dem Tachographen-Ausdruck."""

    def __init__(self, segments, crossings=(), parent=None):
        super().__init__(parent)
        self.segments = segments
        self.crossings = list(crossings)      # Fähr-/Zugüberfahrten als (von, bis) in Minuten
        self.setMinimumWidth(360)
        self.setMinimumHeight(30)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        r = self.rect().adjusted(4, 3, -4, -7)
        w, h = r.width(), r.height()
        pal = self.palette()
        grid = QPen(dim(pal, 0.45))
        grid.setWidth(1)
        p.setPen(grid)
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
        for hour in range(0, 25, 3):
            x = r.left() + round(w * hour / 24)
            p.drawLine(x, r.bottom(), x, r.bottom() + (4 if hour % 6 == 0 else 2))
        p.setPen(Qt.PenStyle.NoPen)
        for s, e, act, manual in self.segments:
            x0 = r.left() + w * s / 1440
            x1 = r.left() + w * e / 1440
            hh = max(2, round(h * ACT_LEVEL[act]))
            brush = QBrush(ACT_COLOR[act], Qt.BrushStyle.BDiagPattern if manual else
                           (Qt.BrushStyle.Dense5Pattern if act == UNKNOWN else Qt.BrushStyle.SolidPattern))
            p.setBrush(brush)
            p.drawRect(round(x0), r.bottom() - hh, max(1, round(x1 - x0)), hh)
        p.setBrush(QBrush(FERRY_COLOR))
        for s, e in self.crossings:
            x0 = r.left() + w * s / 1440
            x1 = r.left() + w * e / 1440
            p.drawRect(round(x0), r.top(), max(2, round(x1 - x0)), 3)
        p.end()


class Legend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.labels = []
        entries = [(ACT_COLOR[a], False, k) for a, k in
                   ((DRIVE, "col_drive"), (WORK, "col_work"), (AVAIL, "col_avail"),
                    (REST, "col_rest"), (UNKNOWN, "col_unknown"))]
        entries.append((QColor("#777777"), True, "legend_manual"))
        entries.append((FERRY_COLOR, False, "legend_ferry"))
        for color, dashed, key in entries:
            sw = QLabel()
            sw.setFixedSize(14, 14)
            style = f"border:1px dashed {color.name()};" if dashed else f"background:{color.name()};"
            sw.setStyleSheet(style + "border-radius:2px;")
            lab = QLabel()
            self.lay.addWidget(sw)
            self.lay.addWidget(lab)
            self.lay.addSpacing(10)
            self.labels.append((lab, key))
        self.lay.addStretch(1)

    def retranslate(self):
        for lab, key in self.labels:
            lab.setText(tr(key))


def dim(palette, share: float = 0.62) -> QColor:
    """Gedämpfte Schriftfarbe: Text mit dem Hintergrund gemischt.

    Die Qt-Rolle „mid" taugt dafür nicht – manche Themen legen sie fast weiß an,
    dann steht heller Text auf hellem Grund und ist nicht mehr zu lesen. Mischen
    führt dagegen in jedem Thema zu einer Farbe, die sich vom Hintergrund absetzt.
    """
    text = palette.color(QPalette.ColorRole.WindowText)
    back = palette.color(QPalette.ColorRole.Window)
    return QColor(round(text.red() * share + back.red() * (1 - share)),
                  round(text.green() * share + back.green() * (1 - share)),
                  round(text.blue() * share + back.blue() * (1 - share)))


def set_dim(widget, share: float = 0.62) -> None:
    """Setzt die gedämpfte Farbe am Widget – wirkt auch dort, wo kein Stylesheet greift."""
    pal = widget.palette()
    color = dim(pal, share)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        pal.setColor(role, color)
    widget.setPalette(pal)



class MonthCalendar(QCalendarWidget):
    """Monatsraster: Tage mit Daten fett, Lenkzeit als Fußbalken, Befunde hinterlegt.

    Die Farbe trägt die Aussage nie allein – zusätzlich steht ein Punkt in der Ecke.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setGridVisible(True)
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
        self.marks: dict[dt.date, str] = {}
        self.drive: dict[dt.date, int] = {}

    def set_data(self, marks: dict, drive: dict) -> None:
        self.marks, self.drive = marks, drive
        self.updateCells()

    def paintCell(self, painter, rect, date):
        day = dt.date(date.year(), date.month(), date.day())
        sev = self.marks.get(day)
        selected = day == self.selectedDate().toPython()
        if sev and not selected:
            painter.fillRect(rect, SEV_TINT[sev])
        if selected:
            painter.fillRect(rect, self.palette().highlight())
        painter.save()
        font = painter.font()
        font.setBold(day in self.drive)
        painter.setFont(font)
        if selected:
            color = self.palette().highlightedText().color()
        elif sev:
            color = SEV_COLOR[sev]
        elif date.month() != self.monthShown():
            color = dim(self.palette(), 0.45)
        else:
            color = self.palette().text().color()
        painter.setPen(QPen(color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(date.day()))
        if sev:
            painter.setBrush(QBrush(SEV_COLOR[sev]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(rect.right() - 7, rect.top() + 2, 5, 5))
        minutes = self.drive.get(day, 0)
        if minutes:
            painter.setBrush(QBrush(ACT_COLOR[DRIVE]))
            painter.setPen(Qt.PenStyle.NoPen)
            width = (rect.width() - 6) * min(minutes / 600, 1.0)
            painter.drawRect(QRectF(rect.left() + 3, rect.bottom() - 4, width, 2))
        painter.restore()


class Meter(QWidget):
    """Ein Wert gegen seine Grenze – lesbarer als ein Diagramm mit einem Balken."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = self.note = ""
        self.text = "–"
        self.share = 0.0
        self.bad = False
        self.setMinimumSize(150, 84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, title: str, text: str, share: float, note: str, bad: bool = False):
        self.title, self.text, self.share, self.note, self.bad = title, text, share, note, bad
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -6.5, -0.5)
        p.setPen(QPen(dim(pal)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 5, 5)
        small = QFont(self.font())
        small.setPointSizeF(small.pointSizeF() * 0.92)
        p.setFont(small)
        p.setPen(QPen(dim(pal)))
        p.drawText(QRectF(r.left() + 10, r.top() + 5, r.width() - 20, 18),
                   Qt.AlignmentFlag.AlignVCenter, self.title)
        big = QFont(self.font())
        big.setPointSizeF(big.pointSizeF() * 1.6)
        big.setBold(True)
        p.setFont(big)
        p.setPen(QPen(SEV_COLOR["violation"] if self.bad else pal.text().color()))
        p.drawText(QRectF(r.left() + 10, r.top() + 23, r.width() - 20, 26),
                   Qt.AlignmentFlag.AlignVCenter, self.text)
        track = r.width() - 20
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dim(pal, 0.18)))
        p.drawRoundedRect(QRectF(r.left() + 10, r.bottom() - 22, track, 6), 3, 3)
        p.setBrush(QBrush(SEV_COLOR["violation"] if self.bad else QColor("#256abf")))
        p.drawRoundedRect(QRectF(r.left() + 10, r.bottom() - 22,
                                 track * max(0.0, min(self.share, 1.0)), 6), 3, 3)
        p.setFont(small)
        p.setPen(QPen(dim(pal)))
        p.drawText(QRectF(r.left() + 10, r.bottom() - 15, track, 13),
                   Qt.AlignmentFlag.AlignVCenter, self.note)
        p.end()


class MeterRow(QWidget):
    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.meters = [Meter() for _ in range(count)]
        for m in self.meters:
            lay.addWidget(m)
        self.setMaximumHeight(94)


class SpeedChart(QWidget):
    """Geschwindigkeit über den Tag: eine Linie, die eingestellte Grenze, Überschreitungen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: list[int] = []
        self.limit = 90
        self.spans: list[tuple[int, int, int]] = []
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, series, limit, spans):
        self.series, self.limit, self.spans = series, limit, spans
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        left, right, top, bottom = 46, 10, 22, 26
        w = max(self.width() - left - right, 10)
        h = max(self.height() - top - bottom, 10)
        ymax = max(120, (max(self.series) // 30 + 1) * 30 if self.series else 120)
        small = QFont(self.font())
        small.setPointSizeF(small.pointSizeF() * 0.9)
        p.setFont(small)

        def X(sec):
            return left + w * sec / 86400

        def Y(kmh):
            return top + h * (1 - kmh / ymax)

        for kmh in range(0, ymax + 1, 30):
            p.setPen(QPen(dim(pal, 0.22), 1))
            p.drawLine(int(left), int(Y(kmh)), int(left + w), int(Y(kmh)))
            p.setPen(QPen(dim(pal)))
            p.drawText(QRectF(0, Y(kmh) - 8, left - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(kmh))
        for hour in range(0, 25, 2):
            p.setPen(QPen(dim(pal)))
            p.drawText(QRectF(X(hour * 3600) - 20, top + h + 4, 40, 14),
                       Qt.AlignmentFlag.AlignHCenter, str(hour))
        if not self.series:
            p.setPen(QPen(dim(pal)))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("speed_none"))
            p.end()
            return
        pen = QPen(SEV_COLOR["violation"], 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(int(left), int(Y(self.limit)), int(left + w), int(Y(self.limit)))
        p.drawText(QRectF(left + 6, Y(self.limit) - 15, 260, 13),
                   Qt.AlignmentFlag.AlignLeft, tr("speed_limit_line", limit=self.limit))

        # Je Bildpunkt den Höchstwert – 86400 Werte passen sonst nicht aufs Bild.
        # Lücken (nicht aufgezeichnet) trennen die Kurve, statt sie zu überbrücken.
        step = max(1, int(86400 / w))
        runs: list[list[tuple[float, float]]] = []
        for sec in range(0, 86400, step):
            chunk = [v for v in self.series[sec:sec + step] if v >= 0]
            if not chunk:
                runs.append([]) if runs and runs[-1] else None
                continue
            if not runs or not runs[-1]:
                runs.append([])
            runs[-1].append((X(sec), Y(max(chunk))))
        runs = [r for r in runs if len(r) > 1]
        for start, length, peak in self.spans:
            p.setPen(Qt.PenStyle.NoPen)
            tint = QColor(SEV_COLOR["violation"])
            tint.setAlpha(46)
            p.setBrush(QBrush(tint))
            p.drawRect(QRectF(X(start), top, max(X(start + length) - X(start), 2), h))
        area = QColor(ACT_COLOR[DRIVE])
        area.setAlpha(38)
        for run in runs:
            path = QPainterPath()
            path.moveTo(*run[0])
            for pt in run[1:]:
                path.lineTo(*pt)
            fill = QPainterPath(path)
            fill.lineTo(run[-1][0], Y(0))
            fill.lineTo(run[0][0], Y(0))
            fill.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.fillPath(fill, QBrush(area))
            p.setPen(QPen(ACT_COLOR[DRIVE], 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(SEV_COLOR["violation"]))
        for start, length, peak in self.spans:
            p.drawEllipse(QRectF(X(start + length / 2) - 3, Y(peak) - 3, 6, 6))
        p.end()


# Fundstellen für den Reiter „Restzeit“ – als Schlüssel, der Text kommt aus der
# jeweiligen Sprachdatei.
LEGAL_TEXT = {
    "drive_day": "legal_art6_1",
    "drive_week": "legal_art6_2",
    "drive_two": "legal_art6_3",
    "daily_rest": "legal_art8_2",
    "break": "legal_art7",
    "weekly_rest": "legal_art8_6",
}


def control_name(code: int) -> str:
    """ControlType: je ein Bit für Herunterladen, Ausdruck und Anzeige."""
    parts = [tr(key) for bit, key in ((0x80, "ctrl_card"), (0x40, "ctrl_vu"),
                                      (0x20, "ctrl_print"), (0x10, "ctrl_display"))
             if code & bit]
    return tr("ctrl_generic") + (" – " + ", ".join(parts) if parts else "")


def _table(cols: int, stretch: int | None = None) -> QTableWidget:
    """Tabelle; `stretch` ist die Spalte, die den freien Platz bekommt (Standard: letzte)."""
    t = QTableWidget(0, cols)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    h = t.horizontalHeader()
    if stretch is None:
        h.setStretchLastSection(True)
    else:
        h.setStretchLastSection(False)
        for c in range(cols):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == stretch
                                   else QHeaderView.ResizeMode.ResizeToContents)
    return t


def _blocks_text(blocks: str, days: int) -> str:
    """Welche Datenbereiche enthält die Datei (Kennungen aus dem Archivindex)."""
    names = {1: "blk_overview", 2: "blk_activities", 3: "blk_events", 4: "blk_speed",
             5: "blk_technical"}
    out, seen = [], set()
    for part in (blocks or "").split(","):
        if not part:
            continue
        key = names.get(int(part, 16) & 0x0F)
        if key and key not in seen:
            seen.add(key)
            out.append(tr(key) + (f" ({days})" if key == "blk_activities" and days else ""))
    return ", ".join(out) or "–"


def _item(text, align_right=False, color: QColor | None = None, bold=False) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    if align_right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color is not None:
        it.setForeground(QBrush(color))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    return it


# --------------------------------------------------------------------------- Hintergrund

class ReaderWorker(QThread):
    progress = Signal(int)
    finished_ok = Signal(bytes, list)
    failed = Signal(str)

    def __init__(self, reader: str):
        super().__init__()
        self.reader = reader

    def run(self):
        try:
            with PCSC() as ctx, ctx.connect(self.reader) as card:
                raw, warn = download_card(card, lambda a, b: self.progress.emit(int(100 * a / max(b, 1))))
            self.finished_ok.emit(raw, warn)
        except PCSCError as e:
            if e.no_service:
                self.failed.emit(tr("msg_pcsc_missing"))
            elif e.no_card:
                self.failed.emit(tr("msg_no_card"))
            else:
                self.failed.emit(tr("msg_read_fail", error=str(e)))
        except (CardError, OSError, ValueError) as e:
            self.failed.emit(tr("msg_read_fail", error=str(e)))


# --------------------------------------------------------------------------- Dialoge

class SettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle(tr("set_title"))
        lay = QFormLayout(self)
        self.unknown = QCheckBox(tr("set_unknown_rest"))
        self.unknown.setChecked(settings.value("unknown_as_rest", True, bool))
        self.arbzg = QCheckBox(tr("set_arbzg"))
        self.arbzg.setChecked(settings.value("check_arbzg", True, bool))
        self.ferry = QCheckBox(tr("set_ferry"))
        self.ferry.setChecked(settings.value("ferry_rule", True, bool))
        self.coverage = QCheckBox(tr("set_coverage"))
        self.coverage.setChecked(settings.value("check_coverage", True, bool))
        self.coverage_days = QSpinBox()
        self.coverage_days.setRange(1, 365)
        self.coverage_days.setValue(settings.value("coverage_days", 56, int))
        self.coverage.toggled.connect(self.coverage_days.setEnabled)
        self.coverage_days.setEnabled(self.coverage.isChecked())
        self.retention = QSpinBox()
        self.retention.setRange(1, 30)
        self.retention.setValue(settings.value("retention_years", 2, int))
        self.dir = QLineEdit(settings.value("archive_dir", default_archive_dir(), str))
        browse = QPushButton(tr("btn_browse"))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.dir, 1)
        row.addWidget(browse)
        lay.addRow(self.unknown)
        lay.addRow(self.arbzg)
        lay.addRow(self.ferry)
        lay.addRow(self.coverage)
        lay.addRow(tr("set_coverage_days"), self.coverage_days)
        lay.addRow(tr("set_retention"), self.retention)
        lay.addRow(tr("set_archive_dir"), row)
        note = QLabel(tr("set_restart"))
        note.setWordWrap(True)
        lay.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("set_archive_dir"), self.dir.text())
        if d:
            self.dir.setText(d)

    def accept(self):
        self.s.setValue("unknown_as_rest", self.unknown.isChecked())
        self.s.setValue("check_arbzg", self.arbzg.isChecked())
        self.s.setValue("ferry_rule", self.ferry.isChecked())
        self.s.setValue("check_coverage", self.coverage.isChecked())
        self.s.setValue("coverage_days", self.coverage_days.value())
        self.s.setValue("retention_years", self.retention.value())
        self.s.setValue("archive_dir", self.dir.text())
        super().accept()


class AccessDialog(QDialog):
    """Archiv ▸ Zugang: Verschlüsselung ein- und ausschalten, Passwort, Selbstsperre."""

    def __init__(self, parent, archive, settings: QSettings):
        super().__init__(parent)
        self.archive = archive
        self.s = settings
        self.setWindowTitle(tr("act_access"))
        lay = QVBoxLayout(self)
        note = QLabel(tr("access_intro"))
        note.setWordWrap(True)
        lay.addWidget(note)

        box = QGroupBox(tr("access_group"))
        gl = QVBoxLayout(box)
        self.off = QRadioButton(tr("access_off"))
        self.on = QRadioButton(tr("access_on"))
        if not crypto_available():
            self.on.setEnabled(False)
            missing = QLabel(tr("access_missing"))
            missing.setWordWrap(True)
            missing.setStyleSheet(f"color:{SEV_COLOR['warning'].name()};")
            gl.addWidget(missing)
        enabled = archive.vault.enabled
        (self.on if enabled else self.off).setChecked(True)
        gl.addWidget(self.off)
        gl.addWidget(self.on)
        form = QFormLayout()
        self.pw1 = QLineEdit()
        self.pw2 = QLineEdit()
        for e in (self.pw1, self.pw2):
            e.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr("access_password"), self.pw1)
        form.addRow(tr("access_repeat"), self.pw2)
        gl.addLayout(form)
        self.warn = QLabel(tr("access_warning"))
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color:{SEV_COLOR['warning'].name()};")
        gl.addWidget(self.warn)
        lay.addWidget(box)

        timer_box = QGroupBox(tr("access_timer_group"))
        tl = QFormLayout(timer_box)
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 240)
        self.minutes.setSpecialValueText(tr("access_timer_off"))
        self.minutes.setSuffix(" min")
        self.minutes.setValue(settings.value("lock_minutes", 15, int))
        tl.addRow(tr("access_timer"), self.minutes)
        self.at_start = QCheckBox(tr("access_lock_at_start"))
        self.at_start.setChecked(settings.value("lock_at_start", False, bool))
        tl.addRow(self.at_start)
        lay.addWidget(timer_box)

        row = QHBoxLayout()
        self.btn_recovery = QPushButton(tr("access_new_recovery"))
        self.btn_recovery.clicked.connect(self._new_recovery)
        self.btn_recovery.setEnabled(enabled and archive.vault.unlocked)
        row.addWidget(self.btn_recovery)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel(tr("access_hint"))
        hint.setWordWrap(True)
        set_dim(hint)
        lay.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for r in (self.off, self.on):
            r.toggled.connect(self._update)
        self._update()

    def _update(self) -> None:
        turning_on = self.on.isChecked() and not self.archive.vault.enabled
        for e in (self.pw1, self.pw2):
            e.setEnabled(turning_on)
        self.warn.setVisible(turning_on)

    def _new_recovery(self) -> None:
        try:
            key = self.archive.vault.new_recovery_key()
        except VaultError as e:
            QMessageBox.critical(self, tr("act_access"), str(e))
            return
        self._show_recovery(key)

    def _show_recovery(self, key: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("recovery_title"))
        lay = QVBoxLayout(dlg)
        text = QLabel(tr("recovery_text"))
        text.setWordWrap(True)
        lay.addWidget(text)
        field = QLineEdit(key)
        field.setReadOnly(True)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(font.pointSizeF() * 1.4)
        field.setFont(font)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(field)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = bb.addButton(tr("btn_copy"), QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(key))
        save = bb.addButton(tr("btn_save"), QDialogButtonBox.ButtonRole.ActionRole)

        def store():
            fn, _ = QFileDialog.getSaveFileName(dlg, tr("btn_save"),
                                                "TachoArchiv-Wiederherstellung.txt", "Text (*.txt)")
            if fn:
                Path(fn).write_text(tr("recovery_file", key=key, date=fmt_dt(dt.datetime.now(UTC))),
                                    encoding="utf-8")

        save.clicked.connect(store)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        dlg.exec()

    def accept(self) -> None:
        self.s.setValue("lock_minutes", self.minutes.value())
        self.s.setValue("lock_at_start", self.at_start.isChecked())
        vault = self.archive.vault
        if self.on.isChecked() and not vault.enabled:
            if self.pw1.text() != self.pw2.text():
                QMessageBox.warning(self, tr("act_access"), tr("msg_password_mismatch"))
                return
            if len(self.pw1.text()) < 8:
                QMessageBox.warning(self, tr("act_access"), tr("msg_password_short"))
                return
            if QMessageBox.question(self, tr("act_access"), tr("ask_protect")) != \
                    QMessageBox.StandardButton.Yes:
                return
            try:
                key = self.archive.protect(self.pw1.text())
            except (VaultError, OSError) as e:
                QMessageBox.critical(self, tr("act_access"), str(e))
                return
            self._show_recovery(key)
        elif self.off.isChecked() and vault.enabled:
            if QMessageBox.question(self, tr("act_access"), tr("ask_unprotect")) != \
                    QMessageBox.StandardButton.Yes:
                return
            try:
                self.archive.unprotect()
            except (VaultError, OSError) as e:
                QMessageBox.critical(self, tr("act_access"), str(e))
                return
        super().accept()


class ExportDialog(QDialog):
    """Umfang, Zeitraum und Sprache des PDF-Berichts.

    Die Sprache ist hier bewusst getrennt von der Oberfläche: wer den Bericht
    erstellt, spricht nicht zwangsläufig die Sprache dessen, der ihn lesen muss.
    """

    def __init__(self, parent, settings: QSettings, periods, period_index: int, surname: str):
        super().__init__(parent)
        self.surname = surname
        self.setWindowTitle(tr("act_export_pdf"))
        lay = QVBoxLayout(self)

        box = QGroupBox(tr("pdf_scope"))
        bl = QVBoxLayout(box)
        self.full = QRadioButton(tr("pdf_full"))
        self.only = QRadioButton(tr("pdf_only"))
        self.warn = QCheckBox(tr("pdf_with_warnings"))
        last = settings.value("pdf_scope", "full", str)
        (self.only if last == "violations" else self.full).setChecked(True)
        self.warn.setChecked(settings.value("pdf_warnings", False, bool))
        for button, key in ((self.full, "pdf_full_note"), (self.only, "pdf_only_note")):
            bl.addWidget(button)
            note = QLabel(tr(key))
            note.setWordWrap(True)
            set_dim(note)
            note.setContentsMargins(22, 0, 0, 6)
            bl.addWidget(note)
            if button is self.only:
                self.warn.setContentsMargins(22, 0, 0, 0)
                bl.addWidget(self.warn)
        lay.addWidget(box)

        box2 = QGroupBox(tr("pdf_group_period"))
        form = QFormLayout(box2)
        self.period = QComboBox()
        for label, days in periods:
            self.period.addItem(label, days)
        self.period.setCurrentIndex(period_index)
        form.addRow(tr("lbl_period"), self.period)
        self.language = QComboBox()
        for code in i18n.LANGUAGES:
            self.language.addItem(i18n.language_label(code), code)
        wanted = settings.value("pdf_language", i18n.language(), str)
        codes = list(i18n.LANGUAGES)
        self.language.setCurrentIndex(codes.index(wanted) if wanted in codes
                                      else codes.index(i18n.language()))
        form.addRow(tr("pdf_language"), self.language)
        note = QLabel(tr("pdf_note_language", current=i18n.iso3(i18n.language())))
        note.setWordWrap(True)
        set_dim(note)
        form.addRow(note)
        lay.addWidget(box2)

        self.file_label = QLabel()
        set_dim(self.file_label)
        lay.addWidget(self.file_label)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText(tr("btn_save"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.only.toggled.connect(self._update)
        self.language.currentIndexChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        self.warn.setEnabled(self.only.isChecked())
        self.file_label.setText(tr("pdf_file", name=self.suggested_name()))

    def suggested_name(self) -> str:
        code = i18n.iso3(self.language.currentData())
        kind = "Verstoesse" if self.only.isChecked() else "Auswertung"
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", self.surname or "Fahrer").strip("_") or "Fahrer"
        return f"{kind}_{name}_{dt.date.today():%Y%m%d}_{code}.pdf"

    def result_values(self) -> dict:
        return {"index": self.period.currentIndex(),
                "scope": "violations" if self.only.isChecked() else "full",
                "with_warnings": self.warn.isChecked() and self.only.isChecked(),
                "days": self.period.currentData(),
                "period_label": self.period.currentText(),
                "language": self.language.currentData(),
                "name": self.suggested_name()}


def default_archive_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return str(Path(base) / "archiv")


# --------------------------------------------------------------------------- Hauptfenster

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        i18n.set_language(self.settings.value("language", _system_language(), str))
        base = self.settings.value("archive_dir", default_archive_dir(), str)
        self.archive = Archive(base, Vault(base))
        self.selected_day: dt.date | None = None
        self.marks: dict[dt.date, str] = {}
        self.crossing_days: dict[dt.date, list] = {}
        self.speed_blocks = []
        self._last_action = dt.datetime.now(UTC)
        self.card = None
        self.result: Result | None = None
        self.current: str | None = None
        self.current_vehicle: str | None = None
        self.worker: ReaderWorker | None = None
        self.integrity: dict[str, bool] = {}
        self.signatures: dict = {}
        self._status_key: str | None = None      # dauerhafte Meldung, sprachabhängig
        self._status_text = ""
        self.resize(1280, 820)
        self.setWindowIcon(QIcon.fromTheme(APP_ID))
        self._build()
        self.retranslate()
        self.refresh_readers()
        # Ein geschütztes Archiv bleibt zu, bis jemand das Passwort kennt.
        if self.archive.vault.enabled and self.settings.value("lock_at_start", False, bool):
            self._show_lock()
        elif self.archive.vault.enabled:
            self.ask_unlock()
        else:
            self.reload_drivers()
            self.reload_vehicles()
        QApplication.instance().installEventFilter(self)
        self._lock_timer = QTimer(self)
        self._lock_timer.timeout.connect(self._check_autolock)
        self._lock_timer.start(30000)
        self._show_lock()

    # ---------------------------------------------------------------- Aufbau
    def _action(self, icon, slot) -> QAction:
        a = QAction(self)
        if icon is not None:
            a.setIcon(icon)
        a.triggered.connect(slot)
        return a

    def _build(self):
        tb = QToolBar()
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.a_read = self._action(QIcon.fromTheme("media-flash"), self.read_card)
        self.a_import = self._action(QIcon.fromTheme("document-open"), self.import_files)
        self.a_pdf = self._action(QIcon.fromTheme("document-print"), self.export_pdf)
        self.a_csv = self._action(QIcon.fromTheme("document-save"), self.export_csv)
        self.a_demo = self._action(None, self.load_demo)
        self.a_verify = self._action(None, self.verify_archive)
        self.a_folder = self._action(None, self.open_folder)
        self.a_settings = self._action(QIcon.fromTheme("preferences-system"), self.open_settings)
        self.a_about = self._action(None, self.about)
        self.a_diag = self._action(None, self.card_diagnosis)
        self.a_access = self._action(None, self.open_access)
        self.a_signatures = self._action(None, self.check_signatures)
        self.a_certdiag = self._action(None, self.certificate_diagnosis)
        self.a_manual = self._action(None, self.open_manual)
        self.a_read.setShortcut("Ctrl+R")
        self.a_import.setShortcut("Ctrl+O")
        self.a_pdf.setShortcut("Ctrl+P")
        for a in (self.a_read, self.a_import):
            tb.addAction(a)
        self.reader_label = QLabel()
        self.reader_combo = QComboBox()
        self.reader_combo.setMinimumWidth(240)
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(self.refresh_readers)
        tb.addSeparator()
        tb.addWidget(self.reader_label)
        tb.addWidget(self.reader_combo)
        tb.addWidget(self.btn_refresh)
        tb.addSeparator()
        tb.addAction(self.a_pdf)
        tb.addAction(self.a_csv)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        for code in i18n.LANGUAGES:
            self.lang_combo.addItem(i18n.language_label(code), code)
        self.lang_combo.setCurrentIndex(list(i18n.LANGUAGES).index(i18n.language()))
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        tb.addWidget(self.lang_label)
        tb.addWidget(self.lang_combo)

        self.m_file = self.menuBar().addMenu("")
        for a in (self.a_read, self.a_import, self.a_demo):
            self.m_file.addAction(a)
        self.m_file.addSeparator()
        for a in (self.a_pdf, self.a_csv):
            self.m_file.addAction(a)
        self.m_file.addSeparator()
        self.a_quit = self._action(None, self.close)
        self.a_quit.setShortcut("Ctrl+Q")
        self.m_file.addAction(self.a_quit)
        self.m_archive = self.menuBar().addMenu("")
        for a in (self.a_verify, self.a_signatures, self.a_folder, self.a_access,
                  self.a_settings):
            self.m_archive.addAction(a)
        self.m_help = self.menuBar().addMenu("")
        self.m_help.addAction(self.a_manual)
        self.m_help.addSeparator()
        self.m_help.addAction(self.a_diag)
        self.m_help.addAction(self.a_certdiag)
        self.m_help.addAction(self.a_about)

        split = QSplitter()
        split.addWidget(self._build_left())

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 6, 6, 6)
        head = QHBoxLayout()
        self.title = QLabel()
        tf = self.title.font()
        tf.setPointSizeF(tf.pointSizeF() * 1.5)
        tf.setBold(True)
        self.title.setFont(tf)
        self.summary = QLabel()
        self.period_label = QLabel()
        self.period_combo = QComboBox()
        self.period_combo.currentIndexChanged.connect(self.refresh_views)
        head.addWidget(self.title)
        head.addSpacing(16)
        head.addWidget(self.summary, 1)
        head.addWidget(self.period_label)
        head.addWidget(self.period_combo)
        rl.addLayout(head)

        self.tabs = QTabWidget()
        for build in (self._build_day, self._build_days, self._build_violations,
                      self._build_warnings, self._build_remaining, self._build_shifts,
                      self._build_weeks, self._build_vehicle, self._build_events,
                      self._build_archive):
            self.tabs.addTab(build(), "")
        rl.addWidget(self.tabs, 1)

        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 1110])
        self.setCentralWidget(split)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.lock_state = QLabel()
        self.statusBar().addPermanentWidget(self.lock_state)
        self.statusBar().addPermanentWidget(self.progress)

    # ---------------------------------------------------------------- Linke Seite
    def _build_left(self) -> QWidget:
        """Oben der Kalender, unten die Kartenübersicht."""
        left = QSplitter(Qt.Orientation.Vertical)
        self.calendar = MonthCalendar()
        self.calendar.setMinimumHeight(250)
        self.calendar.clicked.connect(self.day_selected)
        self.calendar.activated.connect(self.day_selected)
        left.addWidget(self.calendar)

        box = QWidget()
        ov = QVBoxLayout(box)
        ov.setContentsMargins(8, 6, 6, 6)
        self.overview_head = QLabel()
        f = self.overview_head.font()
        f.setBold(True)
        self.overview_head.setFont(f)
        ov.addWidget(self.overview_head)
        self.info_form = QFormLayout()
        self.info_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.info_labels = {}
        for key in ("f_name", "f_birth", "f_card", "f_nation", "f_authority", "f_valid",
                    "f_licence", "f_generation", "f_last_download", "f_data_range", "f_coverage",
                    "f_findings"):
            val = QLabel("–")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
            self.info_labels[key] = val
            self.info_form.addRow(QLabel(), val)
        ov.addLayout(self.info_form)
        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)
        ov.addWidget(self.empty_label)
        ov.addStretch(1)
        self.disclaimer = QLabel()
        self.disclaimer.setWordWrap(True)
        set_dim(self.disclaimer)
        ov.addWidget(self.disclaimer)
        scroll = QScrollArea()
        scroll.setWidget(box)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left.addWidget(scroll)
        left.setSizes([300, 470])
        return left

    # ---------------------------------------------------------------- Reiter
    def _build_day(self) -> QWidget:
        """Der im Kalender gewählte Tag."""
        page = QWidget()
        lay = QVBoxLayout(page)
        head = QHBoxLayout()
        self.day_title = QLabel()
        f = self.day_title.font()
        f.setPointSizeF(f.pointSizeF() * 1.3)
        f.setBold(True)
        self.day_title.setFont(f)
        self.day_badge = QLabel()
        head.addWidget(self.day_title)
        head.addWidget(self.day_badge)
        head.addStretch(1)
        lay.addLayout(head)
        self.day_legend = Legend()
        lay.addWidget(self.day_legend)
        self.day_bar = DayBar([], ())
        self.day_bar.setMinimumHeight(60)
        lay.addWidget(self.day_bar)
        self.day_meters = MeterRow(4)
        lay.addWidget(self.day_meters)
        self.day_findings_head = QLabel()
        lay.addWidget(self.day_findings_head)
        self.t_day_findings = _table(4)
        self.t_day_findings.setMaximumHeight(170)
        lay.addWidget(self.t_day_findings)
        self.day_shifts_head = QLabel()
        lay.addWidget(self.day_shifts_head)
        self.t_day_shifts = _table(7)
        lay.addWidget(self.t_day_shifts, 1)
        return page

    def _build_days(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.legend = Legend()
        lay.addWidget(self.legend)
        self.t_days = _table(8)
        self.t_days.itemSelectionChanged.connect(self._day_row_selected)
        lay.addWidget(self.t_days)
        return page

    def _build_violations(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.violations_note = QLabel()
        set_dim(self.violations_note)
        self.violations_note.setWordWrap(True)
        lay.addWidget(self.violations_note)
        self.t_findings = _table(4)
        lay.addWidget(self.t_findings, 1)
        return page

    def _build_warnings(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.warnings_note = QLabel()
        set_dim(self.warnings_note)
        self.warnings_note.setWordWrap(True)
        lay.addWidget(self.warnings_note)
        self.t_warnings = _table(4)
        lay.addWidget(self.t_warnings, 1)
        return page

    def _build_remaining(self) -> QWidget:
        """Prognose der noch zulässigen Zeiten."""
        page = QWidget()
        lay = QVBoxLayout(page)
        self.remaining_note = QLabel()
        set_dim(self.remaining_note)
        self.remaining_note.setWordWrap(True)
        lay.addWidget(self.remaining_note)
        self.remaining_top = MeterRow(3)
        self.remaining_bottom = MeterRow(3)
        lay.addWidget(self.remaining_top)
        lay.addWidget(self.remaining_bottom)
        self.remaining_head = QLabel()
        lay.addWidget(self.remaining_head)
        self.t_remaining = _table(3, stretch=2)
        lay.addWidget(self.t_remaining, 1)
        return page

    def _build_shifts(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.shift_meters = MeterRow(4)
        lay.addWidget(self.shift_meters)
        self.t_shifts = _table(9)
        lay.addWidget(self.t_shifts, 1)
        return page

    def _build_weeks(self) -> QWidget:
        self.t_weeks = _table(6, stretch=0)
        return self.t_weeks

    def _build_events(self) -> QWidget:
        """Drei waagerechte Felder: Fehler, Kontrollen, Sonstiges."""
        split = QSplitter(Qt.Orientation.Vertical)
        self.event_heads = []
        self.event_tables = []
        for _ in range(3):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 2, 0, 2)
            head = QLabel()
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            table = _table(4)
            lay.addWidget(head)
            lay.addWidget(table, 1)
            self.event_heads.append(head)
            self.event_tables.append(table)
            split.addWidget(box)
        split.setSizes([220, 160, 260])
        return split

    def _build_vehicle(self) -> QWidget:
        """Alles Fahrzeugbezogene, mit der Geschwindigkeit als eigenem Unterreiter."""
        self.vehicle_tabs = QTabWidget()

        page = QWidget()
        lay = QVBoxLayout(page)
        self.veh_title = QLabel()
        vf = self.veh_title.font()
        vf.setPointSizeF(vf.pointSizeF() * 1.25)
        vf.setBold(True)
        self.veh_title.setFont(vf)
        lay.addWidget(self.veh_title)
        self.veh_form = QFormLayout()
        self.veh_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.veh_labels = {}
        for key in ("f_vin", "f_plate", "f_vu_generation", "f_company", "f_vu_last"):
            val = QLabel("–")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.veh_form.addRow(QLabel(), val)
            self.veh_labels[key] = val
        lay.addLayout(self.veh_form)
        self.vu_head = QLabel()
        lay.addWidget(self.vu_head)
        self.t_vu = _table(7, stretch=3)
        lay.addWidget(self.t_vu, 1)
        self.vehicle_tabs.addTab(page, "")

        speed = QWidget()
        sl = QVBoxLayout(speed)
        bar = QHBoxLayout()
        self.speed_day_label = QLabel()
        self.speed_day = QComboBox()
        self.speed_day.setMinimumWidth(140)
        self.speed_day.currentIndexChanged.connect(self.refresh_speed)
        self.speed_limit_label = QLabel()
        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(30, 130)
        self.speed_limit.setSuffix(" km/h")
        self.speed_limit.setValue(self.settings.value("speed_limit", 90, int))
        self.speed_limit.valueChanged.connect(self._speed_limit_changed)
        self.btn_speed_csv = QPushButton()
        self.btn_speed_csv.clicked.connect(self.export_speed_csv)
        bar.addWidget(self.speed_day_label)
        bar.addWidget(self.speed_day)
        bar.addSpacing(16)
        bar.addWidget(self.speed_limit_label)
        bar.addWidget(self.speed_limit)
        bar.addStretch(1)
        bar.addWidget(self.btn_speed_csv)
        sl.addLayout(bar)
        self.speed_meters = MeterRow(4)
        sl.addWidget(self.speed_meters)
        self.speed_chart = SpeedChart()
        sl.addWidget(self.speed_chart, 2)
        tables = QSplitter()
        for attr, cols in (("t_overspeed", 4), ("t_speed_hours", 5)):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 4, 0)
            head = QLabel()
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            table = _table(cols, stretch=0)
            bl.addWidget(head)
            bl.addWidget(table, 1)
            setattr(self, attr, table)
            setattr(self, attr + "_head", head)
            tables.addWidget(box)
        tables.setSizes([440, 660])
        sl.addWidget(tables, 3)
        self.vehicle_tabs.addTab(speed, "")

        # Fahrzeuge, die auf der Fahrerkarte stehen – etwas anderes als das Archiv
        self.t_vehicles = _table(6)
        self.vehicle_tabs.addTab(self.t_vehicles, "")
        return self.vehicle_tabs

    def _build_archive(self) -> QWidget:
        """Fahrer- und Fahrzeugliste liegen hier, weil sie personenbezogen sind."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.lock_label = QLabel()
        self.lock_label.setWordWrap(True)
        self.btn_lock = QPushButton()
        self.btn_lock.clicked.connect(self.toggle_lock)
        bar.addWidget(self.lock_label, 1)
        bar.addWidget(self.btn_lock)
        lay.addLayout(bar)

        inner = QSplitter()
        self.driver_list = QListWidget()
        self.driver_list.currentItemChanged.connect(self.driver_selected)
        self.vehicle_list = QListWidget()
        self.vehicle_list.currentItemChanged.connect(self.vehicle_selected)
        self.side = QTabWidget()
        self.side.addTab(self.driver_list, "")
        self.side.addTab(self.vehicle_list, "")
        inner.addWidget(self.side)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(6, 0, 0, 0)
        self.archive_head = QLabel()
        f = self.archive_head.font()
        f.setBold(True)
        self.archive_head.setFont(f)
        bl.addWidget(self.archive_head)
        self.t_archive = _table(6)
        bl.addWidget(self.t_archive, 1)
        inner.addWidget(box)
        inner.setSizes([300, 900])
        lay.addWidget(inner, 1)
        return page


    def retranslate(self):
        self.setWindowTitle(tr("app_title"))
        for a, k in ((self.a_read, "act_read_card"), (self.a_import, "act_import"), (self.a_pdf, "act_export_pdf"),
                     (self.a_csv, "act_export_csv"), (self.a_demo, "act_demo"), (self.a_verify, "act_verify"),
                     (self.a_folder, "act_open_folder"), (self.a_settings, "act_settings"),
                     (self.a_about, "act_about"), (self.a_diag, "act_diagnosis"),
                     (self.a_access, "act_access"),
                     (self.a_signatures, "act_check_signatures"),
                     (self.a_certdiag, "act_certdiag"),
                     (self.a_manual, "act_manual")):
            a.setText(tr(k))
        self.a_quit.setText(tr("act_quit"))
        self.m_file.setTitle(tr("menu_file"))
        self.m_archive.setTitle(tr("tab_archive"))
        self.m_help.setTitle(tr("menu_help"))
        self.reader_label.setText(tr("lbl_reader") + " ")
        self.btn_refresh.setText(tr("btn_refresh"))
        self.lang_label.setText(tr("lbl_language") + " ")
        self.side.setTabText(0, tr("drivers"))
        self.side.setTabText(1, tr("vehicles"))
        self.t_vu.setHorizontalHeaderLabels([tr(k) for k in (
            "col_imported", "col_vu_downloaded", "col_period", "col_content", "col_retention",
            "col_integrity", "col_file")])
        for row, key in enumerate(self.veh_labels):
            self.veh_form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().setText(tr(key))
        self.period_label.setText(tr("lbl_period") + " ")
        idx = max(0, self.period_combo.currentIndex())
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        control = self.settings.value("coverage_days", 56, int)
        for key, days in PERIODS:
            if key == "period_control":
                self.period_combo.addItem(tr(key, days=control), control)
            else:
                self.period_combo.addItem(tr(key), days)
        self.period_combo.setCurrentIndex(idx)
        self.period_combo.blockSignals(False)
        for i, key in enumerate(("tab_day", "tab_days", "tab_violations", "tab_warnings",
                                 "tab_remaining", "tab_shifts", "tab_weeks", "tab_vehicle",
                                 "tab_events", "tab_archive")):
            self.tabs.setTabText(i, tr(key))
        for i, key in enumerate(("tab_vu_files", "tab_speed", "tab_card_vehicles")):
            self.vehicle_tabs.setTabText(i, tr(key))
        for row, key in enumerate(self.info_labels):
            self.info_form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().setText(tr(key))
        self.overview_head.setText(tr("head_card"))
        self.legend.retranslate()
        self.day_legend.retranslate()
        self._adjust_rows()
        self._show_status()
        self.disclaimer.setText(tr("disclaimer"))
        self.empty_label.setText(tr("msg_empty"))
        self.day_findings_head.setText(tr("head_day_findings"))
        self.day_shifts_head.setText(tr("head_day_shifts"))
        self.violations_note.setText(tr("note_violations"))
        self.warnings_note.setText(tr("note_warnings"))
        self.remaining_head.setText(tr("head_remaining"))
        self.vu_head.setText(tr("head_vu_files"))
        self.archive_head.setText(tr("head_archive_files"))
        self.speed_day_label.setText(tr("lbl_speed_day") + " ")
        self.speed_limit_label.setText(tr("lbl_speed_limit") + " ")
        self.btn_speed_csv.setText(tr("btn_speed_csv"))
        self.t_overspeed_head.setText(tr("head_overspeed"))
        self.t_speed_hours_head.setText(tr("head_speed_hours"))
        for head, key in zip(self.event_heads, ("head_ev_faults", "head_ev_controls", "head_ev_other")):
            head.setProperty("key", key)
        self.t_days.setHorizontalHeaderLabels([tr(k) for k in (
            "col_date", "col_timeline", "col_drive", "col_work", "col_avail", "col_rest", "col_unknown", "col_km")])
        for t in (self.t_findings, self.t_warnings, self.t_day_findings):
            t.setHorizontalHeaderLabels([tr(k) for k in (
                "col_time", "col_severity", "col_legal", "col_message")])
        self.t_weeks.setHorizontalHeaderLabels([tr(k) for k in (
            "col_week", "col_drive", "col_work", "col_avail", "col_rest", "col_worktime")])
        self.t_day_shifts.setHorizontalHeaderLabels([tr(k) for k in (
            "col_from", "col_to", "col_duration", "col_drive", "col_work", "col_rest_after",
            "col_rest_kind")])
        self.t_shifts.setHorizontalHeaderLabels([tr(k) for k in (
            "col_from", "col_to", "col_duration", "col_drive", "col_work", "col_avail",
            "col_rest_after", "col_rest_kind", "col_severity")])
        self.t_remaining.setHorizontalHeaderLabels([tr(k) for k in (
            "col_limit", "col_used", "col_legal")])
        self.t_vehicles.setHorizontalHeaderLabels([tr(k) for k in (
            "col_vehicle", "col_from", "col_to", "col_odo_start", "col_odo_end", "col_vin")])
        for i, t in enumerate(self.event_tables):
            keys = (("col_control", "col_time", "col_period", "col_control_card") if i == 1
                    else ("col_event", "col_from", "col_to", "col_vehicle"))
            t.setHorizontalHeaderLabels([tr(k) for k in keys])
        self.t_overspeed.setHorizontalHeaderLabels([tr(k) for k in (
            "col_from", "col_duration", "col_peak", "col_average")])
        self.t_speed_hours.setHorizontalHeaderLabels([tr(k) for k in (
            "col_hour", "col_average", "col_peak", "col_over_limit", "col_distance")])
        self.t_archive.setHorizontalHeaderLabels([tr(k) for k in (
            "col_imported", "col_source", "col_retention", "col_integrity", "col_signature",
            "col_file")])
        self.calendar.setLocale(QLocale(i18n.language()))
        if self.reader_combo.count() == 1 and not self.reader_combo.itemData(0):
            self.reader_combo.setItemText(0, tr("lbl_no_reader"))
        self._show_lock()
        self.refresh_views()
        self.refresh_speed()
        self.refresh_views()

    # ---------------------------------------------------------------- Fahrzeuge
    def reload_vehicles(self, select: str | None = None) -> None:
        if not self.archive.vault.ready:
            self.vehicle_list.clear()
            return
        select = select or self.current_vehicle
        self.vehicle_list.blockSignals(True)
        self.vehicle_list.clear()
        target = None
        for v in self.archive.vehicles():
            plate = " ".join(p for p in (v["nation"], v["registration"]) if p)
            it = QListWidgetItem(f"{plate or v['vin']}\n{v['vin']}")
            it.setData(Qt.ItemDataRole.UserRole, v["vin"])
            self.vehicle_list.addItem(it)
            if v["vin"] == select:
                target = it
        self.vehicle_list.blockSignals(False)
        if target is None and self.vehicle_list.count():
            target = self.vehicle_list.item(0)
        if target is not None:
            self.vehicle_list.setCurrentItem(target)
            if self.side.currentIndex() == 1:
                self.vehicle_selected(target, None)

    def vehicle_selected(self, item, _prev) -> None:
        if item is None:
            self.veh_title.setText("–")
            for lab in self.veh_labels.values():
                lab.setText("–")
            self.t_vu.setRowCount(0)
            return
        vin = item.data(Qt.ItemDataRole.UserRole)
        self.current_vehicle = vin
        info = next((v for v in self.archive.vehicles() if v["vin"] == vin), None)
        dls = list(reversed(self.archive.vu_downloads(vin)))
        plate = " ".join(p for p in (info["nation"], info["registration"]) if p) if info else ""
        self.veh_title.setText(f"{plate or vin}   ({tr('f_vu_count', count=len(dls))})")
        newest = max((d.downloaded_at for d in dls if d.downloaded_at), default="")
        last = "–"
        overdue = False
        if newest:
            when = dt.datetime.fromisoformat(newest)
            days = (dt.datetime.now(UTC) - when).days
            last = fmt_dt(when)
            overdue = days > 90
            if overdue:
                last += "  " + tr("vu_due", count=days)
        self.veh_labels["f_vin"].setText(vin)
        self.veh_labels["f_plate"].setText(plate or "–")
        self.veh_labels["f_vu_generation"].setText(
            tr("gen_2" if info and info["generation"] == 2 else "gen_1") if info else "–")
        self.veh_labels["f_company"].setText(next((d.company for d in dls if d.company), "–"))
        self.veh_labels["f_vu_last"].setText(last)
        self.veh_labels["f_vu_last"].setStyleSheet(
            f"color:{SEV_COLOR['warning'].name()};" if overdue else "")
        self.load_speed()

        years = self.settings.value("retention_years", 2, int)
        self.t_vu.setRowCount(len(dls))
        for r, d in enumerate(dls):
            period = "–"
            if d.period_begin and d.period_end:
                period = (f"{fmt_date(dt.datetime.fromisoformat(d.period_begin))} – "
                          f"{fmt_date(dt.datetime.fromisoformat(d.period_end))}")
            try:
                keep = d.imported_at.replace(year=d.imported_at.year + years)
            except ValueError:
                keep = d.imported_at + dt.timedelta(days=365 * years)
            state = self.integrity.get(f"v{d.id}")
            self.t_vu.setItem(r, 0, _item(fmt_dt(d.imported_at)))
            self.t_vu.setItem(r, 1, _item(fmt_dt(dt.datetime.fromisoformat(d.downloaded_at))
                                          if d.downloaded_at else "–"))
            self.t_vu.setItem(r, 2, _item(period))
            self.t_vu.setItem(r, 3, _item(_blocks_text(d.blocks, d.days)))
            self.t_vu.setItem(r, 4, _item(fmt_date(keep)))
            if state is None:
                self.t_vu.setItem(r, 5, _item(tr("integrity_unchecked")))
            else:
                self.t_vu.setItem(r, 5, _item(tr("integrity_ok" if state else "integrity_bad"),
                                              color=None if state else SEV_COLOR["violation"]))
            self.t_vu.setItem(r, 6, _item(d.path.name))

    def _coverage_text(self, res: Result) -> str:
        """Abdeckung des Nachweiszeitraums für die Übersicht."""
        days = self.settings.value("coverage_days", 56, int)
        covered, total, first = coverage(res.data_start, res.data_end,
                                         dt.datetime.now(UTC), days)
        if first is None:
            return tr("coverage_none")
        return tr("coverage_value", covered=covered, total=total, date=fmt_date(first))

    def _adjust_rows(self) -> None:
        """Nastaliq (Urdu) und arabische Schrift brauchen mehr Zeilenhöhe als Latein.

        Qt bemisst die Zeilenhöhe an der eingestellten Schrift, nicht an der
        tatsächlich eingesetzten Ersatzschrift – ohne Zuschlag werden die
        Unterlängen abgeschnitten.
        """
        height = self.fontMetrics().height() + (16 if i18n.is_rtl() else 6)
        for t in ((self.t_findings, self.t_warnings, self.t_weeks, self.t_vehicles,
                   self.t_shifts, self.t_remaining, self.t_day_findings, self.t_day_shifts,
                   self.t_archive, self.t_vu, self.t_overspeed, self.t_speed_hours)
                  + tuple(self.event_tables)):
            t.verticalHeader().setDefaultSectionSize(height)

    def _show_status(self, msecs: int = 0) -> None:
        text = tr(self._status_key) if self._status_key else self._status_text
        if text:
            self.statusBar().showMessage(text, msecs)

    def change_language(self, _):
        code = self.lang_combo.currentData()
        i18n.set_language(code)
        self.settings.setValue("language", code)
        install_qt_translations(code)
        _apply_direction(code)
        self.retranslate()

    # ---------------------------------------------------------------- Leser
    def refresh_readers(self):
        self.reader_combo.clear()
        readers = []
        try:
            with PCSC() as ctx:
                readers = ctx.readers()
        except PCSCError as e:
            if e.no_service:
                self._status_key = "msg_pcsc_missing"
            else:
                self._status_key, self._status_text = None, str(e)
            self._show_status()
        for r in readers:
            self.reader_combo.addItem(r, r)
        if not readers:
            self.reader_combo.addItem(tr("lbl_no_reader"), "")
        self.a_read.setEnabled(bool(readers))

    def read_card(self):
        reader = self.reader_combo.currentData()
        if not reader or (self.worker and self.worker.isRunning()):
            return
        self.a_read.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.worker = ReaderWorker(reader)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_card_read)
        self.worker.failed.connect(self._on_card_failed)
        self.worker.start()

    def _on_progress(self, pct):
        self.progress.setValue(pct)
        self.statusBar().showMessage(tr("msg_reading", pct=pct))

    def _done_reading(self):
        self.progress.hide()
        self.a_read.setEnabled(True)

    def _on_card_read(self, raw: bytes, warn: list):
        self._done_reading()
        try:
            dl, card = self.archive.add(raw, "card")
        except DuplicateError:
            self.statusBar().showMessage(tr("msg_duplicate", file="—"), 8000)
            return
        except (DddError, OSError) as e:
            QMessageBox.critical(self, tr("app_title"), tr("msg_read_fail", error=str(e)))
            return
        # Echte Warnungen (fehlende Dateien) als Dialog, Hinweise ohne Folgen nur
        # in der Statuszeile – sonst wirkt ein vollständiger Download wie ein Fehler.
        problems = [n.text for n in warn if n.severity != "info"]
        notes = [n.text for n in warn if n.severity == "info"]
        if problems:
            QMessageBox.warning(self, tr("app_title"), tr("msg_read_warnings", items="\n".join(problems)))
        msg = tr("msg_read_ok", file=dl.path.name)
        if notes:
            msg += "  " + tr("msg_read_note", items=" ".join(notes))
        self.statusBar().showMessage(msg, 30000)
        self.reload_drivers(select=dl.card_number)

    def _on_card_failed(self, msg: str):
        self._done_reading()
        QMessageBox.warning(self, tr("app_title"), msg)
        self.statusBar().showMessage(msg, 10000)

    # ---------------------------------------------------------------- Import
    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("act_import"), "", "DDD (*.ddd *.DDD *.c1b *.C1B *.v1b *.V1B *.v2b *.V2B *.tgd *.TGD);;* (*)")
        ok = 0
        last = last_vu = None
        errors = []
        for fn in files:
            name = os.path.basename(fn)
            try:
                raw = Path(fn).read_bytes()
                dl, _ = self.archive.add_any(raw, "file", name)
                ok += 1
                if isinstance(dl, VuDownload):
                    last_vu = dl.vin
                else:
                    last = dl.card_number
            except DuplicateError:
                errors.append(tr("msg_duplicate", file=name))
            except (DddError, VuError) as e:
                errors.append(tr("msg_import_fail", file=name, error=str(e)))
            except OSError as e:
                errors.append(tr("msg_import_fail", file=name, error=str(e)))
        if errors:
            QMessageBox.warning(self, tr("app_title"), "\n".join(errors))
        if ok:
            self.statusBar().showMessage(tr("msg_import_ok", count=ok), 8000)
            self.reload_drivers(select=last)
            self.reload_vehicles(select=last_vu)
            if last_vu and not last:
                self.side.setCurrentIndex(1)

    def load_demo(self):
        """Fahrerkarte und Fahrzeugdatei zum Vorführen – beides erfunden."""
        added = 0
        try:
            dl, _ = self.archive.add(build_demo(), "file", "demo.ddd")
            self.reload_drivers(select=dl.card_number)
            added += 1
        except DuplicateError:
            pass
        try:
            vu, _ = self.archive.add_vu(build_demo_vu(), "file", "demo-fahrzeug.ddd")
            self.reload_vehicles(select=vu.vin)
            added += 1
        except (DuplicateError, VuError):
            pass
        if not added:
            self.statusBar().showMessage(tr("msg_duplicate", file="demo.ddd"), 8000)

    # ---------------------------------------------------------------- Daten
    def reload_drivers(self, select: str | None = None):
        if not self.archive.vault.ready:
            self.driver_list.clear()
            self.card = self.result = None
            self.refresh_views()
            return
        select = select or self.current
        self.driver_list.blockSignals(True)
        self.driver_list.clear()
        target = None
        for d in self.archive.drivers():
            name = ", ".join(p for p in (d["surname"], d["firstnames"]) if p) or d["card_number"]
            it = QListWidgetItem(f"{name}\n{d['card_number']}")
            it.setData(Qt.ItemDataRole.UserRole, d["card_number"])
            self.driver_list.addItem(it)
            if d["card_number"] == select:
                target = it
        self.driver_list.blockSignals(False)
        if target is None and self.driver_list.count():
            target = self.driver_list.item(0)
        if target is not None:
            self.driver_list.setCurrentItem(target)
            self.driver_selected(target, None)
        else:
            self.current = None
            self.card = self.result = None
            self.refresh_views()

    def driver_selected(self, item, _prev):
        if item is None:
            return
        self.current = item.data(Qt.ItemDataRole.UserRole)
        self.card = self.archive.load_driver(self.current)
        st = Settings(unknown_as_rest=self.settings.value("unknown_as_rest", True, bool),
                      check_arbzg=self.settings.value("check_arbzg", True, bool),
                      ferry_rule=self.settings.value("ferry_rule", True, bool),
                      check_coverage=self.settings.value("check_coverage", True, bool),
                      coverage_days=self.settings.value("coverage_days", 56, int))
        self.result = analyze(self.card, st)
        self.refresh_views()

    def _since(self) -> dt.datetime | None:
        days = self.period_combo.currentData()
        if not days:
            return None
        today = dt.datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return today - dt.timedelta(days=days)

    def day_marks(self, findings) -> dict[dt.date, str]:
        """Je Tag die schwerste Bewertung – Hinweise färben nicht."""
        rank = {"warning": 1, "violation": 2}
        marks: dict[dt.date, str] = {}
        for f in findings:
            if f.severity in rank and rank[f.severity] > rank.get(marks.get(f.time.date(), ""), 0):
                marks[f.time.date()] = f.severity
        return marks

    def _tint_row(self, table, row: int, sev: str | None) -> None:
        if not sev:
            return
        for c in range(table.columnCount()):
            item = table.item(row, c)
            if item is not None:
                item.setBackground(QBrush(SEV_TINT[sev]))

    def _fill_findings(self, table, findings) -> None:
        table.setRowCount(len(findings))
        for r, f in enumerate(findings):
            table.setItem(r, 0, _item(fmt_dt(f.time)))
            table.setItem(r, 1, _item(tr("sev_" + f.severity), color=SEV_COLOR[f.severity], bold=True))
            table.setItem(r, 2, _item(tr(f.legal)))
            table.setItem(r, 3, _item(fmt_finding(f)))
            self._tint_row(table, r, f.severity if f.severity != "info" else None)
        for c in range(3):
            table.resizeColumnToContents(c)
        table.horizontalHeader().setStretchLastSection(True)

    def refresh_views(self, *_):
        has = self.card is not None and self.result is not None
        self.empty_label.setVisible(not has)
        self.empty_label.setText(tr("msg_empty") if self.archive.vault.ready else tr("msg_empty_locked"))
        tables = (self.t_days, self.t_findings, self.t_warnings, self.t_weeks, self.t_vehicles,
                  self.t_shifts, self.t_remaining, self.t_day_findings, self.t_day_shifts,
                  self.t_archive) + tuple(self.event_tables)
        for t in tables:
            t.setRowCount(0)
        for a in (self.a_pdf, self.a_csv):
            a.setEnabled(has)
        if not has:
            self.title.setText(tr("app_title"))
            self.summary.setText("")
            self.day_title.setText("")
            self.day_badge.setText("")
            self.calendar.set_data({}, {})
            for v in self.info_labels.values():
                v.setText("–")
            return
        card, res, since = self.card, self.result, self._since()
        i = card.info
        counts = res.counts(since)
        self.title.setText(i.display_name or i.card_number)
        self.summary.setText(tr("count_summary", **counts))
        vals = {
            "f_name": i.display_name,
            "f_birth": fmt_date(i.birth_date),
            "f_card": i.card_number,
            "f_nation": i.issuing_nation,
            "f_authority": i.authority,
            "f_valid": f"{fmt_date(i.validity_begin)} – {fmt_date(i.expiry_date)}",
            "f_licence": f"{i.licence_number} ({i.licence_nation})" if i.licence_number else "–",
            "f_generation": tr("gen_2" if i.generation == 2 else "gen_1"),
            "f_last_download": fmt_dt(i.last_download),
            "f_data_range": f"{fmt_dt(res.data_start)} – {fmt_dt(res.data_end)} UTC",
            "f_coverage": self._coverage_text(res),
            "f_findings": tr("count_summary", **counts),
        }
        for k, v in vals.items():
            self.info_labels[k].setText(v or "–")

        self.crossing_days = {}
        for c in res.crossings:
            d0 = c.start.replace(hour=0, minute=0, second=0, microsecond=0)
            while d0 < c.end:
                d1 = d0 + dt.timedelta(days=1)
                a, b = max(c.start, d0), min(c.end, d1)
                self.crossing_days.setdefault(d0.date(), []).append(
                    (int((a - d0).total_seconds() // 60), int((b - d0).total_seconds() // 60)))
                d0 = d1

        findings = [f for f in res.findings if since is None or f.time >= since]
        self.marks = self.day_marks(findings)
        self.calendar.set_data(self.marks, {d.date: d.totals.get(DRIVE, 0) for d in res.days})
        with_data = [d.date for d in res.days if sum(d.totals.values()) and d.totals.get(DRIVE, 0)]
        if with_data and (self.selected_day is None or self.selected_day not in with_data):
            self.selected_day = with_data[-1]
            self.calendar.blockSignals(True)
            self.calendar.setSelectedDate(QDate(self.selected_day.year, self.selected_day.month,
                                                self.selected_day.day))
            self.calendar.blockSignals(False)

        days = [d for d in res.days if since is None or d.date >= since.date()]
        days.reverse()
        t = self.t_days
        t.setRowCount(len(days))
        for r, d in enumerate(days):
            tot = d.totals
            sev = self.marks.get(d.date)
            t.setItem(r, 0, _item(("⚠ " if sev else "") + fmt_date(d.date) + ("  ✎" if d.manual else "")))
            t.setCellWidget(r, 1, DayBar(d.segments, self.crossing_days.get(d.date, ())))
            for col, act in ((2, DRIVE), (3, WORK), (4, AVAIL), (5, REST), (6, UNKNOWN)):
                t.setItem(r, col, _item(fmt_dur(tot.get(act, 0)), True, bold=(act == DRIVE)))
            t.setItem(r, 7, _item(d.distance, True))
            t.item(r, 0).setData(Qt.ItemDataRole.UserRole, d.date.isoformat())
            self._tint_row(t, r, sev)
            t.setRowHeight(r, 38)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setStretchLastSection(False)
        t.resizeColumnToContents(0)

        self._fill_findings(self.t_findings, [f for f in findings if f.severity == "violation"])
        self._fill_findings(self.t_warnings, [f for f in findings if f.severity != "violation"])

        weeks = [w for w in res.weeks if since is None or w.monday + dt.timedelta(days=7) > since]
        weeks.reverse()
        t = self.t_weeks
        t.setRowCount(len(weeks))
        for r, w in enumerate(weeks):
            y, n = w.iso
            t.setItem(r, 0, _item(f"{tr('week_fmt', week=n, year=y)}  ({fmt_date(w.monday)})"))
            drive = w.totals[DRIVE]
            t.setItem(r, 1, _item(fmt_dur(drive), True, SEV_COLOR["violation"] if drive > 56 * 60 else None, True))
            t.setItem(r, 2, _item(fmt_dur(w.totals[WORK]), True))
            t.setItem(r, 3, _item(fmt_dur(w.totals[AVAIL]), True))
            t.setItem(r, 4, _item(fmt_dur(w.totals[REST] + w.totals[UNKNOWN]), True))
            t.setItem(r, 5, _item(fmt_dur(w.worktime), True))
        t.resizeColumnsToContents()

        self._fill_shifts(res, since)
        self._fill_remaining(res)
        self._fill_events(card, res, since)

        vs = [v for v in card.vehicles if since is None or (v.last_use and v.last_use >= since)]
        vs.reverse()
        t = self.t_vehicles
        t.setRowCount(len(vs))
        for r, v in enumerate(vs):
            t.setItem(r, 0, _item(f"{v.nation} {v.registration}"))
            t.setItem(r, 1, _item(fmt_dt(v.first_use)))
            t.setItem(r, 2, _item(fmt_dt(v.last_use)))
            t.setItem(r, 3, _item(v.odo_begin, True))
            t.setItem(r, 4, _item(v.odo_end, True))
            t.setItem(r, 5, _item(v.vin))
        t.resizeColumnsToContents()

        years = self.settings.value("retention_years", 2, int)
        dls = list(reversed(self.archive.downloads(self.current))) if self.archive.vault.ready else []
        t = self.t_archive
        t.setRowCount(len(dls))
        for r, d in enumerate(dls):
            try:
                keep = d.imported_at.replace(year=d.imported_at.year + years)
            except ValueError:  # 29. Februar
                keep = d.imported_at + dt.timedelta(days=365 * years)
            t.setItem(r, 0, _item(fmt_dt(d.imported_at)))
            t.setItem(r, 1, _item(tr("src_card" if d.source == "card" else "src_file")))
            t.setItem(r, 2, _item(fmt_date(keep)))
            state = self.integrity.get(f"c{d.id}")
            if state is None:
                t.setItem(r, 3, _item(tr("integrity_unchecked")))
            else:
                t.setItem(r, 3, _item(tr("integrity_ok" if state else "integrity_bad"),
                                      color=None if state else SEV_COLOR["violation"], bold=not state))
            sig = self.signatures.get(f"c{d.id}")
            if sig is None:
                t.setItem(r, 4, _item(tr("sig_unchecked")))
            else:
                t.setItem(r, 4, _item(tr("sig_" + sig.state),
                                      color=SIG_COLOR.get(sig.state), bold=sig.state == "failed"))
            t.setItem(r, 5, _item(d.path.name))
        t.resizeColumnsToContents()
        self._fill_day()

    # ---------------------------------------------------------------- Einzelne Reiter
    def _fill_day(self) -> None:
        """Der im Kalender gewählte Tag."""
        res = self.result
        if res is None or self.selected_day is None:
            return
        day = next((d for d in res.days if d.date == self.selected_day), None)
        self.day_title.setText(fmt_date(self.selected_day))
        sev = self.marks.get(self.selected_day)
        counts = {}
        fs = [f for f in res.findings if f.time.date() == self.selected_day]
        for f in fs:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        if sev:
            text = " · ".join(f"{n} × {tr('sev_' + k)}" for k, n in counts.items() if k != "info")
            self.day_badge.setText(f"  {text}  ")
            self.day_badge.setStyleSheet(
                f"background:{SEV_TINT[sev].name()};color:{SEV_COLOR[sev].name()};"
                "border-radius:3px;padding:1px 6px;font-weight:bold;")
        else:
            self.day_badge.setText("")
            self.day_badge.setStyleSheet("")
        self.day_bar.segments = day.segments if day else []
        self.day_bar.crossings = list(self.crossing_days.get(self.selected_day, ()))
        self.day_bar.update()

        totals = day.totals if day else {}
        drive = totals.get(DRIVE, 0)
        work = drive + totals.get(WORK, 0)
        shifts = [s for s in res.shifts if s.start.date() == self.selected_day
                  or s.end.date() == self.selected_day]
        rest = max((int((s.rest_end - s.end).total_seconds() // 60) for s in shifts), default=0)
        self.day_meters.meters[0].set(tr("col_drive"), fmt_dur(drive), drive / 600,
                                      tr("meter_of", value="9:00 h"), drive > 600)
        self.day_meters.meters[1].set(tr("col_worktime"), fmt_dur(work), work / 600,
                                      tr("meter_of", value="10:00 h"), work > 600)
        if shifts:
            self.day_meters.meters[2].set(tr("meter_rest_after"), fmt_dur(rest), rest / (11 * 60),
                                          tr("meter_min", value="9:00 h"), rest < 9 * 60)
        else:
            # Ohne abgeschlossene Schicht gibt es keine Ruhezeit zu messen – lieber nichts
            # anzeigen als eine Zahl, die etwas anderes meint.
            self.day_meters.meters[2].set(tr("meter_rest_after"), "–", 0.0, tr("meter_shift_open"))
        self.day_meters.meters[3].set(tr("col_km"), str(day.distance if day else 0), 0.0,
                                      tr("meter_day_distance"))
        self._fill_findings(self.t_day_findings, fs)
        t = self.t_day_shifts
        t.setRowCount(len(shifts))
        for r, s in enumerate(shifts):
            rest_after = int((s.rest_end - s.end).total_seconds() // 60)
            t.setItem(r, 0, _item(fmt_dt(s.start)))
            t.setItem(r, 1, _item(fmt_dt(s.end)))
            t.setItem(r, 2, _item(fmt_dur(int((s.end - s.start).total_seconds() // 60)), True))
            t.setItem(r, 3, _item(fmt_dur(s.driving), True, bold=True))
            t.setItem(r, 4, _item(fmt_dur(s.work), True))
            t.setItem(r, 5, _item(fmt_dur(rest_after), True))
            t.setItem(r, 6, _item(tr("rest_" + s.rest_kind) if s.rest_kind else "–"))
        t.resizeColumnsToContents()

    def _fill_shifts(self, res, since) -> None:
        shifts = [s for s in res.shifts if since is None or s.end >= since]
        durations = [int((s.end - s.start).total_seconds() // 60) for s in shifts]
        count = len(shifts)
        avg = sum(durations) // count if count else 0
        longest = max(durations, default=0)
        avg_drive = sum(s.driving for s in shifts) // count if count else 0
        m = self.shift_meters.meters
        m[0].set(tr("meter_shifts"), str(count), 1.0 if count else 0.0, tr("meter_in_period"))
        m[1].set(tr("meter_avg_shift"), fmt_dur(avg), avg / (15 * 60), tr("meter_max", value="15:00 h"))
        m[2].set(tr("meter_longest_shift"), fmt_dur(longest), longest / (15 * 60),
                 tr("meter_max", value="15:00 h"), longest > 15 * 60)
        m[3].set(tr("meter_avg_drive"), fmt_dur(avg_drive), avg_drive / 600,
                 tr("meter_of", value="9:00 h"))
        t = self.t_shifts
        t.setRowCount(len(shifts))
        for r, s in enumerate(reversed(shifts)):
            rest_after = int((s.rest_end - s.end).total_seconds() // 60)
            bad = s.driving > 600 or (rest_after and rest_after < 9 * 60)
            t.setItem(r, 0, _item(fmt_dt(s.start)))
            t.setItem(r, 1, _item(fmt_dt(s.end)))
            t.setItem(r, 2, _item(fmt_dur(int((s.end - s.start).total_seconds() // 60)), True))
            t.setItem(r, 3, _item(fmt_dur(s.driving), True,
                                  SEV_COLOR["violation"] if s.driving > 600 else None, True))
            t.setItem(r, 4, _item(fmt_dur(s.work), True))
            t.setItem(r, 5, _item(fmt_dur(s.avail), True))
            t.setItem(r, 6, _item(fmt_dur(rest_after), True,
                                  SEV_COLOR["violation"] if rest_after and rest_after < 9 * 60 else None))
            t.setItem(r, 7, _item(tr("rest_" + s.rest_kind) if s.rest_kind else "–"))
            t.setItem(r, 8, _item(tr("sev_violation") if bad else "–",
                                  color=SEV_COLOR["violation"] if bad else None, bold=bad))
            if bad:
                self._tint_row(t, r, "violation")
            elif s.rest_kind == "weekly":
                # Wochenruhe grenzt die Wochen ab. Bewusst ein neutrales Grau: Rot und
                # Gelb bleiben den Verstößen und Warnungen vorbehalten. Die Spalte
                # „Art der Ruhe“ nennt es ohnehin im Klartext.
                shade = QColor(t.palette().text().color())
                shade.setAlpha(26)
                for c in range(t.columnCount()):
                    t.item(r, c).setBackground(QBrush(shade))
        t.resizeColumnsToContents()

    def _fill_remaining(self, res) -> None:
        """Prognose aus dem Stand der vorliegenden Daten."""
        now = dt.datetime.now(UTC)
        rest = remaining(res, now)
        self.remaining_note.setText(tr("note_remaining", time=fmt_dt(now)))
        top = self.remaining_top.meters
        top[0].set(tr("meter_left_today"), fmt_dur(rest["day"]), rest["day"] / rest["limit"],
                   tr("meter_of", value=fmt_dur(rest["limit"])), rest["day"] <= 0)
        top[1].set(tr("meter_left_week"), fmt_dur(rest["week"]), rest["week"] / (56 * 60),
                   tr("meter_of", value="56:00 h"), rest["week"] <= 0)
        top[2].set(tr("meter_left_fortnight"), fmt_dur(rest["fortnight"]),
                   rest["fortnight"] / (90 * 60), tr("meter_of", value="90:00 h"),
                   rest["fortnight"] <= 0)
        bottom = self.remaining_bottom.meters
        bottom[0].set(tr("meter_extensions"), str(rest["extensions"]), rest["extensions"] / 2,
                      tr("meter_left_week_note"), rest["extensions"] <= 0)
        bottom[1].set(tr("meter_reduced_rests"), str(rest["reduced"]), rest["reduced"] / 3,
                      tr("meter_until_weekly"), rest["reduced"] <= 0)
        bottom[2].set(tr("meter_until_weekly_rest"),
                      fmt_dur(rest["weekly"]) if rest["weekly"] is not None else "–",
                      (rest["weekly"] or 0) / (144 * 60), tr("meter_max", value="144:00 h"),
                      rest["weekly"] is not None and rest["weekly"] <= 0)
        rows = [
            (tr("limit_daily_drive"), fmt_dur(rest["day_used"]), tr(LEGAL_TEXT["drive_day"])),
            (tr("limit_extension"), tr("value_of_two", used=2 - rest["extensions"]),
             tr(LEGAL_TEXT["drive_day"])),
            (tr("limit_week_drive"), fmt_dur(rest["week_used"]), tr(LEGAL_TEXT["drive_week"])),
            (tr("limit_fortnight_drive"), fmt_dur(rest["fortnight_used"]), tr(LEGAL_TEXT["drive_two"])),
            (tr("limit_shift_end"), tr("value_after", value="15:00 h"), tr(LEGAL_TEXT["daily_rest"])),
            (tr("limit_break"), tr("value_after", value="4:30 h"), tr(LEGAL_TEXT["break"])),
            (tr("limit_weekly_rest"),
             fmt_dt(rest["weekly_due"]) if rest["weekly_due"] else "–", tr(LEGAL_TEXT["weekly_rest"])),
        ]
        t = self.t_remaining
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                t.setItem(r, c, _item(v))
        t.resizeColumnsToContents()

    def _fill_events(self, card, res, since) -> None:
        """Fehler, Kontrollen, Sonstiges – jedes in sein Feld."""
        faults, controls, other = [], [], []
        for e in card.events:
            if since is not None and e.begin and e.begin < since:
                continue
            row = (event_name(e.type, e.fault), fmt_dt(e.begin), fmt_dt(e.end),
                   f"{e.nation} {e.registration}".strip())
            (faults if e.fault else other).append(row)
        for c in card.controls:
            if since is not None and c.time and c.time < since:
                continue
            period = (f"{fmt_dt(c.period_begin)} – {fmt_dt(c.period_end)}"
                      if c.period_begin or c.period_end else "–")
            controls.append((control_name(c.type), fmt_dt(c.time), period,
                             c.registration or c.card_number))
        for c in res.crossings:
            if since is None or c.start >= since:
                other.append((tr("ev_ferry_est" if c.estimated else "ev_ferry"),
                              fmt_dt(c.start), fmt_dt(c.end), ""))
        for head, table, rows, key in zip(
                self.event_heads, self.event_tables, (faults, controls, other),
                ("head_ev_faults", "head_ev_controls", "head_ev_other")):
            head.setText(f"{tr(key)}  ({len(rows)})")
            rows.sort(key=lambda r: r[1], reverse=True)
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, v in enumerate(row):
                    table.setItem(r, c, _item(v))
            table.resizeColumnsToContents()

    # ---------------------------------------------------------------- Kalender
    def day_selected(self, qdate) -> None:
        """Klick im Kalender öffnet den Tagesreiter."""
        self.selected_day = dt.date(qdate.year(), qdate.month(), qdate.day())
        self._fill_day()
        self.tabs.setCurrentIndex(0)

    def _day_row_selected(self) -> None:
        """Auswahl in der Tagesliste wandert in den Kalender."""
        items = self.t_days.selectedItems()
        if not items:
            return
        first = self.t_days.item(items[0].row(), 0)
        iso = first.data(Qt.ItemDataRole.UserRole) if first else None
        if not iso:
            return
        day = dt.date.fromisoformat(iso)
        self.selected_day = day
        self.calendar.blockSignals(True)
        self.calendar.setSelectedDate(QDate(day.year, day.month, day.day))
        self.calendar.blockSignals(False)
        self._fill_day()

    # ---------------------------------------------------------------- Geschwindigkeit
    def _speed_limit_changed(self, value: int) -> None:
        self.settings.setValue("speed_limit", value)
        self.refresh_speed()

    def load_speed(self) -> None:
        """Geschwindigkeitsblöcke aller Downloads des gewählten Fahrzeugs einlesen."""
        self.speed_blocks = []
        if not self.current_vehicle or not self.archive.vault.ready:
            self._fill_speed_days()
            return
        blocks = []
        for d in self.archive.vu_downloads(self.current_vehicle):
            try:
                vf, _ = parse_vu(self.archive._load(d.path))
                blocks += parse_speed(vf)
            except (OSError, ValueError, VaultError):
                continue
        self.speed_blocks = blocks
        self._fill_speed_days()

    def _fill_speed_days(self) -> None:
        days = sorted(speed_days(self.speed_blocks), reverse=True)
        current = self.speed_day.currentData()
        self.speed_day.blockSignals(True)
        self.speed_day.clear()
        for d in days:
            self.speed_day.addItem(fmt_date(d), d)
        if current in days:
            self.speed_day.setCurrentIndex(days.index(current))
        self.speed_day.blockSignals(False)
        self.refresh_speed()

    def refresh_speed(self, *_) -> None:
        day = self.speed_day.currentData()
        limit = self.speed_limit.value()
        for t in (self.t_overspeed, self.t_speed_hours):
            t.setRowCount(0)
        if day is None:
            self.speed_chart.set_data([], limit, [])
            for m in self.speed_meters.meters:
                m.set("", "–", 0.0, "")
            self.t_overspeed_head.setText(tr("head_overspeed"))
            self.t_speed_hours_head.setText(tr("head_speed_hours"))
            return
        series = speed_series(self.speed_blocks, day)
        spans = overspeed(self.speed_blocks, day, limit)
        stats = speed_stats(self.speed_blocks, day, limit)
        midnight = dt.datetime.combine(day, dt.time(), tzinfo=UTC)
        self.speed_chart.set_data(series, limit, [
            (int((o.start - midnight).total_seconds()), o.seconds, o.peak) for o in spans])
        m = self.speed_meters.meters
        m[0].set(tr("meter_peak"), f"{stats['peak']} km/h", stats["peak"] / max(limit * 1.4, 1),
                 tr("meter_peak_at", time=fmt_dt(stats["peak_at"])) if stats["peak_at"] else "–",
                 stats["peak"] > limit)
        m[1].set(tr("meter_avg_speed"), f"{stats['average']} km/h",
                 stats["average"] / max(limit, 1), tr("meter_moving", value=fmt_dur(stats["moving"] // 60)))
        m[2].set(tr("meter_time_over", limit=limit), fmt_dur(stats["over"] // 60),
                 stats["over"] / max(stats["recorded"], 1),
                 tr("meter_seconds", count=stats["over"]), stats["over"] > 0)
        m[3].set(tr("meter_overspeed_count"), str(len(spans)), min(len(spans) / 5, 1.0),
                 tr("meter_overspeed_note"), bool(spans))
        self.t_overspeed_head.setText(f"{tr('head_overspeed')}  ({len(spans)})")
        self.t_speed_hours_head.setText(tr("head_speed_hours"))
        t = self.t_overspeed
        t.setRowCount(len(spans))
        for r, o in enumerate(spans):
            t.setItem(r, 0, _item(o.start.strftime("%H:%M:%S")))
            t.setItem(r, 1, _item(tr("value_seconds", count=o.seconds), True))
            t.setItem(r, 2, _item(f"{o.peak} km/h", True, SEV_COLOR["violation"], True))
            t.setItem(r, 3, _item(f"{o.average} km/h", True))
            self._tint_row(t, r, "violation")
        t.resizeColumnsToContents()
        t = self.t_speed_hours
        rows = []
        for hour in range(24):
            seg = [v for v in series[hour * 3600:(hour + 1) * 3600] if v >= 0]
            moving = [v for v in seg if v > 0]
            if not seg:
                continue
            over = sum(1 for v in seg if v > limit)
            rows.append((f"{hour:02d}:00",
                         f"{round(sum(moving) / len(moving)) if moving else 0} km/h",
                         f"{max(seg)} km/h", tr("value_seconds", count=over),
                         f"{round(sum(moving) / 3600)} km", over))
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row[:5]):
                t.setItem(r, c, _item(v, c > 0))
            self._tint_row(t, r, "violation" if row[5] else None)
        t.resizeColumnsToContents()

    def export_speed_csv(self) -> None:
        day = self.speed_day.currentData()
        if day is None:
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, tr("btn_speed_csv"), f"Geschwindigkeit_{day:%Y%m%d}.csv", "CSV (*.csv)")
        if not fn:
            return
        series = speed_series(self.speed_blocks, day)
        import csv
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow([tr("col_time"), "km/h"])
            for sec, value in enumerate(series):
                if value >= 0:
                    w.writerow([f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}", value])
        self.statusBar().showMessage(tr("msg_export_ok", file=fn), 8000)

    # ---------------------------------------------------------------- Zugangsschutz
    def _show_lock(self) -> None:
        vault = self.archive.vault
        if not vault.enabled:
            self.lock_label.setText(tr("lock_off"))
            self.btn_lock.setText(tr("btn_protect"))
            self.lock_state.setText("")
        elif vault.unlocked:
            minutes = self.settings.value("lock_minutes", 15, int)
            self.lock_label.setText(tr("lock_open", minutes=minutes) if minutes else tr("lock_open_no_timer"))
            self.btn_lock.setText(tr("btn_lock"))
            self.lock_state.setText("🔓 " + tr("lock_state_open"))
        else:
            self.lock_label.setText(tr("lock_closed"))
            self.btn_lock.setText(tr("btn_unlock"))
            self.lock_state.setText("🔒 " + tr("lock_state_closed"))

    def toggle_lock(self) -> None:
        vault = self.archive.vault
        if not vault.enabled:
            self.open_access()
        elif vault.unlocked:
            self.lock_archive()
        else:
            self.ask_unlock()

    def lock_archive(self) -> None:
        self.archive.lock()
        self.card = self.result = None
        self.current = self.current_vehicle = None
        self.driver_list.clear()
        self.vehicle_list.clear()
        self.speed_blocks = []
        self.refresh_views()
        self.refresh_speed()
        self._show_lock()
        self.statusBar().showMessage(tr("msg_locked"), 8000)

    def ask_unlock(self) -> bool:
        """Fragt nach Passwort oder Wiederherstellungsschlüssel."""
        while True:
            secret, ok = QInputDialog.getText(self, tr("act_access"), tr("ask_password"),
                                              QLineEdit.EchoMode.Password)
            if not ok:
                return False
            try:
                self.archive.unlock(secret)
            except WrongSecret:
                QMessageBox.warning(self, tr("act_access"), tr("msg_wrong_password"))
                continue
            except VaultError as e:
                QMessageBox.critical(self, tr("act_access"), str(e))
                return False
            self.touch()
            self.reload_drivers()
            self.reload_vehicles()
            self._show_lock()
            self.statusBar().showMessage(tr("msg_unlocked"), 8000)
            return True

    def open_access(self) -> None:
        if AccessDialog(self, self.archive, self.settings).exec():
            self._show_lock()
            self.refresh_views()

    def touch(self) -> None:
        """Merkt sich die letzte Bedienung – Grundlage für die Selbstsperre."""
        self._last_action = dt.datetime.now(UTC)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress,
                            QEvent.Type.Wheel):
            self.touch()
        return super().eventFilter(obj, event)

    def _check_autolock(self) -> None:
        minutes = self.settings.value("lock_minutes", 15, int)
        vault = self.archive.vault
        if not (minutes and vault.enabled and vault.unlocked):
            return
        if dt.datetime.now(UTC) - self._last_action >= dt.timedelta(minutes=minutes):
            self.lock_archive()

    # ---------------------------------------------------------------- Export
    def _period_text(self) -> str:
        return self.period_combo.currentText()

    def export_pdf(self):
        if not self.result:
            return
        periods = [(self.period_combo.itemText(i), self.period_combo.itemData(i))
                   for i in range(self.period_combo.count())]
        dlg = ExportDialog(self, self.settings, periods, self.period_combo.currentIndex(),
                           self.card.info.surname)
        if not dlg.exec():
            return
        opt = dlg.result_values()
        self.settings.setValue("pdf_scope", opt["scope"])
        self.settings.setValue("pdf_warnings", opt["with_warnings"])
        self.settings.setValue("pdf_language", opt["language"])
        fn, _ = QFileDialog.getSaveFileName(self, tr("act_export_pdf"), opt["name"], "PDF (*.pdf)")
        if not fn:
            return
        since = None
        if opt["days"]:
            today = dt.datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            since = today - dt.timedelta(days=opt["days"])
        from .report import build_html
        doc = QTextDocument()
        doc.setHtml(build_html(self.card, self.result, since, opt["period_label"],
                               scope=opt["scope"], with_warnings=opt["with_warnings"],
                               language=opt["language"], period_key=PERIODS[opt["index"]][0],
                               control_days=self.settings.value("coverage_days", 56, int)))
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(fn)
        doc.print_(printer)
        self.statusBar().showMessage(tr("msg_export_ok", file=fn), 8000)

    def export_csv(self):
        if not self.result:
            return
        fn, _ = QFileDialog.getSaveFileName(self, tr("act_export_csv"),
                                            f"Auswertung_{dt.date.today():%Y%m%d}.csv", "CSV (*.csv)")
        if not fn:
            return
        from .report import write_csv
        write_csv(fn, self.result, self._since())
        self.statusBar().showMessage(tr("msg_export_ok", file=fn), 8000)

    # ---------------------------------------------------------------- Archiv
    def verify_archive(self):
        self.integrity = self.archive.verify()
        bad = sum(1 for v in self.integrity.values() if not v)
        n = len(self.integrity)
        if bad:
            QMessageBox.critical(self, tr("act_verify"), tr("msg_verify_bad", bad=bad, count=n))
        else:
            QMessageBox.information(self, tr("act_verify"), tr("msg_verify_ok", count=n))
        self.refresh_views()

    def check_signatures(self):
        """Prüft die Kartensignaturen gegen die hinterlegte Wurzel."""
        if not self.archive.vault.ready:
            self.ask_unlock()
            return
        roots = self.archive.roots()
        self.signatures = self.archive.check_signatures()
        self.refresh_views()
        if roots.empty:
            self._ask_for_root()
            if not any(s.state == "partial" for s in self.signatures.values()):
                return
        bad = sum(1 for s in self.signatures.values() if s.state == "failed")
        partial = sum(1 for s in self.signatures.values() if s.state == "partial")
        unknown = sum(1 for s in self.signatures.values()
                      if s.state in ("no_root", "unsupported"))
        total = len(self.signatures)
        if bad:
            QMessageBox.critical(self, tr("act_check_signatures"),
                                 tr("msg_sig_bad", bad=bad, count=total))
        elif partial:
            QMessageBox.information(self, tr("act_check_signatures"),
                                    tr("msg_sig_partial_root", count=partial))
        elif unknown:
            QMessageBox.warning(self, tr("act_check_signatures"),
                                tr("msg_sig_partial", count=total - unknown, total=total))
        else:
            QMessageBox.information(self, tr("act_check_signatures"),
                                    tr("msg_sig_ok", count=total))

    def _ask_for_root(self) -> None:
        """Sagt, wohin das Wurzelzertifikat gehört – und macht den Ordner auf."""
        folder = self.archive.prepare_erca()
        box = QMessageBox(self)
        box.setWindowTitle(tr("act_check_signatures"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(tr("msg_sig_no_root", folder=str(folder)))
        open_button = box.addButton(tr("btn_open_folder"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_manual(self):
        """Öffnet die Bedienungsanleitung dort, wo sie installiert wurde."""
        here = Path(__file__).resolve().parent
        candidates = [here.parent / "doc" / "bedienungsanleitung.md",
                      Path("/usr/share/doc/tachoarchiv/bedienungsanleitung.md"),
                      Path("/usr/local/share/doc/tachoarchiv/bedienungsanleitung.md"),
                      Path("/usr/share/doc/tachoarchiv/bedienungsanleitung.md.gz")]
        for path in candidates:
            if path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return
        QMessageBox.information(self, tr("act_manual"), tr("msg_manual_missing"))

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.archive.base)))

    def open_settings(self):
        if SettingsDialog(self.settings, self).exec():
            if self.current:
                item = self.driver_list.currentItem()
                self.driver_selected(item, None)

    def card_diagnosis(self):
        """Sendet lesende Testbefehle an die Karte – Hilfe bei nicht lesbaren Karten."""
        reader = self.reader_combo.currentData()
        if not reader:
            QMessageBox.information(self, tr("act_diagnosis"), tr("msg_pcsc_missing"))
            return
        try:
            with PCSC() as ctx, ctx.connect(reader) as card:
                lines = [reader, ""] + probe(card)
        except PCSCError as e:
            lines = [tr("msg_no_card") if e.no_card else
                     (tr("msg_pcsc_missing") if e.no_service else str(e))]
        except (CardError, OSError, ValueError) as e:
            lines = [str(e)]
        self._text_dialog(tr("act_diagnosis"), tr("diag_note"), lines)

    def _text_dialog(self, title: str, note_text: str, lines: list[str]) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(820, 520)
        lay = QVBoxLayout(dlg)
        note = QLabel(note_text)
        note.setWordWrap(True)
        lay.addWidget(note)
        text = QPlainTextEdit("\n".join(lines))
        text.setReadOnly(True)
        text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(text, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = bb.addButton(tr("btn_copy"), QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text.toPlainText()))
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        dlg.exec()

    def certificate_diagnosis(self):
        """Aufbau der Zertifikate des neuesten Downloads – ohne Fahrerdaten."""
        if not self.archive.vault.ready:
            self.ask_unlock()
            return
        dls = self.archive.downloads(self.current)
        if not dls:
            QMessageBox.information(self, tr("act_certdiag"), tr("msg_empty"))
            return
        from .certdiag import describe
        try:
            lines = describe(self.archive._load(dls[-1].path), self.archive.roots())
        except (OSError, ValueError, VaultError) as e:
            lines = [str(e)]
        self._text_dialog(tr("act_certdiag"), tr("certdiag_note"), lines)

    def about(self):
        QMessageBox.about(self, tr("act_about"), tr("about_text", version=__version__))


def _system_language() -> str:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        code = v.split(":")[0][:2].lower()
        if code in i18n.LANGUAGES:
            return code
    return "en"


def _apply_direction(lang: str) -> None:
    """Arabisch und Urdu werden von rechts nach links geschrieben."""
    app = QApplication.instance()
    if app is not None:
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl(lang)
                               else Qt.LayoutDirection.LeftToRight)


def install_qt_translations(lang: str) -> None:
    """Uebersetzt Qts eigene Texte (OK, Abbrechen, Schliessen) passend zur Oberflaeche."""
    app = QApplication.instance()
    if app is None:
        return
    old = getattr(app, "_qt_translator", None)
    if old is not None:
        app.removeTranslator(old)
        app._qt_translator = None
    tr_ = QTranslator()
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if tr_.load(f"qtbase_{lang}", path):
        app.installTranslator(tr_)
        app._qt_translator = tr_


def main() -> int:
    # Vor dem Start von Qt, damit beides auch ohne Bildschirm funktioniert.
    args = sys.argv[1:]
    if "--version" in args or "-V" in args:
        print(f"TachoArchiv {__version__}")
        return 0
    if "--help" in args or "-h" in args:
        print(f"TachoArchiv {__version__} – Fahrerkarten auslesen, archivieren, auswerten\n"
              f"Aufruf: tachoarchiv [--version] [--help]\n"
              f"Das Programm wird über seine Oberfläche bedient und kennt sonst keine "
              f"Befehlszeilenoptionen.")
        return 0
    app = QApplication(sys.argv)
    app.setOrganizationName("TachoArchiv")
    app.setApplicationName("TachoArchiv")
    app.setDesktopFileName(APP_ID)
    app.setApplicationVersion(__version__)
    win = MainWindow()
    install_qt_translations(i18n.language())
    _apply_direction(i18n.language())
    win.show()
    return app.exec()
