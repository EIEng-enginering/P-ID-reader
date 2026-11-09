"""R5 update, change 5: reversible OFF / SHADOW / ON through the real pipeline and package export."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

pytest.importorskip("jsonschema")
from pid_reader.api import ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import intelligence as intel  # noqa: E402
from pid_reader.engineering import intelligence_store as istore  # noqa: E402
from pid_reader.engineering.pipeline import analyze_drawing  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402

FEATURES = ("DEXPI", "PAGE_FRAME", "REVIEW_LEDGER")


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 9, 1, 2, 3, tzinfo=tz or timezone.utc)


@pytest.fixture()
def clean_env(monkeypatch):
    for n in FEATURES:
        monkeypatch.delenv("PID_R5_" + n, raising=False)
    monkeypatch.setattr(intel, "datetime", _Clock)
    return monkeypatch


def analyse(tmp_path, name, **kw):
    pdf = sheet_pdf(title=True, notes=True)
    db = ProjectStore(tmp_path / (name + ".sqlite"))
    eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="Unit.pdf"), source_pdf_bytes=pdf)
    out = analyze_drawing(db, eid, ocr_engine=None, preset="quick", **kw)
    return db, eid, out


def tree(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_all_off_pipeline_and_package_carry_nothing_new(tmp_path, clean_env):
    db, eid, out = analyse(tmp_path, "off")
    assert "r5_shadow" not in out
    summary = json.loads(db.db.execute("SELECT summary_json FROM intelligence_run WHERE run_id=?", (out["run_id"],)).fetchone()[0])
    assert "page_provenance" not in summary
    dest = tmp_path / "o"
    dest.mkdir()
    pkg = intel.export_package(db, eid, dest)
    files = tree(pkg)
    assert not any(k.startswith("review/") or k == "page_provenance.json" for k in files)
    assert "r5_update" not in json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert [p.name for p in dest.iterdir()] == [pkg.name]                          # no shadow folder either
    db.close()


def test_shadow_leaves_the_package_byte_identical_and_writes_a_separate_folder(tmp_path, clean_env):
    db, eid, out = analyse(tmp_path, "s")
    d_off, d_sh = tmp_path / "off", tmp_path / "sh"
    d_off.mkdir(), d_sh.mkdir()
    off = tree(intel.export_package(db, eid, d_off))
    clean_env.setenv("PID_R5_REVIEW_LEDGER", "shadow")
    clean_env.setenv("PID_R5_PAGE_FRAME", "shadow")
    pkg = intel.export_package(db, eid, d_sh)
    assert tree(pkg) == off                                                       # the authoritative package is unchanged, byte for byte
    shadow = d_sh / (pkg.name + "__r5_shadow")
    assert shadow.is_dir() and sorted(tree(shadow)) == ["page_provenance.json", "review/connection_review_ledger.json"]
    assert not any(k.startswith("review/") for k in tree(pkg))
    db.close()


def test_on_adds_only_the_new_files_and_a_manifest_note(tmp_path, clean_env):
    db, eid, out = analyse(tmp_path, "on")
    d_off, d_on = tmp_path / "off", tmp_path / "on"
    d_off.mkdir(), d_on.mkdir()
    off = tree(intel.export_package(db, eid, d_off))
    clean_env.setenv("PID_R5_REVIEW_LEDGER", "on")
    clean_env.setenv("PID_R5_PAGE_FRAME", "on")
    pkg = intel.export_package(db, eid, d_on)
    on = tree(pkg)
    added = sorted(set(on) - set(off))
    assert added == ["page_provenance.json", "review/connection_review_ledger.json"]
    changed = sorted(k for k in off if off[k] != on[k])
    assert changed == ["manifest.json"]                                          # nothing else changes
    man = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert man["r5_update"]["features"] == {"REVIEW_LEDGER": "ON", "PAGE_FRAME": "ON"} and "never topology" in man["r5_update"]["note"]
    led = json.loads((pkg / "review" / "connection_review_ledger.json").read_text(encoding="utf-8"))
    assert led["note"].startswith("Candidates for human review only")
    snap = json.loads((pkg / "engineering_intelligence_v1.json").read_text(encoding="utf-8"))
    assert not any(r["id"].startswith("rvw-") for r in snap["relationships"])
    assert intel.validate_snapshot(snap) == []
    db.close()


def test_page_frame_on_records_provenance_with_the_run_and_off_does_not(tmp_path, clean_env):
    clean_env.setenv("PID_R5_PAGE_FRAME", "on")
    db, eid, out = analyse(tmp_path, "pf")
    summary = json.loads(db.db.execute("SELECT summary_json FROM intelligence_run WHERE run_id=?", (out["run_id"],)).fetchone()[0])
    pp = summary["page_provenance"]
    assert pp["status"] == "OK" and pp["pages"][0]["physical_measurements_allowed"] is False and pp["pages"][0]["geometry_rescaled"] is False
    db.close()


def test_page_frame_shadow_returns_provenance_but_stores_nothing(tmp_path, clean_env):
    clean_env.setenv("PID_R5_PAGE_FRAME", "shadow")
    db, eid, out = analyse(tmp_path, "pfs")
    assert out["r5_shadow"]["page_provenance"]["status"] == "OK"
    summary = json.loads(db.db.execute("SELECT summary_json FROM intelligence_run WHERE run_id=?", (out["run_id"],)).fetchone()[0])
    assert "page_provenance" not in summary
    db.close()


def test_on_does_not_change_the_analysis_itself(tmp_path, clean_env):
    """Same drawing, flags OFF vs ON: identical stage outcomes' counts and identical items (only the optional provenance differs)."""
    db1, e1, o1 = analyse(tmp_path, "a")
    clean_env.setenv("PID_R5_PAGE_FRAME", "on")
    clean_env.setenv("PID_R5_REVIEW_LEDGER", "on")
    db2, e2, o2 = analyse(tmp_path, "b")
    assert o1["counts"] == o2["counts"] and o1["health"]["drawing_status"] == o2["health"]["drawing_status"]
    assert [i["item_id"] for i in o1["items"]] == [i["item_id"] for i in o2["items"]]
    db1.close(), db2.close()


