"""WP-01..03 integration into the current repository: per-page layout, frame-aware detector ingestion, review sidecar helpers, CLI and the Windows tab.

All evidence here is synthetic; nothing measures engineering accuracy.
"""
from __future__ import annotations

import json
import os
import time
from io import BytesIO
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from reportlab.pdfgen.canvas import Canvas  # noqa: E402

from pid_reader.engineering import wp123_recovery as R  # noqa: E402
from pid_reader.engineering import wp123_session as S  # noqa: E402


def w(i, text, x0, y0, x1, y1, page=1):
    return {"id": i, "text": text, "page": page, "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}, "raw_score": 0.95, "review_state": "PROPOSED_UNVERIFIED"}


def pdf_two_pages() -> bytes:
    s = BytesIO()
    c = Canvas(s, pagesize=(600, 400))
    for _ in range(2):
        c.setFont("Helvetica", 14)
        c.drawString(100, 300, "FE-2202")
        c.drawString(300, 200, "V-2201")
        c.showPage()
    c.save()
    return s.getvalue()


def test_regions_are_inferred_per_page_and_page_one_is_unchanged():
    title = [w("a", "PIPING", .1, .9, .2, .93), w("b", "DRAWING", .3, .9, .4, .93)]
    p1 = R.infer_regions(title, profile="auto")
    assert [r["page"] for r in p1] == [1]
    mixed = title + [w("c", "FE-2202", .3, .3, .4, .33, page=2)]
    regs = R.infer_regions(mixed, profile="auto")
    assert [r["page"] for r in regs] == [1]                       # page 2 has no title words: page 1's layout is not borrowed
    both = R.infer_regions(mixed + [w("d", "PIPING", .1, .9, .2, .93, page=2), w("e", "REVISION", .3, .9, .4, .93, page=2)], profile="auto")
    assert sorted(r["page"] for r in both) == [1, 2]
    s418 = R.infer_regions([w("x", "A", .5, .5, .52, .52)], profile="s418")
    assert [(r["type"], r["page"]) for r in s418] == [("DOCUMENT_METADATA_REGION", 1), ("DRAWING_FRAME", 1), ("DRAWING_FRAME", 1)]
    assert R.infer_regions([], profile="auto") == []


def test_detector_boxes_are_mapped_from_render_frame_to_media_frame():
    class Frame:                                                  # rendered frame = media frame mirrored left-right
        def bbox_to_media(self, b):
            return {"x0": round(1 - b["x1"], 7), "x1": round(1 - b["x0"], 7), "y0": b["y0"], "y1": b["y1"]}
    det = [{"id": "d1", "bbox": {"x0": .1, "y0": .2, "x1": .3, "y1": .4}, "raw_score": .9, "coarse_class": "valve", "page": 1}]
    kept = R.normalise_detections(det, page_frame=Frame(), render_frame=True)
    assert kept[0]["bbox"] == {"x0": .7, "x1": .9, "y0": .2, "y1": .4}
    plain = R.normalise_detections(det)                           # without a frame the Rev X behaviour (already media) is kept
    assert plain[0]["bbox"] == {"x0": .1, "x1": .3, "y0": .2, "y1": .4}


def test_read_detectors_maps_a_tr1_record_through_the_page_frame(tmp_path):
    class Frame:
        def bbox_to_media(self, b):
            return {"x0": b["y0"], "x1": b["y1"], "y0": b["x0"], "y1": b["x1"]}
    rec = {"schema": "pid-tr1-detections/1", "source_sha256": "a" * 64,
           "detections": [{"id": "d1", "bbox": {"x0": .1, "y0": .5, "x1": .2, "y1": .6}, "raw_score": .8, "coarse_class": "valve"}]}
    f = tmp_path / "rec.json"
    f.write_text(json.dumps(rec))
    got = R.read_detectors(f, expected_source_sha256="a" * 64, page_frame=Frame())
    assert got[0]["bbox"] == {"x0": .5, "x1": .6, "y0": .1, "y1": .2}
    with pytest.raises(ValueError):
        R.read_detectors(f, expected_source_sha256="b" * 64, page_frame=Frame())


def _result():
    words = [w("o1", "FE-2202", .30, .30, .36, .32), w("o2", "V-2201", .50, .50, .55, .52), w("o3", "PF-00019-14.3-A3S-40", .1, .1, .3, .12),
             w("o4", "HPF-22204-114.3--AS-40", .1, .2, .3, .22)]
    dets = [{"id": "frc-1", "bbox": {"x0": .29, "y0": .33, "x1": .37, "y1": .40}, "raw_score": .95, "coarse_class": "instrumentation", "page": 1,
             "model_confidence_status": "LEADING"}]
    return R.recover_wp123(pdf_two_pages(), words, dets, profile="none")


def test_register_rows_fold_in_the_newest_decision_and_keep_the_chain(tmp_path):
    res = _result()
    sc = S.Wp123Sidecar(tmp_path / "wp.sqlite")
    try:
        aid = sc.add(res)
        doc, rows = sc.rows(aid)
        readings = [r for r in rows if r["group"] == S.GROUPS[0]]
        assert {r["text"] for r in readings} >= {"FE-2202", "V-2201"}
        assert all(r["decision"] is None and r["state_text"] == "Proposed (not reviewed)" for r in rows)
        assert all(r["page"] == 1 for r in rows)
        det_rows = [r for r in rows if r["group"] == S.GROUPS[4]]
        assert det_rows and det_rows[0]["evidence"]
        target = next(r for r in readings if r["text"] == "FE-2202")
        sc.decide(aid, target["id"], "accept", actor="Tester One", reason="Matches printed label")
        sc.decide(aid, target["id"], "correct", actor="Tester One", reason="Zero not letter O", corrected_text="FE-2202A")
        _doc, rows2 = sc.rows(aid)
        t2 = next(r for r in rows2 if r["id"] == target["id"])
        assert t2["decision"] == "CORRECTED_READING" and t2["corrected_text"] == "FE-2202A" and t2["decided_by"] == "Tester One"
        assert len(sc.store.decisions(aid)) == 2                  # both decisions remain: append-only
        assert sc.verify() == []
        with pytest.raises(ValueError):
            sc.decide(aid, target["id"], "reject", actor="", reason="x")
        with pytest.raises(ValueError):
            sc.decide(aid, target["id"], "correct", actor="T", reason="r")        # corrected text required
        with pytest.raises(ValueError):
            sc.decide(aid, "no-such-target", "reject", actor="T", reason="r")
        assert sc.latest_analysis_for(res["source_sha256"]) == aid
    finally:
        sc.close()


def test_store_default_path_is_outside_the_repository_and_overridable(monkeypatch, tmp_path):
    monkeypatch.delenv("PID_WP123_STORE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert S.default_store_path() == tmp_path / "PIDReader" / "wp123" / "wp123_review.sqlite"
    monkeypatch.setenv("PID_WP123_STORE", str(tmp_path / "x.sqlite"))
    assert S.default_store_path() == tmp_path / "x.sqlite"


def test_cli_recover_and_review_roundtrip(tmp_path, capsys):
    from pid_reader.cli import main
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(pdf_two_pages())
    csv = tmp_path / "ocr.csv"
    csv.write_text("ocr_id,text,score,x0,y0,x1,y1\no1,FE-2202,0.95,0.17,0.2,0.26,0.25\n", encoding="utf-8")
    out, db = tmp_path / "out", tmp_path / "wp.sqlite"
    rc = main(["recover-wp123", str(pdf), "--ocr-csv", str(csv), "--region-profile", "none", "--output-dir", str(out), "--store-database", str(db)])
    assert rc == 0
    info = json.loads(capsys.readouterr().out)
    assert info["summary"]["readings_proposed"] == 1 and info["summary"]["reviewed_engineering_objects"] == 0
    from pid_reader.engineering.wp123_store import WP123Store
    with WP123Store(db) as st:
        target = st.get(info["analysis_id"])["readings"][0]["id"]
    assert main(["wp123-review", str(db), info["analysis_id"], target, "--actor", "A B", "--reason", "checked", "--decision", "ACCEPTED_AS_READING"]) == 0
    capsys.readouterr()
    assert main(["wp123-audit", str(db)]) == 0
    assert (out / "wp123_result.json").is_file()
    import subprocess, sys
    root = Path(__file__).resolve().parents[1]
    chk = subprocess.run([sys.executable, str(root / "tools" / "check_wp123.py"), str(out / "wp123_result.json"), "--source", str(pdf)], capture_output=True, text=True)
    assert chk.returncode == 0, chk.stdout + chk.stderr
