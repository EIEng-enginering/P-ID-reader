"""WPU-17: CPU presets, no network, bounded/cancellable stages with safe resume, hostile inputs, export path safety."""
from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf, symbol_sheet_pdf  # noqa: E402

from pid_reader.api import Cancelled, ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import intelligence_store as istore  # noqa: E402
from pid_reader.engineering import symbol_detect as sd  # noqa: E402
from pid_reader.engineering.drawing_export import safe_stem  # noqa: E402
from pid_reader.engineering.pipeline import analyze_drawing  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src" / "pid_reader"
REVX_MODULES = ["page_regions", "stage_telemetry", "intelligence_store", "ocr_adaptive", "engineering_text", "table_parse", "doc_text", "symbol_library", "symbol_detect",
                "vector_network", "engineering_graph", "control_loops", "crosssheet", "intelligence", "ai_prompt", "dexpi_xml", "gold_scoring"]


# ---------------------------------------------------------------- CPU presets
def test_presets_are_ordered_by_cost_and_cover_more_families():
    q, s, d = (sd.PRESETS[k] for k in ("quick", "standard", "deep"))
    assert set(q["families"]) < set(s["families"]) < set(d["families"])
    assert q["coarse_ratio"] > s["coarse_ratio"] > d["coarse_ratio"] and q["fine_step"] > s["fine_step"] > d["fine_step"] and q["threshold"] > s["threshold"] > d["threshold"]
    from pid_reader.engineering import ocr_adaptive as oa
    assert len(oa.PRESETS["quick"]["zero_variants"]) < len(oa.PRESETS["standard"]["zero_variants"]) < len(oa.PRESETS["deep"]["zero_variants"])


def test_unknown_preset_is_refused_everywhere():
    pdf = symbol_sheet_pdf([{"kind": "ball", "x": 300, "y": 200, "s": 22}])
    with pytest.raises(ValueError):
        sd.detect_symbols(pdf, 1, preset="turbo")


# ---------------------------------------------------------------- no network at run time
def test_analysis_and_export_work_with_every_socket_blocked(tmp_path, monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    pdf = symbol_sheet_pdf([{"kind": "ball", "x": 300, "y": 200, "s": 22, "tag": "XV-1"}])
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="n.pdf"), source_pdf_bytes=pdf)
        out = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
        from pid_reader.engineering.intelligence import export_package
        (tmp_path / "o").mkdir()
        assert export_package(db, eid, tmp_path / "o").exists() and out["health"]["drawing_status"]


@pytest.mark.parametrize("module", REVX_MODULES)
def test_new_modules_import_no_network_or_shell_libraries(module):
    text = (SRC / "engineering" / f"{module}.py").read_text(encoding="utf-8")
    for banned in (r"^\s*(?:import|from)\s+(?:requests|urllib|http|socket|ftplib|smtplib|subprocess|webbrowser|xmlrpc)\b",):
        assert not re.search(banned, text, re.M), (module, banned)
    assert "os.system" not in text and "eval(" not in text and "exec(" not in text and "pickle" not in text


def test_new_modules_do_not_import_qt():
    for module in REVX_MODULES + ["standalone_intelligence"]:
        path = SRC / ("standalone_intelligence.py" if module == "standalone_intelligence" else f"engineering/{module}.py")
        assert "PySide6" not in path.read_text(encoding="utf-8"), module


# ---------------------------------------------------------------- cancellation at every stage, safe resume
class CancelAfter:
    def __init__(self, n):
        self.n, self.calls = n, 0

    def check(self):
        self.calls += 1
        if self.calls > self.n:
            raise Cancelled()


