"""WPU-04: quantities, sizes, classification, tables, notes, revision history."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

pytest.importorskip("pdfplumber")
from pid_reader.engineering import engineering_text as et  # noqa: E402
from pid_reader.engineering import table_parse as tp  # noqa: E402
from pid_reader.engineering.page_regions import profile_pages, segment_regions  # noqa: E402


# ---------------------------------------------------------------- quantities (positive)
@pytest.mark.parametrize("text,value,unit,basis,norm", [
    ("SP=1.74kPa(g)", 1.74, "kPa(g)", "GAUGE", 1.74),
    ("6895 kPa(g)", 6895.0, "kPa(g)", "GAUGE", 6895.0),
    ("210 kPag", 210.0, "kPa(g)", "GAUGE", 210.0),
    ("10 bara", 10.0, "bar(a)", "ABSOLUTE", 1000.0),
    ("100 psig", 100.0, "psi(g)", "GAUGE", 689.4757),
])
def test_pressure_quantities_keep_unit_and_basis(text, value, unit, basis, norm):
    q = et.parse_quantity(text)
    assert q["status"] == "PARSED" and q["value"] == value and q["original_unit"] == unit and q["pressure_basis"] == basis
    assert q["normalized_unit"] == "kPa" and abs(q["normalized_value"] - norm) < 0.01 and q["verbatim"] == text


def test_setpoint_assignment_is_typed_setpoint_not_design():
    q = et.parse_quantity("SP=550kPa(g)")
    assert q["numeric_type"] == "SETPOINT" and q["qualifier"] == "SETPOINT_ASSIGNMENT"


def test_temperature_and_power_normalised_with_original_kept():
    t = et.parse_quantity("60 °F")
    assert t["original_unit"] == "°F" and abs(t["normalized_value"] - 15.5556) < 0.001
    p = et.parse_quantity("36000 BTU/h")
    assert p["original_unit"] == "BTU/h" and abs(p["normalized_value"] - 10550.56) < 0.01


# ---------------------------------------------------------------- quantities (negative / honesty)
def test_pressure_without_basis_is_unknown_never_defaulted():
    q = et.parse_quantity("550 kPa")
    assert q["pressure_basis"] == "UNKNOWN" and q["original_unit"] == "kPa"


def test_states_and_unitless_values_are_not_invented():
    assert et.parse_quantity("TBD")["status"] == "TBD" and et.parse_quantity("TBD")["value"] is None
    assert et.parse_quantity("HOLD")["status"] == "HOLD"
    nu = et.parse_quantity("60")
    assert nu["status"] == "PARSED_NO_UNIT" and nu["original_unit"] is None and nu["normalized_value"] is None


def test_unit_may_come_from_label_and_is_marked_so():
    q = et.parse_quantity("3450", context="OPERATING PRESSURE kPa(g)")
    assert q["qualifier"] == "UNIT_FROM_LABEL" and q["pressure_basis"] == "GAUGE" and q["numeric_type"] == "OPERATING"


def test_dp_is_ambiguous_not_design():
    q = et.parse_quantity("120 kPa", context="DP")
    assert q["numeric_type"] == "UNKNOWN" and "DIFFERENTIAL" in q["alternatives"] and "DESIGN" in q["alternatives"]


def test_garbage_is_unparsed_and_btu_without_rate_not_normalised():
    assert et.parse_quantity("see note 3")["status"] == "UNPARSED"
    b = et.parse_quantity("500 BTU")
    assert b["normalized_value"] is None and b["qualifier"] == "ENERGY_UNIT_NO_RATE"


# ---------------------------------------------------------------- sizes
@pytest.mark.parametrize("text,kind,values", [("NPS 20", "SIZE", [20.0]), ("NPS 1 1/2", "SIZE", [1.5]), ("NPS 30 x NPS 20", "REDUCER", [30.0, 20.0]),
                                              ('20"', "SIZE", [20.0]), ("DN 500", "SIZE", [500.0])])
def test_line_sizes(text, kind, values):
    r = et.parse_line_size(text)
    assert r["kind"] == kind and [s["value"] for s in r["sizes"]] == values


@pytest.mark.parametrize("text", ["PIT-101", "LINE 200-1", "", "NPS", "NPS 30 x"])
def test_non_sizes_are_not_sizes(text):
    assert et.parse_line_size(text)["status"] == "UNPARSED"


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("text,primary", [
    ("NPS 20", "SIZE"), ("LINE 200-2", "LINE_REFERENCE"), ("0209-01-ML-02-001", "DRAWING_REFERENCE"), ("PIT-101", "INSTRUMENT_TAG"),
    ("CLASS 600", "PRESSURE_CLASS"), ('10"-P-1001-A1A', "PIPING_SPEC"), ("HOLD 1", "HOLD"), ("2015-02-11", "DATE"), ("SP=210kPa(g)", "SETPOINT")])
def test_classification_primary(text, primary):
    assert et.classify_text(text)["primary"] == primary


def test_nps_is_never_a_valve_or_instrument_tag_and_line_ref_never_a_drawing_number():
    for t in ("NPS 20", "NPS20", "NPS 30 x NPS 20"):
        assert "INSTRUMENT_TAG" not in [m["kind"] for m in et.classify_text(t)["matches"]]
    assert "DRAWING_REFERENCE" not in [m["kind"] for m in et.classify_text("LINE 200-2")["matches"]]


def test_unknown_is_a_valid_classification():
    c = et.classify_text("random words here")
    assert c["primary"] == "UNKNOWN" and c["matches"] == []


# ---------------------------------------------------------------- tables from a real PDF
def _table_from_pdf(**kw):
    prof = profile_pages(sheet_pdf(table=True, **kw))[0]
    reg = next(r for r in segment_regions(prof) if r["kind"] == "TABLE")
    words = [dict(w, id=f"w{i}") for i, w in enumerate(prof["words"])]
    return tp.parse_table(words, reg["bbox"], prof["rules"], label=reg["label"]), reg


def test_station_data_grid_is_recovered_with_cell_evidence():
    table, reg = _table_from_pdf(title=False)
    assert table["grid_source"] == "RULING_GRID" and table["rows"] >= 3 and table["cols"] >= 3
    texts = {(c["row"], c["col"]): c["text"] for c in table["cells"]}
    assert "PRESSURE" in texts.values() and "6895" in texts.values() and "3450" in texts.values()
    for c in table["cells"]:
        assert c["word_ids"] and 0 <= c["bbox"]["x0"] < c["bbox"]["x1"] <= 1


def test_design_and_operating_values_bind_to_their_own_columns():
    table, _ = _table_from_pdf(title=False)
    values = {(v["field_name"], v["verbatim"]): v for v in tp.bind_values(table)}
    assert values[("PRESSURE", "6895")]["numeric_type"] == "DESIGN" and values[("PRESSURE", "6895")]["column_label"] == "DESIGN"
    assert values[("PRESSURE", "3450")]["numeric_type"] == "OPERATING"
    assert values[("TEMP", "60")]["numeric_type"] == "DESIGN"
    assert not any(v["numeric_type"] == "SETPOINT" for v in values.values())          # no substitution


def test_no_value_crosses_rows():
    table, _ = _table_from_pdf(title=False)
    for v in tp.bind_values(table):
        row_cells = [c["text"] for c in table["cells"] if c["row"] == v["evidence"]["row"]]
        assert v["verbatim"] in row_cells and v["row_label"] in row_cells


def _w(text, x0, y0, x1, y1, i):
    return {"id": i, "text": text, "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}}


def test_row_and_column_naming_different_types_is_conflicting_not_guessed():
    words = [_w("ITEM", .10, .10, .14, .12, "a"), _w("OPERATING", .20, .10, .26, .12, "b"),
             _w("DESIGN", .10, .14, .15, .16, "c"), _w("500", .20, .14, .23, .16, "d"),
             _w("OPERATING", .10, .18, .16, .20, "e"), _w("400", .20, .18, .23, .20, "f")]
    table = tp.parse_table(words, {"x0": .05, "y0": .08, "x1": .30, "y1": .22})
    by = {v["verbatim"]: v for v in tp.bind_values(table)}
    assert by["500"]["status"] == "CONFLICTING" and by["500"]["numeric_type"] == "CONFLICTING"
    assert {a["numeric_type"] for a in by["500"]["alternatives"]} == {"DESIGN", "OPERATING"}
    assert by["400"]["status"] == "BOUND" and by["400"]["numeric_type"] == "OPERATING"


def test_word_straddling_two_rows_is_ambiguous_and_never_bound_confidently():
    words = [_w("ITEM", .10, .10, .14, .12, "a"), _w("VALUE", .20, .10, .25, .12, "b"),
             _w("FIRST", .10, .14, .14, .16, "c"), _w("SECOND", .10, .18, .15, .20, "d"),
             _w("777", .20, .155, .23, .185, "e")]                       # sits between the two data rows
    table = tp.parse_table(words, {"x0": .05, "y0": .08, "x1": .30, "y1": .22})
    v = next(x for x in tp.bind_values(table) if x["verbatim"] == "777")
    assert v["status"] in ("CONFLICTING", "UNBOUND") and v["status"] != "BOUND"
    assert v["alternatives"][0]["reason"] in ("ROW_AMBIGUOUS", "NO_ROW_LABEL") and v["numeric_type"] == "UNKNOWN"


def test_duplicate_values_stay_separate_records():
    words = [_w("ITEM", .10, .10, .14, .12, "a"), _w("VALUE", .20, .10, .25, .12, "b"),
             _w("A", .10, .14, .12, .16, "c"), _w("42", .20, .14, .22, .16, "d"),
             _w("B", .10, .18, .12, .20, "e"), _w("42", .20, .18, .22, .20, "f")]
    recs = tp.bind_values(tp.parse_table(words, {"x0": .05, "y0": .08, "x1": .30, "y1": .22}))
    assert len(recs) == 2 and {r["field_name"] for r in recs} == {"A", "B"}
    assert recs[0]["evidence"]["word_ids"] != recs[1]["evidence"]["word_ids"]


def test_empty_region_gives_empty_table_and_no_values():
    t = tp.parse_table([], {"x0": 0, "y0": 0, "x1": 1, "y1": 1})
    assert t["cells"] == [] and tp.bind_values(t) == []


# ---------------------------------------------------------------- revision table and notes
def test_revision_history_is_parsed_separately_from_title_block():
    prof = profile_pages(sheet_pdf(title=True, revision=True))[0]
    words = [dict(w, id=f"w{i}") for i, w in enumerate(prof["words"])]
    reg = next(r for r in segment_regions(prof) if r["kind"] == "REVISION_TABLE")
    table = tp.parse_table(words, reg["bbox"], prof["rules"])
    rows = tp.parse_revision_table(table)
    assert len(rows) >= 2
    assert rows[0]["fields"]["REV"] == "A" and "ISSUED" in rows[0]["fields"]["DESCRIPTION"] and rows[0]["fields"]["DATE"] == "2014-01-01"
    assert rows[1]["fields"]["REV"] == "B" and rows[1]["evidence"]
    flat = " ".join(" ".join(r["fields"].values()) for r in rows)
    assert "STATUS" not in flat.upper() and "PRELIMINARY" not in flat.upper()          # issue status is not a revision row


def test_notes_and_holds_are_numbered_with_evidence():
    prof = profile_pages(sheet_pdf(title=False, notes=True))[0]
    words = [dict(w, id=f"w{i}") for i, w in enumerate(prof["words"])]
    reg = next(r for r in segment_regions(prof) if r["kind"] == "NOTES")
    notes = tp.parse_notes(words, reg["bbox"])
    kinds = [n["kind"] for n in notes]
    assert kinds.count("NOTE") >= 2 and any("HOLD" in n["text"].upper() for n in notes)
    assert all(n["evidence"] and n["word_ids"] for n in notes)


def test_notes_ignore_plain_body_text():
    words = [_w("RANDOM", .1, .1, .2, .12, "a"), _w("LABEL", .22, .1, .3, .12, "b")]
    assert tp.parse_notes(words, {"x0": 0, "y0": 0, "x1": 1, "y1": 1}) == []


# ---------------------------------------------------------------- integrated into the pipeline and persisted
def test_pipeline_persists_document_text_items_with_evidence(tmp_path):
    from pid_reader.api import ReadParams, read_pid
    from pid_reader.engineering import intelligence_store as istore
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.project import ProjectStore
    pdf = sheet_pdf(title=True, notes=True, table=True, revision=True, body_words=150)
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="s.pdf"), source_pdf_bytes=pdf)
        out = analyze_drawing(db, eid, ocr_engine=None)
        outcome = next(o for o in out["outcomes"] if o["stage_id"] == "doc_text")
        assert outcome["status"] == "SUCCESS" and outcome["diagnostics"]["stats"]["tables"] >= 1
        stored = istore.list_items(db, out["run_id"])
        attrs = [i for i in stored if i["item_kind"] == "ATTRIBUTE"]
        design = [a for a in attrs if a["attribute"].get("verbatim") == "6895"]
        assert design and design[0]["attribute"]["numeric_type"] == "DESIGN" and design[0]["truth_class"] == "STRUCTURALLY_DERIVED"
        assert all(i["evidence"] and i["review_state"] == "PROPOSED_UNVERIFIED" for i in stored)
        assert any(a["attribute"]["field_name"] == "NOTE" and "HOLD" in a["attribute"]["verbatim"].upper() for a in attrs)
        assert any(a["attribute"]["field_name"] == "REVISION_HISTORY_ROW" for a in attrs)
        assert any(a["attribute"]["field_name"] == "TITLE_BLOCK_TEXT" and a["attribute"]["classification"] == "DRAWING_REFERENCE" for a in attrs)
