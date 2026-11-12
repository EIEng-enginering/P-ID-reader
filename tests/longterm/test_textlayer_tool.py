"""build_textlayer_crops: every crop's label is the text-layer word at THAT position (regression: a stale loop variable labelled every crop with the page's last word)."""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
ROOT = Path(__file__).resolve().parents[2]


def make_pdf(path):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(612, 396))
    c.setFont("Helvetica", 14)
    labels = [("HPF-22204-114.3-A1S-40", 40, 340), ("GHS-22203-168.3-C3S-80", 330, 200), ("DR-22202-33.4-C3S-XXS", 60, 60), ("NORM-24-170", 400, 100)]
    for text, x, y in labels:
        c.drawString(x, y, text)
    c.setFont("Helvetica", 12)
    for i in range(30):
        c.drawString(20 + (i % 10) * 55, 20 + (i // 10) * 12, "WORD")     # filler so the page has a real text layer
    c.save()
    return labels


def test_labels_match_their_positions_and_pixels(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    labels = make_pdf(lib / "s.pdf")
    index = tmp_path / "INDEX.csv"
    with open(index, "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=["sheet_id", "library_file", "operator", "filing_or_project", "text_source", "doc_type"])
        w.writeheader()
        w.writerow(dict(sheet_id="T1", library_file="s.pdf", operator="Test Operator", filing_or_project="x", text_source="text", doc_type="pid"))
    out = tmp_path / "out"
    res = subprocess.run([sys.executable, str(ROOT / "tools/longterm/build_textlayer_crops.py"), "--index", str(index), "--library", str(lib), "--out", str(out),
                          "--sheets", "1", "--per-sheet", "12", "--heldout-fraction", "0"], capture_output=True, text=True, env=dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src")))
    assert res.returncode == 0, res.stderr[-800:]
    items = json.loads((out / "train_proxy.json").read_text())["items"]
    found = {i["text"]: i for i in items if i["category"] in ("LINE_LABEL",)}
    assert {"HPF-22204-114.3-A1S-40", "GHS-22203-168.3-C3S-80", "DR-22202-33.4-C3S-XXS", "NORM-24-170"} <= set(found)
    for text, x, y in labels:                                   # the box of each item sits where that label was drawn (396 high page; y is from the bottom)
        box = found[text]["bbox"]
        assert abs(box["x0"] * 612 - x) < 6 and abs(box["y1"] * 396 - (396 - y)) < 8, (text, box)
    texts = [i["text"] for i in items]
    assert len(set(texts)) > 1 and "WORD" not in {i["text"] for i in items if i["category"] == "LINE_LABEL"}
