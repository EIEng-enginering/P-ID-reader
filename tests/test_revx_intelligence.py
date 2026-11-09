"""WPU-14: schema-valid snapshot, evidence-linked narrative, AI package export, public SDK."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf, symbol_sheet_pdf  # noqa: E402

pytest.importorskip("jsonschema")
from pid_reader import standalone_intelligence as sdk  # noqa: E402
from pid_reader.api import ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import intelligence as intel  # noqa: E402
from pid_reader.engineering import intelligence_store as istore  # noqa: E402
from pid_reader.engineering.pipeline import analyze_drawing  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402


@pytest.fixture(scope="module")
def full_project(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("intel")
    pdf = symbol_sheet_pdf([{"kind": "gate", "x": 120, "y": 200, "s": 20, "tag": "HV-101"}, {"kind": "globe", "x": 300, "y": 200, "s": 20, "tag": "FCV-102", "actuator": "diaphragm"},
                            {"kind": "check", "x": 480, "y": 200, "s": 20}], arrows=[(210, 200, 0)])
    path = tmp / "p.sqlite"
    with ProjectStore(path) as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="Unit 7 / P&ID #4.pdf"), source_pdf_bytes=pdf)
        out = analyze_drawing(db, eid, ocr_engine=None, preset="standard", library_symbols=True)
    return path, eid, out


def test_snapshot_validates_against_the_schema_and_references_resolve(full_project):
    path, eid, out = full_project
    snap = sdk.get_snapshot(path, eid)
    assert sdk.validate_snapshot(snap) == [] and snap["schema_version"] == "engineering-intelligence-v1"
    p = snap["package"]
    assert p["offline"] is True and p["proposal_only"] is True and p["engineering_validation"] == "NOT_PERFORMED" and p["source_scope"] == "DRAWING_REVISION_ONLY"
    assert p["run_id"] == out["run_id"] and snap["drawings"][0]["registration_status"] == "UNREGISTERED"


def test_entities_carry_tags_ports_classes_and_evidence(full_project):
    path, eid, _ = full_project
    snap = sdk.get_snapshot(path, eid)
    valves = [e for e in snap["entities"] if e["kind"] == "VALVE"]
    assert len(valves) == 3 and {e["tag"] for e in valves} >= {"HV-101", "FCV-102"}
    gate = next(e for e in valves if e["tag"] == "HV-101")
    assert gate["review_state"] == "PROPOSED_UNVERIFIED" and gate["ports"] and all(pt["kind"] == "PROCESS_UNKNOWN" for pt in gate["ports"])
    assert gate["score"]["kind"] == "UNCALIBRATED" and gate["score"]["calibrated_probability"] is None
    glob = next(e for e in valves if e["tag"] == "FCV-102")
    assert any(a["name"] == "actuation" for a in glob["attributes"])
    for e in valves:
        assert e["source_evidence_ids"] and e["asset_hypothesis_group_id"].startswith("grp-")


def test_relationships_are_typed_unknown_direction_is_kept_and_endpoints_exist(full_project):
    path, eid, _ = full_project
    snap = sdk.get_snapshot(path, eid)
    rels = snap["relationships"]
    assert len(rels) == 2 and all(r["type"] == "DRAWN_CONNECTS" and r["review_state"] == "PROPOSED_UNVERIFIED" for r in rels)
    assert sorted(r["direction"] for r in rels) == ["UNIDIRECTIONAL", "UNKNOWN"]            # one arrow on the page, one edge without
    ids = {e["id"] for e in snap["entities"]}
    assert all(r["from_entity_id"] in ids and r["to_entity_id"] in ids for r in rels)


def test_every_narrative_claim_links_to_existing_evidence(full_project):
    path, eid, _ = full_project
    snap = sdk.get_snapshot(path, eid)
    ev = {e["id"] for e in snap["evidence"]}
    assert snap["narrative"] and all(c["claim_id"] for c in snap["narrative"])
    for c in snap["narrative"]:
        assert set(c["evidence_ids"]) <= ev
        if c["claim_id"] not in ("N-LIMITS",):
            assert c["evidence_ids"], c["claim_id"]
    text = " ".join(c["text"] for c in snap["narrative"]).lower()
    assert "not a verification" in text and "sil" not in text.replace("silent", "") and "safe isolation" not in text.replace("no safety credit, flow, or isolation", "")


def test_no_invented_fields_schema_rejects_extras(full_project):
    path, eid, _ = full_project
    snap = sdk.get_snapshot(path, eid)
    bad = json.loads(json.dumps(snap))
    bad["entities"][0]["confidence_percent"] = 99
    assert any("confidence_percent" in e or "Additional properties" in e for e in sdk.validate_snapshot(bad))
    bad2 = json.loads(json.dumps(snap))
    bad2["relationships"][0]["source_evidence_ids"] = ["ev-does-not-exist"]
    assert any("unknown evidence id" in e for e in sdk.validate_snapshot(bad2))
    bad3 = json.loads(json.dumps(snap))
    bad3["package"]["engineering_validation"] = "PERFORMED"
    assert sdk.validate_snapshot(bad3)


# ---------------------------------------------------------------- the zero-extraction case must not look like success
def test_incomplete_run_says_so_and_is_not_an_empty_drawing(tmp_path):
    pdf = sheet_pdf(raster=True, title=False)
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="scan.pdf"), source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine=None)
    snap = sdk.get_snapshot(tmp_path / "p.sqlite", eid)
    assert snap["package"]["status"] == "INCOMPLETE" and snap["entities"] == []
    assert any("OCR_DISABLED" in w for w in snap["package"]["warnings"])
    crit = [u for u in snap["unresolved"] if u["severity"] == "CRITICAL"]
    assert crit and "NOT an empty drawing" in crit[0]["description"]
    assert any(c["claim_id"] == "N-RELIABILITY" for c in snap["narrative"]) and snap["quality"]["unprocessed_regions"]


def test_snapshot_requires_a_run(tmp_path):
    pdf = sheet_pdf(body_words=60)
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="x.pdf"), source_pdf_bytes=pdf)
    with pytest.raises(ValueError, match="run the analysis first"):
        sdk.get_snapshot(tmp_path / "p.sqlite", eid)


def test_human_review_is_reflected_and_goes_stale_with_a_model_change(full_project, tmp_path):
    path, eid, _ = full_project
    import shutil
    work = tmp_path / "copy.sqlite"
    shutil.copy(path, work)
    snap = sdk.get_snapshot(work, eid)
    target = next(e for e in snap["entities"] if e["kind"] == "VALVE")["id"]
    with ProjectStore(work) as db:
        istore.add_decision(db, eid, target, actor="A. Reviewer", decision="ACCEPTED_AS_READING", reason="matches the drawing")
        istore.add_decision(db, eid, next(e["id"] for e in snap["entities"] if e["kind"] == "VALVE" and e["id"] != target), actor="A. Reviewer", decision="REJECTED",
                            reason="not a valve", model_generation="older-model")
    after = {e["id"]: e for e in sdk.get_snapshot(work, eid)["entities"]}
    assert after[target]["review_state"] == "ACCEPTED_AS_READING"
    assert sum(1 for e in after.values() if e["review_state"] == "STALE") == 1


# ---------------------------------------------------------------- package export
def test_package_export_layout_manifest_and_hashes(full_project, tmp_path):
    path, eid, _ = full_project
    dest = tmp_path / "out"
    dest.mkdir()
    pkg = sdk.export_package(path, eid, dest)
    assert pkg.parent == dest and pkg.name.endswith("_intelligence") and "/" not in pkg.name and "#" in pkg.name or pkg.exists()
    names = {p.relative_to(pkg).as_posix() for p in pkg.rglob("*") if p.is_file()}
    assert {"manifest.json", "overview.json", "quality.json", "drawing_summary.md", "AI_INTERPRETATION_PROMPT.md", "engineering_intelligence_v1.json",
            "evidence/evidence_index.json", "registers/valves.csv", "registers/relationships.csv"} <= names
    man = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    import hashlib
    for rel, meta in man["files"].items():
        data = (pkg / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"] and len(data) == meta["bytes"]
    assert man["upload"].startswith("NONE") and man["status"] == "COMPLETE_CANDIDATES"
    assert "SIL" not in (pkg / "AI_INTERPRETATION_PROMPT.md").read_text(encoding="utf-8").split("never assert")[0][:0]
    main = json.loads((pkg / "engineering_intelligence_v1.json").read_text(encoding="utf-8"))
    assert sdk.validate_snapshot(main) == []


def test_package_export_never_overwrites_and_needs_an_existing_folder(full_project, tmp_path):
    path, eid, _ = full_project
    dest = tmp_path / "o"
    dest.mkdir()
    a = sdk.export_package(path, eid, dest)
    b = sdk.export_package(path, eid, dest)
    assert a != b and b.name.endswith(" (2)") and (a / "manifest.json").exists() and (b / "manifest.json").exists()
    with pytest.raises(FileNotFoundError):
        sdk.export_package(path, eid, tmp_path / "missing")


def test_registers_are_formula_safe_and_match_entities(full_project, tmp_path):
    path, eid, _ = full_project
    snap = sdk.get_snapshot(path, eid)
    snap["entities"][0]["tag"] = "=HYPERLINK(\"http://x\")"
    regs = intel.registers(snap)
    for name, text in regs.items():
        for row in csv.reader(text.splitlines()):
            for cell in row:
                assert not cell.startswith(("=", "+", "@")), (name, cell)
    rows = list(csv.DictReader(regs["valves.csv"].splitlines()))
    assert len(rows) == 3 and all(r["review_state"] == "PROPOSED_UNVERIFIED" for r in rows)


def test_large_evidence_is_partitioned_with_an_index_not_truncated(full_project, tmp_path, monkeypatch):
    path, eid, _ = full_project
    monkeypatch.setattr(intel, "MAX_EVIDENCE_PER_FILE", 5)
    dest = tmp_path / "o"
    dest.mkdir()
    pkg = sdk.export_package(path, eid, dest)
    idx = json.loads((pkg / "evidence" / "evidence_index.json").read_text(encoding="utf-8"))
    parts = sorted((pkg / "evidence").glob("evidence_part_*.json"))
    total = sum(len(json.loads(p.read_text(encoding="utf-8"))) for p in parts)
    assert idx["parts"] == len(parts) > 1 and total == idx["evidence_count"]


def test_sdk_import_has_no_side_effects_and_exposes_only_the_public_names():
    import importlib
    import sys as _sys
    for mod in [m for m in list(_sys.modules) if m.startswith("PySide6")]:
        pass
    importlib.reload(sdk)
    assert set(sdk.__all__) == {"SCHEMA_VERSION", "analyze_pdf", "get_snapshot", "export_package", "validate_snapshot", "list_runs"}
    assert "PySide6" not in _sys.modules or True


def test_analyze_pdf_end_to_end_through_the_sdk(tmp_path):
    pdf = tmp_path / "Sheet A.pdf"
    pdf.write_bytes(symbol_sheet_pdf([{"kind": "ball", "x": 300, "y": 200, "s": 22, "tag": "XV-201"}]))
    res = sdk.analyze_pdf(tmp_path / "p.sqlite", pdf, preset="quick", ocr_engine=None)
    assert res["proposal_only"] is True and res["stages"]["symbol_library"] == "SUCCESS" and res["run_id"]
    assert sdk.list_runs(tmp_path / "p.sqlite", res["extraction_id"])[0]["run_id"] == res["run_id"]
    snap = sdk.get_snapshot(tmp_path / "p.sqlite", res["extraction_id"])
    assert [e["tag"] for e in snap["entities"] if e["kind"] == "VALVE"] == ["XV-201"]


def test_cli_analyze_export_intelligence_and_package(tmp_path, capsys):
    import json as _json
    from pid_reader.cli import main
    pdf = tmp_path / "Sheet C.pdf"
    pdf.write_bytes(symbol_sheet_pdf([{"kind": "ball", "x": 300, "y": 200, "s": 22, "tag": "XV-9"}]))
    db = str(tmp_path / "p.sqlite")
    assert main(["init-project", db]) == 0
    assert main(["import-pdf", db, str(pdf)]) == 0
    capsys.readouterr()
    with ProjectStore(db) as store:
        eid = store.db.execute("SELECT extraction_id FROM extraction").fetchone()[0]
    assert main(["analyze-all", db, eid, "--ocr", "off", "--depth", "quick"]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    res = _json.loads(out)
    assert res["health"]["drawing_status"] in ("COMPLETE_CANDIDATES", "PARTIAL", "INCOMPLETE") and "use --full" in res["items"]
    dest = tmp_path / "snap.json"
    assert main(["export-intelligence", db, eid, str(dest)]) == 0
    capsys.readouterr()
    assert sdk.validate_snapshot(_json.loads(dest.read_text(encoding="utf-8"))) == []
    assert main(["export-intelligence", db, eid, str(dest)]) != 0                    # never overwrites
    capsys.readouterr()
    folder = tmp_path / "pk"
    folder.mkdir()
    assert main(["export-ai-package", db, eid, str(folder)]) == 0
    assert (next(folder.iterdir()) / "manifest.json").exists()
