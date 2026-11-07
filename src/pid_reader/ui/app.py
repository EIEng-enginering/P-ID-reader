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


def run_app(database: str | None = None) -> int:
    app = make_application()
    from .main_window import MainWindow
    window = MainWindow(database)
    from PySide6.QtCore import QSettings
    geometry = QSettings("EnhanceIntegrationEngineering", "PIDReader").value("geometry")
    if geometry:
        window.restoreGeometry(geometry)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_app(sys.argv[1] if len(sys.argv) > 1 else None))
