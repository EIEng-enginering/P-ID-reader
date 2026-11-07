"""Drive the real desktop window (native Windows platform) and save screenshots.

    python tools/gui_screenshots.py OUT_DIR [--scale 1.25]

Uses a throw-away project in a temp folder and settings in a temp INI file.
QT_SCALE_FACTOR can emulate 100/125/150 % display scaling for evidence.
"""
import argparse, os, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ap = argparse.ArgumentParser()
ap.add_argument("out_dir")
ap.add_argument("--scale", default="1")
ap.add_argument("--pdf", default=str(ROOT / "fixtures" / "synthetic_catalog_symbols.pdf"))
args = ap.parse_args()
os.environ["QT_SCALE_FACTOR"] = args.scale

from PySide6.QtCore import QSettings
from pid_reader.ui.app import make_application
app = make_application([])
tmp = Path(tempfile.mkdtemp(prefix="pid-shots-"))
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp / "qs"))
from pid_reader.ui import main_window as mw
s = QSettings(mw.ORG, mw.APP); s.clear(); s.setValue("reviewer", "Screenshot Run"); s.setValue("ocr_engine", "auto")
w = mw.MainWindow(str(tmp / "shots.sqlite")); w.resize(1500, 900); w.show()

def idle():
    t = time.time()
    while w.task is not None and time.time() - t < 240:
        app.processEvents(); time.sleep(0.02)
    for _ in range(20): app.processEvents()

out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
w._import([Path(args.pdf)]); idle()
w.analyze(); idle()
w.layer_combo.setCurrentIndex(w.layer_combo.findData("symbols")); w.show_findings()
if w.finding_rows: w.finding_table.selectRow(0)
w.viewer.fit()
tag = f"scale{args.scale}"
names = ["drawing", "registers", "graph", "revisions", "batch", "libraries", "reports", "audit"]
for i, n in enumerate(names):
    w.tabs.setCurrentIndex(i)
    if n == "libraries": w.library_tab.example("tag"); w.library_tab.example("cat")
    for _ in range(10): app.processEvents()
    w.grab().save(str(out / f"{n}_{tag}.png"))
print("saved", len(names), "screenshots to", out, "dpr", w.devicePixelRatioF())
w.close()