def test_cancel_at_each_point_leaves_a_consistent_project_and_the_rerun_completes(tmp_path):
    pdf = symbol_sheet_pdf([{"kind": "gate", "x": 150, "y": 200, "s": 22, "tag": "HV-1"}, {"kind": "ball", "x": 400, "y": 200, "s": 22}])
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="c.pdf"), source_pdf_bytes=pdf)
        cancelled = 0
        for n in (0, 1, 2, 4, 7, 11):
            try:
                analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True, cancel=CancelAfter(n))
            except Cancelled:
                cancelled += 1
            assert db.verify_audit_chain()
            assert db.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert cancelled >= 4
        runs_before = db.db.execute("SELECT COUNT(*) FROM intelligence_run").fetchone()[0]
        assert runs_before == 0, "a cancelled run records nothing half-finished"
        out = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
        assert out["run_id"] and out["health"]["drawing_status"] != "FAILED"
        again = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
        assert again["run_id"] == out["run_id"]                            # idempotent resume


# ---------------------------------------------------------------- hostile and malformed inputs
@pytest.mark.parametrize("blob", [b"", b"%PDF-1.4\n", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer<<>>\n%%EOF", b"not a pdf at all", b"%PDF-" + b"\x00" * 2000])
def test_malformed_bytes_fail_closed_with_an_exception_not_a_hang(blob):
    with pytest.raises(Exception):
        sd.detect_symbols(blob, 1, preset="quick")


def test_page_regions_and_vector_network_refuse_garbage():
    from pid_reader.engineering.page_regions import analyse_pages
    from pid_reader.engineering.vector_network import analyze_vector_network
    for fn in (lambda: analyse_pages(b"%PDF-garbage"), lambda: analyze_vector_network(b"%PDF-garbage", 1)):
        with pytest.raises(Exception):
            fn()


def test_oversized_page_is_tiled_within_bounded_tile_count_not_rendered_whole():
    pdf = symbol_sheet_pdf([{"kind": "ball", "x": 1500, "y": 1000, "s": 40, "pipe": False}], size=(3400.0, 2400.0))
    res = sd.detect_symbols(pdf, 1, preset="quick", tile_px=1800, overlap_px=300)
    assert res["tiles_total"] > 1 and res["tiles_processed"] <= sd.MAX_TILES and res["status"] in ("COMPLETE_CANDIDATES", "PARTIAL")


# ---------------------------------------------------------------- export path safety
@pytest.mark.parametrize("hostile", ["..\\..\\evil.pdf", "../../etc/passwd.pdf", "C:\\Windows\\system32\\x.pdf", "a/b/c.pdf", "CON.pdf", "NUL.pdf", "x" * 400 + ".pdf", "..pdf", "<>:\"|?*.pdf"])
def test_hostile_file_names_cannot_escape_the_chosen_folder(hostile):
    stem = safe_stem(hostile)
    assert stem and "/" not in stem and "\\" not in stem and ".." not in stem.replace("...", "") and len(stem) <= 150
    assert not re.search(r'[<>:"|?*]', stem) and stem.split(".")[0].upper() not in ("CON", "NUL", "PRN", "AUX")


def test_package_for_a_hostile_filename_stays_inside_the_folder(tmp_path):
    pdf = sheet_pdf(body_words=60)
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="..\\..\\outside\\evil.pdf"), source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine=None)
        from pid_reader.engineering.intelligence import export_package
        dest = tmp_path / "chosen"
        dest.mkdir()
        pkg = export_package(db, eid, dest)
    assert pkg.resolve().parent == dest.resolve()
    assert not (tmp_path / "outside").exists()
    inside = [p for p in pkg.rglob("*") if p.is_file()]
    assert inside and all(pkg.resolve() in p.resolve().parents for p in inside)


def test_decisions_cannot_claim_safety_or_verification():
    with ProjectStore(":memory:") as db:                                   # no extraction needed: the vocabulary guard fires first
        for bad in ("VERIFIED_PLANT", "SIL_ASSIGNED", "IPL_CREDITED", "APPROVED"):
            with pytest.raises(ValueError):
                istore.add_decision(db, "x", "i", actor="R", decision=bad, reason="x")
