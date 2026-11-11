# PyInstaller spec: python -m PyInstaller packaging/pid_reader.spec --distpath C:/PIDWork/build/dist --workpath C:/PIDWork/build/work
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtBluetooth", "PySide6.QtNetwork",
            "tkinter", "matplotlib", "pytest", "IPython"]
datas = (collect_data_files("rapidocr_onnxruntime") + collect_data_files("pdfminer") + collect_data_files("pypdfium2_raw")
         + collect_data_files("pypdfium2") + collect_data_files("pdfplumber")
         + [(str(ROOT / "contracts"), "contracts"), (str(ROOT / "fixtures" / "synthetic_pid_vector.pdf"), "examples"),
            (str(ROOT / "fixtures" / "synthetic_catalog_symbols.pdf"), "examples"),
            (str(ROOT / "docs"), "docs"),
            # TR1: the learned-detector script is started BY PATH with the optional torch component's Python, so it ships as data; only the small cards are bundled
            # (weights are larger and are placed in %LOCALAPPDATA%/PIDReader/tr1/models or beside the program in models/)
            (str(ROOT / "src" / "pid_reader" / "tr1" / "infer_cli.py"), "pid_reader/tr1"), (str(ROOT / "src" / "pid_reader" / "tr1" / "tiled_r3.py"), "pid_reader/tr1"),
            (str(ROOT / "models" / "E5_MODEL_CARD.json"), "models"), (str(ROOT / "models" / "R3_FINE_CLASS_CARD.json"), "models")])
binaries = collect_dynamic_libs("onnxruntime") + collect_dynamic_libs("pypdfium2_raw")
hidden = ["pid_reader.engineering.standalone_worker", "pid_reader.worker", "pid_reader.cli", "rapidocr_onnxruntime",
          "pid_reader.tr1.detector", "pid_reader.tr1.review", "pid_reader.tr1.batch_export", "pid_reader.tr1.proposals", "pid_reader.ui.tr1_dialog"]

a_gui = Analysis([str(ROOT / "packaging" / "pid_reader_app.py")], pathex=[str(ROOT / "src")], binaries=binaries,
                 datas=datas, hiddenimports=hidden, excludes=EXCLUDES)
a_cli = Analysis([str(ROOT / "packaging" / "pid_reader_cli.py")], pathex=[str(ROOT / "src")], binaries=[],
                 datas=[], hiddenimports=hidden, excludes=EXCLUDES)
MERGE((a_gui, "PIDReader", "PIDReader"), (a_cli, "pid-reader-cli", "pid-reader-cli"))
pyz_gui, pyz_cli = PYZ(a_gui.pure), PYZ(a_cli.pure)
exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="PIDReader", console=False, icon=None)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="pid-reader-cli", console=True)
COLLECT(exe_gui, a_gui.binaries, a_gui.datas, exe_cli, a_cli.binaries, a_cli.datas, name="PIDReader")
