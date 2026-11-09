"""WPU-15: DEXPI stays honestly disabled; the mapping report lists every kind with a status; DXF source mode is separate and tested."""
from __future__ import annotations

from io import StringIO

import pytest

from pid_reader.engineering import dexpi, dexpi_xml

ALLOWED = {"PARTIAL", "NOT_AVAILABLE", "UNMAPPED"}


def snap(kinds=("VALVE", "EQUIPMENT", "UNCLASSIFIED_SYMBOL", "TABLE_CELL"), rels=("DRAWN_CONNECTS", "SIGNAL_CONNECTS", "PROPOSED_SAME_AS")):
    return {"entities": [{"id": f"e{i}", "kind": k} for i, k in enumerate(kinds)], "relationships": [{"id": f"r{i}", "type": t} for i, t in enumerate(rels)]}


def test_export_refuses_and_writes_no_file(tmp_path):
    out = tmp_path / "x.xml"
    with pytest.raises(dexpi.DexpiNotAvailable, match="BLOCKED_OFFICIAL_XSD_NOT_SUPPLIED"):
        dexpi_xml.export_dexpi_xml(snap(), out)
    assert not out.exists() and list(tmp_path.iterdir()) == []


def test_supplying_a_file_called_xsd_does_not_unlock_export(tmp_path):
    xsd = tmp_path / "dexpi.xsd"
    xsd.write_text("<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'/>", encoding="utf-8")
    st = dexpi_xml.status(xsd)
    assert st["status"] in (dexpi_xml.STATUS_BLOCKED_VALIDATOR, dexpi_xml.STATUS_DISABLED) and st["dexpi_conformant"] is False
    with pytest.raises(dexpi.DexpiNotAvailable):
        dexpi_xml.export_dexpi_xml(snap(), tmp_path / "o.xml", xsd_path=xsd)
    assert not (tmp_path / "o.xml").exists()


def test_status_names_the_specific_blocker_for_a_missing_file(tmp_path):
    st = dexpi_xml.status(tmp_path / "nope.xsd")
    assert st["status"] == dexpi_xml.STATUS_BLOCKED_XSD and "never downloaded" in st["reason"]


def test_the_older_adapter_still_refuses():
    assert dexpi.STATUS == "NOT_IMPLEMENTED"
    with pytest.raises(dexpi.DexpiNotAvailable):
        dexpi.export_dexpi(object(), "x.xml")


def test_report_covers_every_kind_with_a_status_and_never_claims_conformance():
    r = dexpi_xml.mapping_report(snap())
    assert r["dexpi_conformant"] is False and r["xsd_validation"] == "NOT_RUN" and r["export_status"] == dexpi_xml.STATUS_DISABLED
    assert {row["kind"] for row in r["entities"]} == {"VALVE", "EQUIPMENT", "UNCLASSIFIED_SYMBOL", "TABLE_CELL"}
    assert all(row["status"] in ALLOWED and row["target_class_verified"] is False for row in r["entities"] + r["relationships"])
    assert {row["type"] for row in r["relationships"]} == {"DRAWN_CONNECTS", "SIGNAL_CONNECTS", "PROPOSED_SAME_AS"}


def test_unclassified_symbols_and_tables_are_never_forced_into_a_class():
    rows = {row["kind"]: row for row in dexpi_xml.mapping_report(snap())["entities"]}
    assert rows["UNCLASSIFIED_SYMBOL"]["status"] == "UNMAPPED" and "never forced" in rows["UNCLASSIFIED_SYMBOL"]["gap"]
    assert rows["TABLE_CELL"]["status"] == "UNMAPPED"


def test_identity_proposals_are_not_interchange_content():
    rows = {row["type"]: row for row in dexpi_xml.mapping_report(snap())["relationships"]}
    assert rows["PROPOSED_SAME_AS"]["status"] == "UNMAPPED"


def test_unknown_kinds_are_reported_unmapped_not_dropped():
    r = dexpi_xml.mapping_report(snap(kinds=("SOMETHING_NEW",), rels=("WEIRD",)))
    assert r["entities"][0]["status"] == "UNMAPPED" and r["relationships"][0]["status"] == "UNMAPPED"


def test_report_states_the_preserved_unknown_policy_and_prerequisites():
    r = dexpi_xml.mapping_report(snap())
    assert "side manifest" in r["preserved_unknown_policy"] and "lossless" in r["preserved_unknown_policy"]
    assert any("XSD" in p for p in r["prerequisites"]) and any("round trip" in p for p in r["prerequisites"])
    assert "UNVERIFIED_AGAINST_SPEC" in r["note"]


def test_every_snapshot_entity_kind_the_exporter_can_emit_has_a_mapping_decision():
    from pid_reader.engineering import intelligence as intel
    emitted = {"VALVE", "VALVE_ACTUATOR", "INSTRUMENT", "EQUIPMENT", "UNCLASSIFIED_SYMBOL", "TABLE", "TABLE_CELL", "ANNOTATION", "INSTRUMENT_LOOP", "SAFETY_DEVICE", "CONTROL_SYSTEM"}
    assert emitted <= set(dexpi_xml.ENTITY_MAPPING) and set(intel._ENTITY_BY_FAMILY.values()) <= set(dexpi_xml.ENTITY_MAPPING)


def test_dxf_source_mode_is_separate_unreviewed_and_makes_no_connectivity_claim():
    ezdxf = pytest.importorskip("ezdxf")
    from pid_reader.formats.dxf_source import read_dxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))
    msp.add_line((100, 0), (100, 50))
    msp.add_text("PIT-101", dxfattribs={"insert": (10, 10), "height": 3})
    buf = StringIO()
    doc.write(buf)
    out = read_dxf(buf.getvalue().encode("utf-8"))
    text = str(out).lower()
    assert "dexpi" not in text and "connected" not in text.replace("not connected", "")
    objs = out.get("observations") or out.get("entities") or out.get("objects") or []
    assert objs and all(o.get("review_state", "PROPOSED") in ("PROPOSED", "UNREVIEWED", "PROPOSED_UNVERIFIED") for o in objs)
