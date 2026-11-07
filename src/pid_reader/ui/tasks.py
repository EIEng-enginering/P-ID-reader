"""Background task runner for the desktop app (keeps the UI responsive).

Worker functions receive ``(report, is_cancelled)`` and must open their own
``ProjectStore`` (a SQLite connection must not cross threads). Cancellation is
cooperative; the isolated PDF reader additionally kills its child process.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..api import CancelToken, Cancelled


class CallbackCancelToken(CancelToken):
    def __init__(self, is_cancelled):
        super().__init__()
        self._is_cancelled = is_cancelled

    def check(self) -> None:
        if self._is_cancelled():
            raise Cancelled()


class Task(QThread):
    progress = Signal(float, str)
    result = Signal(object)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, title: str, fn, parent=None):
        super().__init__(parent)
        self.title = title
        self._fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:  # executes in the worker thread
        try:
            out = self._fn(lambda fraction, message: self.progress.emit(float(fraction), str(message)),
                           self.is_cancelled)
        except Cancelled:
            self.stopped.emit()
            return
        except Exception as exc:  # reported to the user, never silently swallowed
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        if self._cancel:
            self.stopped.emit()
        else:
            self.result.emit(out)
