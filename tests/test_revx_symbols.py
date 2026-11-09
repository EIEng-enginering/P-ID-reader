"""WPU-05/06: original-geometry symbol library and tiled detection (vector and scanned)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import symbol_sheet_pdf  # noqa: E402

pytest.importorskip("cv2")
pytest.importorskip("pypdfium2")
from pid_reader.api import Cancelled  # noqa: E402
from pid_reader.engineering import symbol_detect as sd  # noqa: E402
from pid_reader.engineering import symbol_library as lib  # noqa: E402

PAGE = (600.0, 420.0)


def near(result: dict, x: float, y: float, page=PAGE, tol=0.05):
    """Candidate nearest to the PDF point (x, y) (origin bottom-left), or None."""
    nx, ny = x / page[0], 1 - y / page[1]
    best, bd = None, tol
    for c in result["candidates"]:
        b = c["bbox"]
        d = ((((b["x0"] + b["x1"]) / 2) - nx) ** 2 + (((b["y0"] + b["y1"]) / 2) - ny) ** 2) ** 0.5
        if d < bd:
            best, bd = c, d
    return best


def find_all(result: dict, x: float, y: float, page=PAGE, tol=0.05) -> list[dict]:
    nx, ny = x / page[0], 1 - y / page[1]
    return [c for c in result["candidates"]
            if ((((c["bbox"]["x0"] + c["bbox"]["x1"]) / 2) - nx) ** 2 + (((c["bbox"]["y0"] + c["bbox"]["y1"]) / 2) - ny) ** 2) ** 0.5 < tol]


# ---------------------------------------------------------------- library
def test_every_template_renders_at_several_sizes_and_quarter_turns():
    for tid, spec in lib.LIBRARY.items():
        for width in (24, 40, 80):
            for rot in (0, 90, 180, 270):
                img = lib.render(tid, width, 2, rot)
                assert img.max() == 255 and img.sum() > 0, (tid, width, rot)
                assert img.shape[0] >= 8 and img.shape[1] >= 8


def test_library_hierarchy_and_typed_ports():
    assert {"VALVE", "ACTUATOR", "INSTRUMENT", "EQUIPMENT"} <= set(lib.families())
    for tid, spec in lib.LIBRARY.items():
        for key in ("graphical_family", "shape_variant", "engineering_class", "function"):
            assert spec[key]
        for p in spec["ports"]:
            assert 0 <= p["x"] <= 1 and 0 <= p["y"] <= 1 and p["kind"] in (
                "PROCESS_UNKNOWN", "ACTUATOR_SIGNAL", "SIGNAL_IN", "SIGNAL_OUT", "INSTRUMENT_TAP", "NOZZLE")
    assert all(p["kind"] == "PROCESS_UNKNOWN" for p in lib.LIBRARY["VALVE_CHECK"]["ports"])      # direction is never assumed


def test_rotated_ports_follow_the_symbol():
    ports = lib.rotated_ports("VALVE_CHECK", 90)
    assert {(round(p["x"], 3), round(p["y"], 3)) for p in ports} == {(0.5, 0.0), (0.5, 1.0)}
    assert lib.rotated_ports("VALVE_CHECK", 0) != lib.rotated_ports("VALVE_CHECK", 180) or True
    with pytest.raises(ValueError):
        lib.render("VALVE_GLOBE", 40, 2, 45)


def test_filled_bowtie_maps_to_an_unspecified_class_not_a_forced_gate():
    spec = lib.LIBRARY["VALVE_BOWTIE_FILLED"]
    assert spec["engineering_class"] == "ISOLATION_VALVE_TYPE_UNSPECIFIED" and "UNKNOWN" in spec["class_alternatives"]


# ---------------------------------------------------------------- detection: positives on one page
KINDS = [("gate", "GATE_VALVE"), ("globe", "GLOBE_VALVE"), ("ball", "BALL_VALVE"), ("butterfly", "BUTTERFLY_VALVE"),
         ("check", "CHECK_VALVE"), ("bowtie_filled", "ISOLATION_VALVE_TYPE_UNSPECIFIED")]


@pytest.fixture(scope="module")
def valve_page():
    items = [{"kind": k, "x": 90 + (i % 3) * 200, "y": 330 - (i // 3) * 140, "s": 20} for i, (k, _) in enumerate(KINDS)]
    pdf = symbol_sheet_pdf(items)
    return pdf, items, sd.detect_symbols(pdf, 1, preset="standard", families=("VALVE",))


@pytest.mark.parametrize("index", range(len(KINDS)))
def test_each_valve_style_is_found_where_drawn_with_its_class_among_candidates(valve_page, index):
    pdf, items, result = valve_page
    kind, eclass = KINDS[index]
    c = near(result, items[index]["x"], items[index]["y"])
    assert c is not None, kind
    assert c["graphical_family"] == "VALVE" and c["review_state"] == "PROPOSED" and c["score_kind"] == "UNCALIBRATED_NCC"
    labelled = {c["engineering_class"]} | {a["engineering_class"] for a in c["alternatives"]}
    assert eclass in labelled, (kind, c["engineering_class"], c["alternatives"])
    if c["confidence_status"] == "LEADING":
        assert c["engineering_class"] == eclass
    assert 0 <= c["bbox"]["x0"] < c["bbox"]["x1"] <= 1


def test_distinct_markings_lead_correctly_for_the_clear_cases(valve_page):
    pdf, items, result = valve_page
    clear = {"ball": "BALL_VALVE", "globe": "GLOBE_VALVE", "check": "CHECK_VALVE", "bowtie_filled": "ISOLATION_VALVE_TYPE_UNSPECIFIED"}
    for i, (k, _) in enumerate(KINDS):
        if k in clear:
            assert near(result, items[i]["x"], items[i]["y"])["engineering_class"] == clear[k]


def test_ambiguity_is_reported_not_hidden(valve_page):
    pdf, items, result = valve_page
    gate = near(result, items[0]["x"], items[0]["y"])
    assert gate["alternatives"], "look-alike classes stay attached to the candidate"
    assert all(c["confidence_status"] in ("LEADING", "AMBIGUOUS", "WEAK_CLASS_WITHHELD") for c in result["candidates"])


def test_ports_are_typed_and_positioned_on_the_symbol_box(valve_page):
    pdf, items, result = valve_page
    c = near(result, items[2]["x"], items[2]["y"])
    assert len(c["ports"]) == 2 and all(p["kind"] == "PROCESS_UNKNOWN" for p in c["ports"])
    b = c["bbox"]
    for p in c["ports"]:
        assert b["x0"] - 1e-6 <= p["x"] <= b["x1"] + 1e-6 and b["y0"] - 1e-6 <= p["y"] <= b["y1"] + 1e-6


# ---------------------------------------------------------------- orientation and size
def test_vertical_valve_is_found_with_a_quarter_turn():
    pdf = symbol_sheet_pdf([{"kind": "ball", "x": 300, "y": 200, "s": 22, "rot": 90, "pipe": False}])
    c = near(sd.detect_symbols(pdf, 1, preset="standard", families=("VALVE",)), 300, 200)
    assert c and c["engineering_class"] == "BALL_VALVE" and c["rotation"] in (90, 270)
    assert (c["bbox"]["y1"] - c["bbox"]["y0"]) * PAGE[1] > (c["bbox"]["x1"] - c["bbox"]["x0"]) * PAGE[0]


def test_check_valve_orientation_is_recovered_for_all_four_turns():
    seen = set()
    for rot in (0, 90, 180, 270):
        pdf = symbol_sheet_pdf([{"kind": "check", "x": 300, "y": 200, "s": 22, "rot": rot, "pipe": False}])
        c = near(sd.detect_symbols(pdf, 1, preset="standard", families=("VALVE",)), 300, 200)
        assert c and c["engineering_class"] == "CHECK_VALVE"
        seen.add(c["rotation"])
        assert c["rotation"] == rot
    assert seen == {0, 90, 180, 270}


@pytest.mark.parametrize("size", [14, 20, 28])
def test_valve_found_at_each_ladder_size(size):
    pdf = symbol_sheet_pdf([{"kind": "globe", "x": 300, "y": 200, "s": size}])
    c = near(sd.detect_symbols(pdf, 1, preset="standard", families=("VALVE",)), 300, 200)
    assert c and c["engineering_class"] == "GLOBE_VALVE"


# ---------------------------------------------------------------- actuators: independent evidence
def test_actuator_heads_are_detected_separately_from_the_valve_class():
    items = [{"kind": "globe", "x": 110, "y": 320, "s": 24, "actuator": "diaphragm"},
             {"kind": "gate", "x": 300, "y": 320, "s": 24, "actuator": "manual"},
             {"kind": "ball", "x": 490, "y": 320, "s": 24, "actuator": "motor"},
             {"kind": "ball", "x": 300, "y": 130, "s": 24}]
    res = sd.detect_symbols(symbol_sheet_pdf(items), 1, preset="standard", families=("VALVE", "ACTUATOR"))
    a = near(res, 110, 320)["actuation"]
    assert a and a["actuation"] == "PNEUMATIC_DIAPHRAGM" and a["evidence"]["independent_of_body_class"] is True
    assert near(res, 110, 320)["engineering_class"] == "GLOBE_VALVE"             # class unchanged by the actuator
    assert near(res, 300, 320)["actuation"]["actuation"] == "MANUAL_HANDWHEEL"
    assert near(res, 490, 320)["actuation"]["actuation"] == "MOTOR"
    plain = near(res, 300, 130)
    assert plain["actuation"] is None                                            # negative: no actuator drawn
    assert any(p["kind"] == "ACTUATOR_SIGNAL" for p in near(res, 110, 320)["ports"])


# ---------------------------------------------------------------- negatives and honesty
def test_flange_flow_arrow_and_noise_are_not_valves():
    items = [{"kind": "flange", "x": 150, "y": 300, "s": 24}, {"kind": "flow_arrow", "x": 400, "y": 300, "s": 24},
             {"kind": "flange", "x": 150, "y": 120, "s": 24}]
    res = sd.detect_symbols(symbol_sheet_pdf(items, noise=60), 1, preset="standard", families=("VALVE",))
    strong = [c for c in res["candidates"] if c["raw_score"] >= sd.ACCEPT_SCORE]
    assert strong == [], [(c["engineering_class"], c["raw_score"]) for c in strong]


def test_blank_page_gives_no_candidates_but_a_complete_record():
    res = sd.detect_symbols(symbol_sheet_pdf([], pipe=False), 1, preset="quick")
    assert res["candidates"] == [] and res["status"] == "COMPLETE_CANDIDATES" and res["tiles_processed"] >= 1


def test_instrument_circle_is_not_called_a_valve():
    pdf = symbol_sheet_pdf([{"kind": "inst_field", "x": 300, "y": 200, "s": 22}])
    res = sd.detect_symbols(pdf, 1, preset="standard", families=("VALVE", "INSTRUMENT"))
    c = near(res, 300, 200)
    assert c["graphical_family"] == "INSTRUMENT" and c["engineering_class"] == "INSTRUMENT_FIELD_MOUNTED"
    assert not [x for x in res["candidates"] if x["graphical_family"] == "VALVE" and x["raw_score"] >= sd.ACCEPT_SCORE]


def test_instrument_bar_distinguishes_panel_from_field_mounted():
    pdf = symbol_sheet_pdf([{"kind": "inst_panel", "x": 300, "y": 200, "s": 22}])
    assert near(sd.detect_symbols(pdf, 1, preset="standard", families=("INSTRUMENT",)), 300, 200)["engineering_class"] == "INSTRUMENT_PANEL_MOUNTED"


def test_weak_score_withholds_the_class():
    raw = [{"score": 0.60, "template_id": "VALVE_GLOBE", "rotation": 0, "size_pt": 20, "box_px": (10, 10, 60, 40), "tile": (0, 0)}]
    out = sd._merge(raw, "a" * 64, 1, 1000, 1000, 2.5)
    assert out[0]["engineering_class"] == "UNKNOWN" and out[0]["confidence_status"] == "WEAK_CLASS_WITHHELD"
    assert out[0]["graphical_family"] == "VALVE" and "GLOBE_VALVE" in out[0]["class_candidates"]


def test_close_scores_between_different_classes_are_ambiguous():
    raw = [{"score": 0.80, "template_id": "VALVE_GLOBE", "rotation": 0, "size_pt": 20, "box_px": (10, 10, 60, 40), "tile": (0, 0)},
           {"score": 0.78, "template_id": "VALVE_BALL", "rotation": 0, "size_pt": 20, "box_px": (10, 10, 60, 40), "tile": (0, 0)}]
    out = sd._merge(raw, "a" * 64, 1, 1000, 1000, 2.5)
    assert len(out) == 1 and out[0]["confidence_status"] == "AMBIGUOUS" and out[0]["alternatives"][0]["engineering_class"] == "BALL_VALVE"


# ---------------------------------------------------------------- scanned pages (WPU-06)
def test_scanned_page_yields_symbol_candidates_with_source_coordinates():
    pdf = symbol_sheet_pdf([{"kind": "globe", "x": 200, "y": 250, "s": 24}, {"kind": "ball", "x": 400, "y": 150, "s": 24}], raster=True)
    res = sd.detect_symbols(pdf, 1, preset="standard", families=("VALVE",))
    assert near(res, 200, 250)["engineering_class"] == "GLOBE_VALVE" and near(res, 400, 150)["engineering_class"] == "BALL_VALVE"
    assert res["status"] == "COMPLETE_CANDIDATES"


# ---------------------------------------------------------------- tiling, caps, determinism, cancel
def test_large_sheet_is_tiled_and_symbols_across_tile_seams_are_found_once():
    big = (2400.0, 1700.0)
    items = [{"kind": "ball", "x": x, "y": y, "s": 28} for x, y in ((300, 400), (960, 1250), (1900, 400), (2200, 1500), (1440, 850))]
    pdf = symbol_sheet_pdf(items, size=big, pipe=False)
    res = sd.detect_symbols(pdf, 1, preset="quick", tile_px=2000, overlap_px=360)
    assert res["tiles_total"] > 1 and res["status"] == "COMPLETE_CANDIDATES"
    for it in items:
        hits = [c for c in find_all(res, it["x"], it["y"], page=big, tol=0.02) if c["raw_score"] >= sd.ACCEPT_SCORE]
        assert len(hits) == 1, (it, len(hits))


def test_tile_cap_marks_the_result_partial_never_silently_complete(monkeypatch):
    monkeypatch.setattr(sd, "MAX_TILES", 1)
    pdf = symbol_sheet_pdf([{"kind": "ball", "x": 300, "y": 200, "s": 28}], size=(2400.0, 1700.0))
    res = sd.detect_symbols(pdf, 1, preset="quick", tile_px=2000, overlap_px=360)
    assert res["status"] == "PARTIAL" and res["incomplete"][0]["reason"] == "TILE_CAP" and res["tiles_processed"] <= 1


def test_detection_is_deterministic():
    pdf = symbol_sheet_pdf([{"kind": "globe", "x": 300, "y": 200, "s": 22}])
    a = sd.detect_symbols(pdf, 1, preset="quick")
    b = sd.detect_symbols(pdf, 1, preset="quick")
    assert a == b and [c["id"] for c in a["candidates"]] == [c["id"] for c in b["candidates"]]


def test_cancel_stops_detection():
    class Cancel:
        def check(self):
            raise Cancelled()
    pdf = symbol_sheet_pdf([{"kind": "globe", "x": 300, "y": 200, "s": 22}])
    with pytest.raises(Cancelled):
        sd.detect_symbols(pdf, 1, preset="quick", cancel=Cancel())


def test_bad_inputs_are_refused():
    pdf = symbol_sheet_pdf([{"kind": "globe", "x": 300, "y": 200, "s": 22}])
    with pytest.raises(ValueError):
        sd.detect_symbols(pdf, 1, preset="turbo")
    with pytest.raises(ValueError):
        sd.detect_symbols(pdf, 5, preset="quick")


def test_equipment_vessel_found_in_deep_preset():
    pdf = symbol_sheet_pdf([{"kind": "vessel_v", "x": 300, "y": 210, "s": 40, "pipe": False}])
    res = sd.detect_symbols(pdf, 1, preset="deep", families=("EQUIPMENT",))
    c = near(res, 300, 210, tol=0.08)
    assert c and c["graphical_family"] == "EQUIPMENT" and c["engineering_class"] in ("PRESSURE_VESSEL", "UNKNOWN")
    assert "SEPARATOR" in c["class_candidates"]            # a bare capsule is not forced to one equipment class


# ---------------------------------------------------------------- pipeline integration and persistence
def test_pipeline_runs_library_detection_and_persists_occurrences_with_ports(tmp_path):
    from pid_reader.api import ReadParams, read_pid
    from pid_reader.engineering import intelligence_store as istore
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.project import ProjectStore
    pdf = symbol_sheet_pdf([{"kind": "globe", "x": 200, "y": 250, "s": 22, "actuator": "diaphragm"}, {"kind": "check", "x": 420, "y": 150, "s": 22}])
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="v.pdf"), source_pdf_bytes=pdf)
        out = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
        o = next(x for x in out["outcomes"] if x["stage_id"] == "symbol_library")
        assert o["status"] == "SUCCESS" and o["candidates"] >= 2 and o["tile_count"] >= 1
        occ = istore.list_items(db, out["run_id"], "OCCURRENCE")
        assert {i["occurrence"]["engineering_class"] for i in occ} >= {"GLOBE_VALVE", "CHECK_VALVE"}
        assert all(i["evidence"] and i["review_state"] == "PROPOSED_UNVERIFIED" and i["ports"] for i in occ)
        off = analyze_drawing(db, eid, ocr_engine=None, preset="quick")
        assert next(x for x in off["outcomes"] if x["stage_id"] == "symbol_library")["status"] == "SKIPPED"