def test_no_schema_migration_or_new_table_is_needed(tmp_path, clean_env):
    clean_env.setenv("PID_R5_PAGE_FRAME", "on")
    clean_env.setenv("PID_R5_REVIEW_LEDGER", "on")
    db, eid, out = analyse(tmp_path, "m")
    assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0] == "13"
    names = {r[0] for r in db.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any("r5" in n or "ledger" in n or "review_candidate" in n for n in names)
    db.close()


# ------------------------------------------------------------------ end to end: real detection -> reviewed reading -> proposed DEXPI
def test_end_to_end_from_a_detected_drawing_to_a_checked_proposed_export(tmp_path, clean_env):
    from revx_fixtures import symbol_sheet_pdf
    from pid_reader.engineering import dexpi_proposed as dp
    from pid_reader.engineering.intelligence import build_snapshot
    pdf = symbol_sheet_pdf([{"kind": "ball", "x": 120, "y": 200, "s": 20, "tag": "XV-101"}, {"kind": "globe", "x": 300, "y": 200, "s": 20, "tag": "FV-102"}])
    db = ProjectStore(tmp_path / "e2e.sqlite")
    eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="Line 4.pdf"), source_pdf_bytes=pdf)
    out = analyze_drawing(db, eid, ocr_engine=None, preset="standard", library_symbols=True)
    snap = build_snapshot(db, eid, out["run_id"])
    valves = [e for e in snap["entities"] if e["kind"] == "VALVE"]
    assert {e["classification"] for e in valves} >= {"BALL_VALVE", "GLOBE_VALVE"}
    # nothing has been reviewed: the default export holds back every class
    _x, side = dp.to_dexpi(snap)
    assert all(f["fate"] == dp.SIDECAR_ONLY for f in side["fates"] if f["kind"] == "entity" and f["id"] in {v["id"] for v in valves})
    # a named human accepts the readings -> the classes are exported, still as proposals
    for v in valves:
        istore.add_decision(db, eid, v["id"], actor="R. Reviewer", decision="ACCEPTED_AS_READING", reason="class confirmed on the drawing")
    snap = build_snapshot(db, eid, out["run_id"])
    assert all(e["review_state"] == "ACCEPTED_AS_READING" for e in snap["entities"] if e["kind"] == "VALVE")
    xml, side = dp.to_dexpi(snap)
    objs, issues = dp.audit_read(xml)
    assert issues == [] and dp.readback(xml, side)["status"] == "PASS"
    # the readings are not on any drawn connection yet, so they stay in the sidecar with that stated reason -- not forced onto a pipe
    f = {x["id"]: x for x in side["fates"] if x["kind"] == "entity"}
    assert all(f[v["id"]]["reason"] == "NOT_ON_ANY_EXPORTED_CONNECTION" for v in valves if v["classification"] in dp.VALVES)
    clean_env.setenv("PID_R5_DEXPI", "on")
    dest = tmp_path / "dx"
    dest.mkdir()
    res = dp.export_dexpi_proposed(snap, dest)
    assert res["checks"]["readback"] == "PASS" and Path(res["xml"]).name == "Line 4.dexpi.xml"
    db.close()
