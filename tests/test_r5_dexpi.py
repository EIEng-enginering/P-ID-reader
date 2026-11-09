"""R5 update, changes 1 and 2: proposed DEXPI mapping, fate accounting, reversible ids, separate checks. Default OFF."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from pid_reader.engineering import dexpi, dexpi_proposed as dp, dexpi_xml, r5_features

SHA_A = "a" * 64
SHA_B = "b" * 64


def ent(eid, kind, cls, tag=None, state="ACCEPTED_AS_READING", ports=(), level="STRUCTURALLY_DERIVED"):
    return {"id": eid, "kind": kind, "tag": tag, "display_name": None, "classification": cls, "semantic_level": level, "review_state": state,
            "source_evidence_ids": ["ev-" + eid], "source_occurrence_ids": [eid], "asset_hypothesis_group_id": None, "attributes": [],
            "ports": [{"id": p, "kind": k, "label": None, "angle_degrees": 0, "source_evidence_ids": ["ev-" + p]} for p, k in ports],
            "score": {"kind": "UNCALIBRATED", "raw_score": 0.9, "calibrated_probability": None, "calibration_id": None}}


def rel(rid, a, b, fp, tp, typ="DRAWN_CONNECTS", state="ACCEPTED_AS_READING"):
    return {"id": rid, "type": typ, "from_entity_id": a, "to_entity_id": b, "from_port_id": fp, "to_port_id": tp, "direction": "UNKNOWN",
            "semantic_level": "STRUCTURALLY_DERIVED", "review_state": state, "source_evidence_ids": ["ev-" + rid], "hypothesis_group_id": None}


def make_snapshot(sha=SHA_A, drawing_no="D-1", revision="A"):
    entities = [
        ent("pump1", "EQUIPMENT", "CENTRIFUGAL_PUMP", "P-101", ports=[("pump1.in", "NOZZLE"), ("pump1.out", "NOZZLE")]),
        ent("hx1", "EQUIPMENT", "PLATE_HEAT_EXCHANGER", "E-201", ports=[("hx1.a", "NOZZLE"), ("hx1.b", "NOZZLE")]),
        ent("hx2", "EQUIPMENT", "TUBULAR_HEAT_EXCHANGER", "E-202", ports=[("hx2.a", "NOZZLE")]),
        ent("vessel1", "EQUIPMENT", "PRESSURE_VESSEL", "V-1", ports=[("vessel1.top", "NOZZLE")]),
        ent("ball1", "VALVE", "BALL_VALVE", "XV-1", ports=[("ball1.a", "PROCESS_UNKNOWN"), ("ball1.b", "PROCESS_UNKNOWN")]),
        ent("globe1", "VALVE", "GLOBE_VALVE", "FV-2", ports=[("globe1.a", "PROCESS_UNKNOWN"), ("globe1.b", "PROCESS_UNKNOWN")]),
        ent("gen1", "VALVE", "VALVE", "HV-3", ports=[("gen1.a", "PROCESS_UNKNOWN"), ("gen1.b", "PROCESS_UNKNOWN")]),
        ent("gate1", "VALVE", "GATE_VALVE", "HV-4", ports=[("gate1.a", "PROCESS_UNKNOWN")]),
        ent("hxgeneric", "EQUIPMENT", "HEAT_EXCHANGER", "E-999", ports=[("hxgeneric.a", "NOZZLE")]),
        ent("unrev", "VALVE", "BALL_VALVE", "XV-9", state="PROPOSED_UNVERIFIED", ports=[("unrev.a", "PROCESS_UNKNOWN")]),
        ent("rej", "VALVE", "BALL_VALVE", "XV-8", state="REJECTED", ports=[("rej.a", "PROCESS_UNKNOWN")]),
        ent("it1", "INSTRUMENT", "INSTRUMENT_FIELD_MOUNTED", "PIT-1", ports=[("it1.p", "OTHER")]),
        ent("it2", "INSTRUMENT", "INSTRUMENT_FIELD_MOUNTED", "PIC-1", ports=[("it2.p", "OTHER")]),
        ent("note1", "ANNOTATION", None, None, state="PROPOSED_UNVERIFIED"),
        ent("unk", "UNCLASSIFIED_SYMBOL", "UNKNOWN", None, state="PROPOSED_UNVERIFIED", level="UNKNOWN"),
    ]
    rels = [rel("r1", "pump1", "ball1", "pump1.out", "ball1.a"), rel("r2", "ball1", "globe1", "ball1.b", "globe1.a"),
            rel("r3", "globe1", "hx1", "globe1.b", "hx1.a"), rel("r4", "pump1", "vessel1", "pump1.in", "vessel1.top"),
            rel("r5", "hx1", "hx2", "hx1.b", "hx2.a", state="PROPOSED_UNVERIFIED"),                     # connection not human reviewed -> sidecar only
            rel("r6", "it1", "it2", "it1.p", "it2.p", typ="SIGNAL_CONNECTS"),
            rel("r7", "pump1", "gate1", "pump1.in", "gate1.a"),                                           # gate valve has no validated mapping
            rel("r8", "pump1", "gen1", "pump1.out", "gen1.a"),
            rel("r9", "gen1", "vessel1", "gen1.b", "vessel1.top"),
            rel("r10", "pump1", "hx1", "WRONGPORT", "hx1.a")]                                             # port not owned by the endpoint entity
    unresolved = [{"id": "unr-r9", "severity": "WARNING", "description": "crossing alternative", "evidence_ids": [], "affected_entity_ids": [], "hypothesis_group_id": None}]
    return {"schema_version": "engineering-intelligence-v1",
            "package": {"run_id": "run-1", "created_utc": "2026-11-09T01:02:03+00:00", "offline": True, "proposal_only": True, "engine_version": "test-1"},
            "drawings": [{"id": "x", "source_name": "Unit 7, A&B.pdf", "sha256": sha, "page_count": 1, "drawing_no": drawing_no, "revision": revision}],
            "evidence": [], "entities": entities, "relationships": rels, "unresolved": unresolved, "quality": {}}


def types(xml):
    objs, issues = dp.audit_read(xml)
    assert issues == []
    return {o["type"] for o in objs}


# ------------------------------------------------------------------ OFF is the unchanged refusal
def test_everything_is_off_by_default(monkeypatch):
    for n in r5_features.FEATURES:
        monkeypatch.delenv("PID_R5_" + n, raising=False)
    assert all(v == "OFF" for v in r5_features.inventory()["features"].values())
    assert set(r5_features.inventory()["disabled_research_only"]) == {"CROWDED_MATCHING", "OPTICAL_STACKED_OCR", "GENERAL_PORT_SIGNAL_RECOGNITION"}


def test_invalid_mode_is_an_error_not_on(monkeypatch):
    monkeypatch.setenv("PID_R5_DEXPI", "yes")
    with pytest.raises(ValueError):
        r5_features.mode("DEXPI")
    with pytest.raises(ValueError):
        r5_features.mode("NOT_A_FEATURE")


def test_off_refuses_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("PID_R5_DEXPI", raising=False)
    with pytest.raises(dexpi.DexpiNotAvailable, match="DEXPI_EXPORT_OFF"):
        dp.export_dexpi_proposed(make_snapshot(), tmp_path)
    with pytest.raises(dexpi.DexpiNotAvailable, match="BLOCKED_OFFICIAL_XSD_NOT_SUPPLIED"):
        dexpi_xml.export_dexpi_xml(make_snapshot(), tmp_path / "x.xml")
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------------------ change 1: five class mappings
def test_five_explicit_classes_map_to_the_dexpi_class_names():
    xml, side = dp.to_dexpi(make_snapshot())
    t = types(xml)
    assert {"Plant/Piping.BallValve", "Plant/Piping.GlobeValve", "Plant/ProcessEquipment.CentrifugalPump",
            "Plant/ProcessEquipment.PlateHeatExchanger", "Plant/ProcessEquipment.TubularHeatExchanger"} <= t
    assert dp.NEW_IN_R5 == ("BALL_VALVE", "GLOBE_VALVE", "CENTRIFUGAL_PUMP", "PLATE_HEAT_EXCHANGER", "TUBULAR_HEAT_EXCHANGER")
    assert side["dexpi_conformant"] is False and side["engineering_validation"] == "NOT_PERFORMED"


def test_generic_valve_keeps_its_unresolved_subtype_note_and_other_classes_stay_in_the_sidecar():
    xml, side = dp.to_dexpi(make_snapshot())
    assert "Plant/Piping.OperatedValve" in types(xml)
    gen_notes = next(o["notes"] for o in side["objects"].values() if o.get("source_id") == "gen1")
    assert "VALVE_SUBTYPE_UNRESOLVED" in gen_notes
    ball_notes = next(o["notes"] for o in side["objects"].values() if o.get("source_id") == "ball1")
    assert "VALVE_SUBTYPE_UNRESOLVED" not in ball_notes
    fates = {(f["kind"], f["id"]): f for f in side["fates"]}
    assert fates[("entity", "gate1")]["fate"] == dp.SIDECAR_ONLY and "NO_VALIDATED_MAPPING_FOR_CLASS:GATE_VALVE" in fates[("entity", "gate1")]["reason"]
    assert fates[("entity", "hxgeneric")]["fate"] == dp.SIDECAR_ONLY and "HEAT_EXCHANGER" in fates[("entity", "hxgeneric")]["reason"]


def test_class_is_exported_only_from_a_human_reviewed_reading_unless_asked():
    _x, side = dp.to_dexpi(make_snapshot())
    f = {(x["kind"], x["id"]): x for x in side["fates"]}
    assert f[("entity", "unrev")]["fate"] == dp.SIDECAR_ONLY and f[("entity", "unrev")]["reason"] == "CLASS_NOT_HUMAN_REVIEWED"
    assert f[("entity", "rej")]["reason"] == "HUMAN_REJECTED" and f[("entity", "rej")]["source_review_state"] == "REJECTED"
    _x2, side2 = dp.to_dexpi(make_snapshot(), include_unreviewed=True)
    f2 = {(x["kind"], x["id"]): x for x in side2["fates"]}
    assert f2[("entity", "rej")]["fate"] == dp.SIDECAR_ONLY                      # a rejected reading is never exported, even when unreviewed ones are
    assert f2[("entity", "unrev")]["fate"] in (dp.SIDECAR_ONLY,)                  # not on any exported connection -> still sidecar, with that reason
    assert f2[("entity", "unrev")]["reason"] == "NOT_ON_ANY_EXPORTED_CONNECTION"
    assert all(o["notes"][0] == "PROPOSED_UNVERIFIED" for o in side2["objects"].values() if "notes" in o)


def test_unclassified_and_unknown_items_are_never_forced_into_a_class():
    xml, side = dp.to_dexpi(make_snapshot())
    f = {(x["kind"], x["id"]): x for x in side["fates"]}
    assert f[("entity", "unk")]["fate"] == dp.SIDECAR_ONLY and f[("entity", "note1")]["fate"] == dp.SIDECAR_ONLY
    assert not any(o["source_id"] in ("unk", "note1") for o in side["objects"].values() if "source_id" in o)


def test_connections_are_grouped_and_unresolved_or_unreviewed_ones_stay_out():
    xml, side = dp.to_dexpi(make_snapshot())
    f = {(x["kind"], x["id"]): x for x in side["fates"]}
    for ok in ("r1", "r2", "r3", "r4", "r6", "r8"):
        assert f[("relationship", ok)]["fate"] == dp.REPRESENTED_UNSUPPORTED, ok
    assert f[("relationship", "r5")]["reason"] == "CONNECTION_NOT_HUMAN_REVIEWED"
    assert f[("relationship", "r7")]["fate"] == dp.SIDECAR_ONLY
    assert f[("relationship", "r9")]["reason"] == "UNRESOLVED_ALTERNATIVE_READING_SEE_REVIEW_LEDGER"      # ambiguous crossing: held for review
    assert f[("relationship", "r10")]["fate"] == dp.REJECTED and f[("relationship", "r10")]["reason"] == "PORT_NOT_OWNED_BY_ENDPOINT_ENTITY"
    # flow is never asserted
    assert all("FLOW_DIRECTION_UNKNOWN_SOURCE_TARGET_ARBITRARY" in o["notes"] for o in side["objects"].values() if o.get("notes") and "Pipe" in o.get("source_id", "") or o.get("source_id") in ("r1", "r2", "r3", "r4", "r8"))


# ------------------------------------------------------------------ change 2: fate accounting
def test_every_source_object_port_and_edge_has_exactly_one_fate():
    snap = make_snapshot()
    _x, side = dp.to_dexpi(snap)
    want = sorted([("entity", e["id"]) for e in snap["entities"]] + [("port", p["id"]) for e in snap["entities"] for p in e["ports"]]
                  + [("relationship", r["id"]) for r in snap["relationships"]])
    assert sorted((f["kind"], f["id"]) for f in side["fates"]) == want
    assert all(f["fate"] in dp.FATES and f["reason"] for f in side["fates"])


def test_source_snapshot_and_review_states_are_retained_losslessly_in_the_sidecar():
    snap = make_snapshot()
    _x, side = dp.to_dexpi(snap)
    assert side["source_snapshot"] == snap and side["source_snapshot"] is not snap
    assert {f["id"]: f["source_review_state"] for f in side["fates"] if f["kind"] == "entity"}["rej"] == "REJECTED"
    assert side["unsupported_information"]["flow_direction"].startswith("never asserted")


def test_fate_accounting_detects_a_missing_or_duplicated_fate():
    snap = make_snapshot()
    _x, side = dp.to_dexpi(snap)
    broken = copy.deepcopy(side)
    broken["fates"].pop()
    with pytest.raises(dp.DexpiExportError, match="FATE_ACCOUNTING_FAILED"):
        dp._assert_fates(snap, broken)
    broken = copy.deepcopy(side)
    broken["fates"].append(copy.deepcopy(broken["fates"][0]))
    with pytest.raises(dp.DexpiExportError, match="FATE_ACCOUNTING_FAILED"):
        dp._assert_fates(snap, broken)


def test_duplicate_source_ids_refuse_the_export_rather_than_merge_observations():
    snap = make_snapshot()
    snap["entities"].append(copy.deepcopy(snap["entities"][0]))
    with pytest.raises(dp.DexpiExportError, match="DUPLICATE_SOURCE_ID"):
        dp.to_dexpi(snap)
    snap = make_snapshot()
    snap["relationships"].append(copy.deepcopy(snap["relationships"][0]))
    with pytest.raises(dp.DexpiExportError, match="DUPLICATE_SOURCE_ID"):
        dp.to_dexpi(snap)
    snap = make_snapshot()
    snap["entities"][1]["ports"][0]["id"] = "pump1.in"
    with pytest.raises(dp.DexpiExportError, match="DUPLICATE_SOURCE_ID"):
        dp.to_dexpi(snap)


# ------------------------------------------------------------------ identifiers
@pytest.mark.parametrize("sid", ["a,b", "a.b", "a_b", "a b", "a_2C_b", "é-ü", "x#node", "1", "D1_x", "a,b,c"])
def test_ids_round_trip_and_are_xml_safe(sid):
    x = dp.encode_id("abc123", sid)
    assert dp.decode_id(x) == ("abc123", sid)
    assert x.replace("_", "").isalnum() and x[0] == "D"


def test_sanitised_look_alikes_cannot_collide():
    ids = ["a,b", "a.b", "a_b", "a b", "a_2C_b", "a-b"]
    enc = {dp.encode_id("n", s) for s in ids}
    assert len(enc) == len(ids)
    with pytest.raises(dp.DexpiExportError):
        dp.encode_id("n", "")


def test_a_comma_in_a_source_id_survives_the_export_unsplit():
    snap = make_snapshot()
    for e in snap["entities"]:                                   # rename one equipment id (and everything that points at it) to contain commas
        pass
    old, new = "pump1", "pump,1.a b"
    s = json.dumps(snap).replace('"pump1"', json.dumps(new)).replace('"pump1.in"', '"pump,1.in"').replace('"pump1.out"', '"pump,1.out"')
    snap = json.loads(s.replace("ev-pump1", "ev-pump,1"))
    xml, side = dp.to_dexpi(snap)
    assert any(f["id"] == new and f["fate"] == dp.REPRESENTED_UNSUPPORTED for f in side["fates"])
    assert dp.readback(xml, side)["status"] == "PASS"
    assert any(m["source_id"] == new for m in side["id_mapping"].values())


def test_same_tag_in_two_documents_does_not_merge_and_namespaces_differ():
    a, b = make_snapshot(SHA_A), make_snapshot(SHA_B)
    xa, sa = dp.to_dexpi(a)
    xb, sb = dp.to_dexpi(b)
    assert sa["namespace"] != sb["namespace"]
    ids_a = {o["id"] for o in dp.audit_read(xa)[0] if o["id"]}
    ids_b = {o["id"] for o in dp.audit_read(xb)[0] if o["id"]}
    assert ids_a and not (ids_a & ids_b)
    c = make_snapshot(SHA_A, revision="B")
    assert dp.to_dexpi(c)[1]["namespace"] != sa["namespace"]               # a new revision is a new namespace


def test_export_is_deterministic():
    x1, s1 = dp.to_dexpi(make_snapshot())
    x2, s2 = dp.to_dexpi(make_snapshot())
    assert x1 == x2 and json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)


# ------------------------------------------------------------------ separate checks
def test_readback_passes_on_a_good_export_and_is_not_a_schema_claim():
    xml, side = dp.to_dexpi(make_snapshot())
    rb = dp.readback(xml, side)
    assert rb["status"] == "PASS", rb
    assert "not an independent importer" in rb["scope"]


def test_readback_detects_duplicate_dangling_missing_and_wrong_class():
    snap = make_snapshot()
    xml, side = dp.to_dexpi(snap)
    victim = next(x for x in side["id_mapping"] if side["id_mapping"][x]["source_id"] == "ball1")
    # dangling reference
    bad = xml.replace('objects="#' + victim, 'objects="#' + victim + '_gone', 1)
    assert "DANGLING_REFERENCE" in dp.readback(bad, side)["problems"]
    # duplicate id
    other = next(x for x in side["id_mapping"] if side["id_mapping"][x]["source_id"] == "globe1")
    assert "DUPLICATE_ID" in dp.readback(xml.replace('id="' + other + '"', 'id="' + victim + '"', 1), side)["problems"]
    # a source object claimed written but removed from the XML
    gone = xml.replace('id="' + victim + '"', 'id="renamed_by_attacker"', 1)
    assert any(p.startswith("WRITTEN_BUT_MISSING_IN_XML") for p in dp.readback(gone, side)["problems"])
    # wrong class
    wrong = xml.replace("Plant/Piping.BallValve", "Plant/Piping.GlobeValve", 1)
    assert any(p.startswith("CLASS_DIFFERS_FROM_SOURCE:ball1") for p in dp.readback(wrong, side)["problems"])
    # tag changed
    assert any(p.startswith("TAG_DIFFERS_FROM_SOURCE") for p in dp.readback(xml.replace("XV-1", "XV-X"), side)["problems"])


def test_reader_refuses_dtd_and_entities():
    evil = '<?xml version="1.0"?><!DOCTYPE m [<!ENTITY x SYSTEM "file:///etc/passwd">]><Model name="m">&x;</Model>'
    objs, issues = dp.audit_read(evil)
    assert issues == ["DTD_ENTITIES_FORBIDDEN"] and objs == []
    assert dp.audit_read("<Model")[1] == ["MALFORMED_XML"]
    assert dp.audit_read(b"<a>" + b"x" * (dp.MAX_XML_BYTES + 1) + b"</a>")[1] == ["INPUT_OVER_LIMIT"]


def test_the_word_accepted_in_source_text_does_not_change_state_or_fail_the_check():
    snap = make_snapshot()
    snap["entities"][0]["tag"] = "ACCEPTED-PUMP-P-101"                   # a legitimate label that contains the word
    snap["entities"][4]["review_state"] = "PROPOSED_UNVERIFIED"        # ... and a reading that is NOT human reviewed
    xml, side = dp.to_dexpi(snap, include_unreviewed=True)
    assert dp.readback(xml, side)["status"] == "PASS"
    f = {x["id"]: x for x in side["fates"] if x["kind"] == "entity"}
    assert f["pump1"]["source_review_state"] == "ACCEPTED_AS_READING" and f["ball1"]["source_review_state"] == "PROPOSED_UNVERIFIED"
    assert all(f["export_state"] == "PROPOSED_UNVERIFIED" for f in side["fates"])        # nothing is promoted, nothing is demoted


def test_xsd_layer_never_passes_without_a_validator_or_the_xsd(tmp_path):
    xml, _ = dp.to_dexpi(make_snapshot())
    assert dp.validate_xsd(xml, None)["status"] == "BLOCKED_XSD_NOT_SUPPLIED"
    fake = tmp_path / "x.xsd"
    fake.write_text("<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'/>", encoding="utf-8")
    assert dp.validate_xsd(xml, fake, expected_sha256="0" * 64)["status"] == "BLOCKED_XSD_HASH_MISMATCH"
    st = dp.validate_xsd(xml, fake)["status"]
    assert st in ("BLOCKED_NO_XML_SCHEMA_VALIDATOR", "VALID", "INVALID")


REGISTRY_DIR = Path(os.environ.get("PID_R5_DEXPI_FILES", r"C:\PIDWork\r5_payload\CHATGPT_WORK_PID_EXTRACTION_RND_RETURN_R5\dexpi"))


@pytest.mark.skipif(not (REGISTRY_DIR / "Plant.xml").is_file(), reason="official DEXPI model files not supplied")
def test_registry_check_passes_the_writer_output_and_catches_unknown_class_and_property():
    reg = dp.load_registry(REGISTRY_DIR / "Core.xml", REGISTRY_DIR / "Plant.xml")
    xml, _ = dp.to_dexpi(make_snapshot(), include_unreviewed=True)
    res = dp.registry_check(xml, reg)
    assert res["status"] == "PASS", res["errors"][:5]
    for cls in ("Plant/Piping.BallValve", "Plant/Piping.GlobeValve", "Plant/ProcessEquipment.CentrifugalPump",
                "Plant/ProcessEquipment.PlateHeatExchanger", "Plant/ProcessEquipment.TubularHeatExchanger"):
        assert cls in reg and not reg[cls]["abstract"]
    bad = xml.replace("Plant/Piping.BallValve", "Plant/Piping.NoSuchValve", 1)
    assert dp.registry_check(bad, reg)["by_code"].get("UNKNOWN_CLASS") == 1
    bad = xml.replace('property="TagName"', 'property="NotAProperty"', 1)
    assert dp.registry_check(bad, reg)["by_code"].get("UNKNOWN_PROPERTY", 0) >= 1


# ------------------------------------------------------------------ orchestration: modes, files, cancel
def test_on_writes_xml_sidecar_and_checks_and_never_overwrites(tmp_path):
    r1 = dp.export_dexpi_proposed(make_snapshot(), tmp_path, mode="on")
    r2 = dp.export_dexpi_proposed(make_snapshot(), tmp_path, mode="on")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["Unit 7, A&B (2).dexpi.checks.json", "Unit 7, A&B (2).dexpi.sidecar.json", "Unit 7, A&B (2).dexpi.xml",
                     "Unit 7, A&B.dexpi.checks.json", "Unit 7, A&B.dexpi.sidecar.json", "Unit 7, A&B.dexpi.xml"]
    assert r1["authoritative_output_changed"] is True and r1["checks"]["readback"] == "PASS" and r1["checks"]["xsd"].startswith("BLOCKED")
    checks = json.loads(Path(r1["checks_file"]).read_text(encoding="utf-8"))
    assert checks["conformance"].startswith("NOT_CLAIMED") and r2["fate_counts"] == r1["fate_counts"]


def test_shadow_writes_only_to_a_separate_folder_and_changes_nothing_authoritative(tmp_path):
    r = dp.export_dexpi_proposed(make_snapshot(), tmp_path, mode="shadow")
    assert [p.name for p in tmp_path.iterdir()] == ["_shadow_dexpi"] and r["authoritative_output_changed"] is False


def test_env_switch_enables_the_legacy_entry_point(tmp_path, monkeypatch):
    monkeypatch.setenv("PID_R5_DEXPI", "on")
    out = dexpi_xml.export_dexpi_xml(make_snapshot(), tmp_path)
    assert out.suffix == ".xml" and out.is_file()


def test_cancel_stops_the_export_and_writes_nothing(tmp_path):
    snap = make_snapshot()
    snap["entities"] += [ent(f"extra{i}", "ANNOTATION", None, None, state="PROPOSED_UNVERIFIED") for i in range(600)]
    with pytest.raises(InterruptedError):
        dp.export_dexpi_proposed(snap, tmp_path, mode="on", cancel=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_missing_folder_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        dp.export_dexpi_proposed(make_snapshot(), tmp_path / "nope", mode="on")
