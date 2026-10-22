"""Bildschirmfotos der Oberfläche mit den Demodaten, z. B. für die Projektseite.

Aufruf: python tools/screenshots.py [Zielordner] [Sprache]

Läuft in einem eigenen, temporären Datenverzeichnis; Archiv und Einstellungen
des Benutzers bleiben unberührt.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QDate, QSettings, QStandardPaths, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
lang = sys.argv[2] if len(sys.argv) > 2 else "en"
out.mkdir(parents=True, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="tachoarchiv-shots-")
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp

QStandardPaths.setTestModeEnabled(True)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
app = QApplication(sys.argv)
app.setStyle("Fusion")
app.styleHints().setColorScheme(Qt.ColorScheme.Light)   # hell, unabhängig vom System
QCoreApplication.setOrganizationName("TachoArchiv-Screenshots")
QCoreApplication.setApplicationName("TachoArchiv-Screenshots")
s = QSettings()
s.setValue("language", lang)
s.setValue("archive_dir", str(Path(tmp) / "archiv"))
s.sync()

from tachoarchiv import app as ta  # noqa: E402

win = ta.MainWindow()
ta.install_qt_translations(lang)
win.resize(1360, 860)
win.show()


def shoot():
    win.load_demo()
    win.day_selected(QDate(2026, 10, 14))          # ein Tag mit Verstoß
    win.statusBar().clearMessage()
    app.processEvents()
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        app.processEvents()
        win.grab().save(str(out / f"tab{i:02d}.png"))
    win.tabs.setCurrentIndex(7)                     # Fahrzeug ▸ Geschwindigkeit
    win.vehicle_tabs.setCurrentIndex(1)
    app.processEvents()
    win.grab().save(str(out / "speed.png"))
    app.quit()


QTimer.singleShot(500, shoot)
app.exec()
print(f"Bilder in {out}")
