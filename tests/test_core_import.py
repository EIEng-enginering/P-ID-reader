from pathlib import Path
import subprocess,sys


def test_import_has_no_qt_side_effects(tmp_path):
    snippet="import sys;import pid_reader;assert 'PySide6' not in sys.modules;assert 'pdfplumber' not in sys.modules;assert 'pypdf' not in sys.modules;print(pid_reader.__version__)"
    r=subprocess.run([sys.executable,"-c",snippet],cwd=tmp_path,env={"PYTHONPATH":str(Path(__file__).resolve().parents[1]/"src")},capture_output=True,text=True)
    assert r.returncode==0,r.stderr
