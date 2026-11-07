"""Child-process entry for the standalone reader (native text + optional offline OCR).

Same CLI, exit codes and atomic publication as the frozen R1 worker
(``pid_reader.worker``); only the reader function differs. The OCR engine is
chosen with the ``PID_OCR_ENGINE`` environment variable (auto|tesseract|rapidocr|off).
"""
from __future__ import annotations

import os

from .. import worker
from .standalone_read import read_pid_standalone


def main(argv=None) -> int:
    engine = os.environ.get("PID_OCR_ENGINE", "auto")
    if engine not in ("auto", "tesseract", "rapidocr", "off"):
        engine = "auto"

    def reader(data, params, cancel, **kwargs):
        return read_pid_standalone(data, params, cancel, ocr_engine=None if engine == "off" else engine, **kwargs)

    return worker.main(argv, _reader=reader)


if __name__ == "__main__":
    raise SystemExit(main())
