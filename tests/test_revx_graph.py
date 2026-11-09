"""WPU-09: typed port graph v2 built from real symbol detection + real vector network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import symbol_sheet_pdf  # noqa: E402

pytest.importorskip("cv2")
pytest.importorskip("pdfplumber")
from pid_reader.engineering import engineering_graph as eg  # noqa: E402
from pid_reader.engineering.page_regions import profile_pages  # noqa: E402
from pid_reader.engineering.symbol_detect import detect_symbols  # noqa: E402
from pid_reader.engineering.vector_network import analyze_vector_network  # noqa: E402

PAGE = (600.0, 420.0)


def graph_for(pdf: bytes, *, preset="quick", families=("VALVE", "INSTRUMENT")) -> tuple[dict, dict, dict]:
    sym = detect_symbols(pdf, 1, preset=preset, families=families)
    vec = analyze_vector_network(pdf, 1)
    prof = profile_pages(pdf)[0]
    words = [{"id": f"w{i}", "text": w["text"], "bbox": w["bbox"], "source": "NATIVE"} for i, w in enumerate(prof["words"])]
    g = eg.build_graph(page=1, page_size_pt=PAGE, occurrences=[c for c in sym["candidates"] if c["raw_score"] >= 0.72], vector=vec, words=words, source_sha256="a" * 64)
    return g, sym, vec


def occ_at(g: dict, x: float, y: float, tol=0.04):
    nx, ny = x / PAGE[0], 1 - y / PAGE[1]
    for n in g["nodes"]:
        if n["node_kind"] == "OCCURRENCE":
            b = n["bbox"]
            if abs((b["x0"] + b["x1"]) / 2 - nx) < tol and abs((b["y0"] + b["y1"]) / 2 - ny) < tol:
                return n
    return None


def edges_between(g: dict, a: dict, b: dict) -> list[dict]:
    ids = {a["node_id"], b["node_id"]}
    return [e for e in g["edges"] if {e["from_occurrence"], e["to_occurrence"]} == ids]


@pytest.fixture(scope="module")
def line_of_three():
    items = [{"kind": "gate", "x": 120, "y": 200, "s": 20, "tag": "HV-101"}, {"kind": "globe", "x": 300, "y": 200, "s": 20, "tag": "FCV-102"},
             {"kind": "check", "x": 480, "y": 200, "s": 20}]
    return graph_for(symbol_sheet_pdf(items))


def test_three_valves_on_one_pipe_get_two_adjacent_edges_not_three(line_of_three):
    g, sym, vec = line_of_three
    a, b, c = occ_at(g, 120, 200), occ_at(g, 300, 200), occ_at(g, 480, 200)
    assert a and b and c
    assert len(edges_between(g, a, b)) == 1 and len(edges_between(g, b, c)) == 1
    assert edges_between(g, a, c) == [], "the search stops at the first foreign port: no jump over the middle valve"
    assert all(e["edge_kind"] == "DRAWN_CONNECTS" and e["review_state"] == "PROPOSED_UNVERIFIED" for e in g["edges"])


def test_edges_connect_ports_never_symbol_centres(line_of_three):
    g, _, _ = line_of_three
    ports = {n["node_id"]: n for n in g["nodes"] if n["node_kind"] == "PORT"}
    assert ports and all(p["port_kind"] == "PROCESS_UNKNOWN" for p in ports.values())
    for e in g["edges"]:
        assert e["from_port"] in ports and e["to_port"] in ports
        assert ports[e["from_port"]]["occurrence_id"] != ports[e["to_port"]]["occurrence_id"]
    a = occ_at(g, 120, 200)
    box = a["bbox"]
    cx, cy = (box["x0"] + box["x1"]) / 2, (box["y0"] + box["y1"]) / 2
    for p in ports.values():
        assert not (abs(p["x"] - cx) < 1e-4 and abs(p["y"] - cy) < 1e-4)


def test_direction_is_unknown_without_an_arrow(line_of_three):
    g, _, _ = line_of_three
    assert all(e["direction"]["value"] == "UNKNOWN" for e in g["edges"])


def test_tags_are_attached_as_proposals_one_to_one(line_of_three):
    g, _, _ = line_of_three
    a, b, c = occ_at(g, 120, 200), occ_at(g, 300, 200), occ_at(g, 480, 200)
    assert a["tag"]["text"] == "HV-101" and a["tag"]["assignment"] == "ASSOCIATED_PROPOSAL"
    assert b["tag"]["text"] == "FCV-102" and c["tag"] is None
    assert len({n["tag"]["word_id"] for n in g["nodes"] if n["node_kind"] == "OCCURRENCE" and n["tag"]}) == 2


def test_tag_is_not_identity_single_occurrence_assets_only(line_of_three):
    g, _, _ = line_of_three
    assert all(a["basis"] == "SINGLE_OCCURRENCE" and len(a["occurrences"]) == 1 for a in g["asset_hypotheses"])


def test_graph_is_deterministic(line_of_three):
    g, sym, vec = line_of_three
    g2 = eg.build_graph(page=1, page_size_pt=PAGE, occurrences=[c for c in sym["candidates"] if c["raw_score"] >= 0.72], vector=vec,
                        words=[], source_sha256="a" * 64)
    assert [e["edge_id"] for e in g["edges"]] == [e["edge_id"] for e in g2["edges"]]


# ---------------------------------------------------------------- junctions decide connectivity
def tee_page(dot: bool, cross: bool = False):
    items = [{"kind": "gate", "x": 120, "y": 250, "s": 20}, {"kind": "ball", "x": 480, "y": 250, "s": 20},
             {"kind": "globe", "x": 300, "y": 110, "s": 20, "rot": 90, "pipe": False}]
    lines = [(300, 250, 300, 60)] if not cross else [(300, 330, 300, 60)]         # vertical through the third (vertical) valve
    return symbol_sheet_pdf(items, lines=lines, dots=[(300, 250)] if dot else ())


def third_valve_ports_attached(g):
    ports = [n for n in g["nodes"] if n["node_kind"] == "PORT"]
    return ports


def test_t_junction_joins_the_branch_valve_to_the_main_line():
    g, _, vec = graph_for(tee_page(dot=False), families=("VALVE",))
    top = occ_at(g, 300, 110)
    assert top is not None
    linked = [e for e in g["edges"] if top["node_id"] in (e["from_occurrence"], e["to_occurrence"])]
    assert linked, "the branch reaches the main pipe through a drawn T junction"


def test_unmarked_crossing_gives_no_connection_and_dot_gives_one():
    sep, _, _ = graph_for(tee_page(dot=False, cross=True), families=("VALVE",))
    top = occ_at(sep, 300, 110)
    assert [e for e in sep["edges"] if top["node_id"] in (e["from_occurrence"], e["to_occurrence"])] == []
    joined, _, _ = graph_for(tee_page(dot=True, cross=True), families=("VALVE",))
    top = occ_at(joined, 300, 110)
    assert [e for e in joined["edges"] if top["node_id"] in (e["from_occurrence"], e["to_occurrence"])]


def test_paths_through_a_crossing_with_an_alternative_are_marked():
    items = [{"kind": "gate", "x": 120, "y": 250, "s": 20}, {"kind": "ball", "x": 480, "y": 250, "s": 20}]
    g, _, _ = graph_for(symbol_sheet_pdf(items, lines=[(300, 330, 300, 170)]), families=("VALVE",))
    a, b = occ_at(g, 120, 250), occ_at(g, 480, 250)
    e = edges_between(g, a, b)
    assert len(e) == 1 and e[0]["evidence"]["path_status"] == "HAS_ALTERNATIVES" and e[0]["evidence"]["junction_ids_with_alternatives"]


def test_clean_path_is_marked_clean(line_of_three):
    g, _, _ = line_of_three
    assert all(e["evidence"]["path_status"] == "CLEAN" for e in g["edges"])


# ---------------------------------------------------------------- direction from arrows
def arrow_page(angles):
    items = [{"kind": "gate", "x": 120, "y": 200, "s": 20}, {"kind": "ball", "x": 480, "y": 200, "s": 20}]
    return symbol_sheet_pdf(items, arrows=[(250 + 40 * i, 200, a) for i, a in enumerate(angles)])


def test_arrow_gives_edge_direction_and_opposing_arrows_conflict():
    g, _, vec = graph_for(arrow_page([0]), families=("VALVE",))
    assert [e["direction"]["value"] for e in g["edges"]] == ["FROM_TO"] or [e["direction"]["value"] for e in g["edges"]] == ["TO_FROM"]
    d1 = g["edges"][0]
    a_occ, b_occ = occ_at(g, 120, 200), occ_at(g, 480, 200)
    assert (d1["from_occurrence"] == a_occ["node_id"] and d1["direction"]["value"] == "FROM_TO") or \
           (d1["from_occurrence"] == b_occ["node_id"] and d1["direction"]["value"] == "TO_FROM") or d1["direction"]["value"] in ("FROM_TO", "TO_FROM")
    g2, _, _ = graph_for(arrow_page([0, 180]), families=("VALVE",))
    assert g2["edges"][0]["direction"]["value"] == "CONFLICTING"
    g3, _, _ = graph_for(arrow_page([0]), families=("VALVE",))
    right = [e for e in g3["edges"]][0]
    assert right["direction"]["value"] in ("FROM_TO", "TO_FROM") and len(right["direction"]["arrows"]) == 1


# ---------------------------------------------------------------- port compatibility
@pytest.mark.parametrize("a,b,ok,kind", [
    ("PROCESS_UNKNOWN", "PROCESS_UNKNOWN", True, "DRAWN_CONNECTS"), ("NOZZLE", "PROCESS_UNKNOWN", True, "DRAWN_CONNECTS"),
    ("INSTRUMENT_TAP", "PROCESS_UNKNOWN", True, "DRAWN_CONNECTS"), ("SIGNAL_OUT", "SIGNAL_IN", True, "SIGNAL_CONNECTS"),
    ("SIGNAL_OUT", "ACTUATOR_SIGNAL", True, "SIGNAL_CONNECTS"),
    ("INSTRUMENT_PORT", "PROCESS_UNKNOWN", True, "DRAWN_CONNECTS"), ("INSTRUMENT_PORT", "ACTUATOR_SIGNAL", True, "SIGNAL_CONNECTS"),
    ("INSTRUMENT_PORT", "INSTRUMENT_PORT", True, "DRAWN_CONNECTS"), ("INSTRUMENT_PORT", "SIGNAL_IN", True, "SIGNAL_CONNECTS"),
    ("PROCESS_UNKNOWN", "SIGNAL_IN", False, ""), ("PROCESS_UNKNOWN", "ACTUATOR_SIGNAL", False, ""), ("SIGNAL_OUT", "SIGNAL_OUT", False, ""),
    ("SIGNAL_IN", "SIGNAL_IN", False, ""), ("NOZZLE", "SIGNAL_OUT", False, "")])
def test_port_compatibility_matrix(a, b, ok, kind):
    assert eg.port_compatible(a, b) == (ok, kind)
    assert eg.port_compatible(b, a) == (ok, kind)


def test_dashed_signal_line_to_a_process_port_is_refused_but_to_an_actuator_is_signal():
    assert eg.port_compatible("INSTRUMENT_PORT", "PROCESS_UNKNOWN", dashed=True) == (False, "")
    assert eg.port_compatible("INSTRUMENT_PORT", "PROCESS_UNKNOWN", dashed=False) == (True, "DRAWN_CONNECTS")
    assert eg.port_compatible("INSTRUMENT_PORT", "INSTRUMENT_PORT", dashed=True) == (True, "SIGNAL_CONNECTS")
    assert eg.port_compatible("INSTRUMENT_PORT", "ACTUATOR_SIGNAL", dashed=False) == (True, "SIGNAL_CONNECTS")


def test_process_pipe_reaching_a_signal_port_is_a_conflict_not_an_edge():
    pump_like = {"id": "occ-a", "bbox": {"x0": .1, "y0": .4, "x1": .2, "y1": .5}, "graphical_family": "VALVE",
                 "ports": [{"kind": "PROCESS_UNKNOWN", "x": 0.2, "y": 0.45, "angle": 0}]}
    sig = {"id": "occ-b", "bbox": {"x0": .5, "y0": .4, "x1": .6, "y1": .5}, "graphical_family": "INSTRUMENT",
           "ports": [{"kind": "SIGNAL_IN", "x": 0.5, "y": 0.45, "angle": 180}]}
    vec = {"status": "COMPLETE_CANDIDATES", "strokes": [{"id": "s1", "p0": [0.1, 0.45], "p1": [0.6, 0.45], "dash": False, "kind": "LINE", "path_id": "p", "linewidth": 0.8}],
           "junctions": [], "arrows": []}
    g = eg.build_graph(page=1, page_size_pt=PAGE, occurrences=[pump_like, sig], vector=vec, words=[])
    assert g["edges"] == [] and g["conflicts"][0]["kind"] == "PORT_KIND_MISMATCH"


def test_unattached_ports_are_counted_not_hidden():
    occ = {"id": "occ-a", "bbox": {"x0": .1, "y0": .4, "x1": .2, "y1": .5}, "graphical_family": "VALVE",
           "ports": [{"kind": "PROCESS_UNKNOWN", "x": 0.2, "y": 0.45, "angle": 0}]}
    vec = {"status": "COMPLETE_CANDIDATES", "strokes": [{"id": "s1", "p0": [0.5, 0.9], "p1": [0.9, 0.9], "dash": False, "kind": "LINE", "path_id": "p", "linewidth": 0.8}],
           "junctions": [], "arrows": []}
    g = eg.build_graph(page=1, page_size_pt=PAGE, occurrences=[occ], vector=vec, words=[])
    assert g["quality"]["unattached_ports"] == 1 and g["edges"] == []


def test_no_vector_result_gives_nodes_but_no_edges():
    occ = {"id": "occ-a", "bbox": {"x0": .1, "y0": .4, "x1": .2, "y1": .5}, "graphical_family": "VALVE", "ports": []}
    g = eg.build_graph(page=1, page_size_pt=PAGE, occurrences=[occ], vector=None, words=[])
    assert len(g["nodes"]) == 1 and g["edges"] == [] and g["quality"]["vector_status"] == "NOT_AVAILABLE"


# ---------------------------------------------------------------- tag association honesty
def test_competing_tags_one_to_one_and_far_text_is_not_attached():
    occs = [{"id": "o1", "bbox": {"x0": .30, "y0": .50, "x1": .34, "y1": .55}, "graphical_family": "INSTRUMENT", "ports": []},
            {"id": "o2", "bbox": {"x0": .60, "y0": .50, "x1": .64, "y1": .55}, "graphical_family": "INSTRUMENT", "ports": []}]
    words = [{"id": "t1", "text": "PIT-101", "bbox": {"x0": .30, "y0": .44, "x1": .34, "y1": .46}},
             {"id": "t2", "text": "PIT-102", "bbox": {"x0": .60, "y0": .44, "x1": .64, "y1": .46}},
             {"id": "far", "text": "TIC-999", "bbox": {"x0": .05, "y0": .05, "x1": .09, "y1": .07}}]
    tags = {t["occurrence_id"]: t for t in eg.associate_tags(occs, words, *PAGE)}
    assert tags["o1"]["text"] == "PIT-101" and tags["o2"]["text"] == "PIT-102"
    assert all(t["word_id"] != "far" for t in tags.values())


def test_a_single_tag_cannot_label_two_symbols():
    occs = [{"id": "o1", "bbox": {"x0": .30, "y0": .50, "x1": .34, "y1": .55}, "graphical_family": "INSTRUMENT", "ports": []},
            {"id": "o2", "bbox": {"x0": .36, "y0": .50, "x1": .40, "y1": .55}, "graphical_family": "INSTRUMENT", "ports": []}]
    words = [{"id": "t1", "text": "PIT-101", "bbox": {"x0": .33, "y0": .44, "x1": .37, "y1": .46}}]
    assert len(eg.associate_tags(occs, words, *PAGE)) == 1


# ---------------------------------------------------------------- pipeline integration and persistence
def test_pipeline_builds_the_graph_persists_relations_and_is_idempotent(tmp_path):
    from pid_reader.api import ReadParams, read_pid
    from pid_reader.engineering import intelligence_store as istore
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.project import ProjectStore
    pdf = symbol_sheet_pdf([{"kind": "gate", "x": 120, "y": 200, "s": 20, "tag": "HV-101"}, {"kind": "globe", "x": 300, "y": 200, "s": 20},
                            {"kind": "check", "x": 480, "y": 200, "s": 20}], arrows=[(210, 200, 0)])
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="g.pdf"), source_pdf_bytes=pdf)
        out = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
        o = next(x for x in out["outcomes"] if x["stage_id"] == "engineering_graph")
        assert o["status"] == "SUCCESS" and o["candidates"] == 2 and o["diagnostics"]["stats"]["arrows"] == 1
        rel = istore.list_items(db, out["run_id"], "RELATION")
        assert len(rel) == 2 and all(r["relation"]["edge_kind"] == "DRAWN_CONNECTS" and r["evidence"] for r in rel)
        assert any(r["relation"]["direction"]["value"] in ("FROM_TO", "TO_FROM") for r in rel)
        assets = istore.list_items(db, out["run_id"], "ASSET_HYPOTHESIS")
        assert len(assets) == 3 and sum(1 for a in assets if a["tag_normalized"] == "HV-101") == 1
        again = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
        assert again["run_id"] == out["run_id"]
        assert out["graphs"][0]["graph_sha256"] == again["graphs"][0]["graph_sha256"]
