"""Desktop entry point: ``python -m pid_reader.ui.app [project.sqlite]`` or ``pid-reader gui``."""
from __future__ import annotations

import sys


def make_application(argv: list[str] | None = None):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    # Crisp rendering at 125% / 150% / 175% Windows scaling (no rounding to whole factors).
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("PIDReader")
    app.setOrganizationName("EnhanceIntegrationEngineering")
    app.setStyle("Fusion")
    return app


def fit_window_to_screen(window) -> None:
    """A remembered window size from another monitor/scale must never leave panels off-screen."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    frame = window.frameGeometry()
    visible = area.intersected(frame)
    if (frame.width() > area.width() or frame.height() > area.height() or visible.width() < frame.width() * 0.9
            or visible.height() < frame.height() * 0.9):
        window.resize(int(area.width() * 0.94), int(area.height() * 0.92))
        window.move(area.topLeft() + QPoint(int(area.width() * 0.03), int(area.height() * 0.03)))


def run_app(database: str | None = None) -> int:
    app = make_application()
    from .main_window import MainWindow
    window = MainWindow(database)
    from PySide6.QtCore import QSettings
    geometry = QSettings("EnhanceIntegrationEngineering", "PIDReader").value("geometry")
    if geometry:
        window.restoreGeometry(geometry)
    fit_window_to_screen(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_app(sys.argv[1] if len(sys.argv) > 1 else None))
