"""WPU-10: loops from tags + drawn signal links; no logic, no SIL/IPL credit."""
from __future__ import annotations

import pytest

from pid_reader.engineering import control_loops as cl


def occ(nid, kind, tag, page=1, actuation=None, x=0.1):
    return {"node_id": nid, "node_kind": "OCCURRENCE", "entity_kind": kind, "page": page, "bbox": {"x0": x, "y0": .4, "x1": x + .03, "y1": .45},
            "engineering_class": "UNKNOWN", "actuation": actuation, "tag": {"text": tag, "word_id": "w-" + nid} if tag else None}


def port(pid, oid, kind="INSTRUMENT_PORT"):
    return {"node_id": pid, "node_kind": "PORT", "occurrence_id": oid, "port_kind": kind, "page": 1, "x": .1, "y": .4}


def edge(eid, fp, tp, fo, to, kind="SIGNAL_CONNECTS", page=1):
    return {"edge_id": eid, "edge_kind": kind, "from_port": fp, "to_port": tp, "from_occurrence": fo, "to_occurrence": to, "page": page}


def graph(nodes, edges, page=1):
    return {"page": page, "nodes": nodes, "edges": edges}


def control_loop_graph(link_controller=True):
    nodes = [occ("pit", "INSTRUMENT", "PIT-102", x=.1), occ("pic", "INSTRUMENT", "PIC-102", x=.3), occ("pcv", "VALVE", "PCV-102", x=.5, actuation={"actuation": "PNEUMATIC_DIAPHRAGM"}),
             port("p1", "pit"), port("p2", "pic"), port("p3", "pic"), port("p4", "pcv", "ACTUATOR_SIGNAL")]
    edges = [edge("e1", "p1", "p2", "pit", "pic")]
    if link_controller:
        edges.append(edge("e2", "p3", "p4", "pic", "pcv"))
    return graph(nodes, edges)


# ---------------------------------------------------------------- tag parsing
@pytest.mark.parametrize("tag,var,funcs,num", [("PIC-102", "PRESSURE", "IC", "102"), ("PCV-102", "PRESSURE", "CV", "102"), ("TT-205A", "TEMPERATURE", "T", "205"),
                                               ("FIT 310", "FLOW", "IT", "310"), ("PSHH-201", "PRESSURE", "SHH", "201")])
def test_isa_tags_parse(tag, var, funcs, num):
    p = cl.parse_instrument_tag(tag)
    assert p["status"] == "PARSED" and p["measured_variable"] == var and p["function_letters"] == funcs and p["loop_number"] == num


@pytest.mark.parametrize("tag", ["NPS 20", "LINE 200-1", "123", "P", "hello world"])
def test_non_tags_stay_unparsed(tag):
    assert cl.parse_instrument_tag(tag)["status"] == "UNPARSED"


def test_roles_come_from_function_letters_only():
    assert "CONTROLLER" in cl.parse_instrument_tag("PIC-101")["roles"] and "TRANSMITTER" in cl.parse_instrument_tag("PIT-101")["roles"]
    assert "ALARM_OR_TRIP_SWITCH_CANDIDATE" in cl.parse_instrument_tag("PSHH-201")["roles"]
    assert cl.parse_instrument_tag("PI-101")["roles"] == ["INDICATOR"]
    assert cl.parse_instrument_tag("PCV-102")["roles"] == ["FINAL_ELEMENT_VALVE"]       # the C of a control valve is not a controller


# ---------------------------------------------------------------- loops: linked by drawn signal
def test_linked_loop_has_three_members_and_control_relations():
    r = cl.build_loops([control_loop_graph()])
    loop = next(x for x in r["loops"] if x["loop_number"] == "102")
    assert loop["status"] == "LINKED_BY_DRAWN_SIGNAL" and {m["tag"] for m in loop["members"]} == {"PIT-102", "PIC-102", "PCV-102"}
    assert loop["has_controller"] and loop["has_final_element"] and loop["logic"] == "NOT_SHOWN_ON_DRAWING" and loop["safety_credit"] == "NOT_ASSESSED"
    kinds = {x["relation"] for x in r["relations"]}
    assert {"MEASURED_VALUE_TO_CONTROLLER", "CONTROLS", "ACTUATES"} <= kinds
    ctl = next(x for x in r["relations"] if x["relation"] == "CONTROLS")
    assert ctl["from_occurrence"] == "pic" and ctl["to_occurrence"] == "pcv" and ctl["evidence"]


def test_position_feedback_from_zt_to_valve_actuator():
    nodes = [occ("zt", "INSTRUMENT", "ZT-102"), occ("v", "VALVE", "PCV-102", x=.4), port("a", "zt"), port("b", "v", "ACTUATOR_SIGNAL")]
    r = cl.build_loops([graph(nodes, [edge("e", "a", "b", "zt", "v")])])
    assert any(x["relation"] == "POSITION_FEEDBACK" and x["from_occurrence"] == "zt" for x in r["relations"])


def test_instrument_connected_to_process_item_is_measures_proposal():
    nodes = [occ("pit", "INSTRUMENT", "PIT-101"), occ("ves", "EQUIPMENT", "V-101", x=.5), port("a", "pit"), port("b", "ves", "NOZZLE")]
    r = cl.build_loops([graph(nodes, [edge("e", "a", "b", "pit", "ves", kind="DRAWN_CONNECTS")])])
    m = next(x for x in r["relations"] if x["relation"] == "MEASURES")
    assert m["measured_variable"] == "PRESSURE" and m["to_occurrence"] == "ves" and "not a verified tapping point" in m["note"]


def test_protective_devices_are_mentions_with_no_credit():
    nodes = [occ("a", "INSTRUMENT", "PSHH-201"), occ("b", "VALVE", "PSV-101", x=.3)]
    r = cl.build_loops([graph(nodes, [])])
    tags = {p["tag"]: p for p in r["protective_device_mentions"]}
    assert set(tags) == {"PSHH-201", "PSV-101"}
    assert all(p["safety_credit"] == "NOT_ASSESSED" and "not shown" in p["statement"] for p in tags.values())


def test_control_system_and_interlock_wording_are_text_mentions_only():
    words = {1: [{"id": "w1", "text": "PLC", "bbox": {"x0": .1, "y0": .1, "x1": .15, "y1": .12}},
                 {"id": "w2", "text": "SCADA", "bbox": {"x0": .2, "y0": .1, "x1": .25, "y1": .12}},
                 {"id": "w3", "text": "INTERLOCK", "bbox": {"x0": .3, "y0": .1, "x1": .4, "y1": .12}},
                 {"id": "w4", "text": "SIL", "bbox": {"x0": .5, "y0": .1, "x1": .55, "y1": .12}},
                 {"id": "w5", "text": "PUMP", "bbox": {"x0": .6, "y0": .1, "x1": .65, "y1": .12}}]}
    r = cl.build_loops([graph([], [])], words)
    assert {m["text"] for m in r["text_mentions"]} == {"PLC", "SCADA", "INTERLOCK", "SIL"}
    assert all(m["safety_credit"] == "NOT_ASSESSED" and m["logic"] == "NOT_SHOWN_ON_DRAWING" for m in r["text_mentions"])
    assert not any("sil" in k.lower() or "ipl" in k.lower() for m in r["text_mentions"] for k in m)


# ---------------------------------------------------------------- negatives: nothing is invented
def test_disconnected_controller_is_not_a_confirmed_loop_and_controls_nothing():
    r = cl.build_loops([control_loop_graph(link_controller=False)])
    statuses = {(x["status"], tuple(sorted(m["tag"] for m in x["members"]))) for x in r["loops"] if x["loop_number"] == "102"}
    assert ("LINKED_BY_DRAWN_SIGNAL", ("PIC-102", "PIT-102")) in statuses
    only = next(x for x in r["loops"] if x["status"] == "LOOP_NUMBER_ONLY")
    assert [m["tag"] for m in only["members"]] == ["PCV-102"] or "PCV-102" in [m["tag"] for m in only["members"]]
    assert not any(x["relation"] in ("CONTROLS", "ACTUATES") for x in r["relations"])
    linked = next(x for x in r["loops"] if x["status"] == "LINKED_BY_DRAWN_SIGNAL")
    assert linked["has_controller"] and not linked["has_final_element"] and "no final element" in linked["note"]


def test_same_loop_number_without_any_signal_edge_is_number_only():
    nodes = [occ("a", "INSTRUMENT", "PIT-102"), occ("b", "INSTRUMENT", "PIC-102", x=.3)]
    r = cl.build_loops([graph(nodes, [])])
    assert [x["status"] for x in r["loops"]] == ["LOOP_NUMBER_ONLY"] and r["relations"] == []
    assert "no drawn signal path" in r["loops"][0]["note"]


def test_same_number_on_different_pages_is_not_merged_without_a_link():
    g1 = graph([occ("a", "INSTRUMENT", "PIT-102", page=1)], [], page=1)
    g2 = graph([occ("b", "INSTRUMENT", "PIC-102", page=2)], [], page=2)
    r = cl.build_loops([g1, g2])
    assert all(x["status"] == "LOOP_NUMBER_ONLY" for x in r["loops"])


def test_different_loop_numbers_are_never_one_loop():
    nodes = [occ("a", "INSTRUMENT", "PIC-102"), occ("b", "VALVE", "FCV-110", x=.4), port("p", "a"), port("q", "b", "ACTUATOR_SIGNAL")]
    r = cl.build_loops([graph(nodes, [edge("e", "p", "q", "a", "b")])])
    assert not any({"PIC-102", "FCV-110"} <= {m["tag"] for m in x["members"]} for x in r["loops"])


def test_signal_between_two_indicators_does_not_create_control():
    nodes = [occ("a", "INSTRUMENT", "PI-102"), occ("b", "INSTRUMENT", "PI-103", x=.3), port("p", "a"), port("q", "b")]
    r = cl.build_loops([graph(nodes, [edge("e", "p", "q", "a", "b")])])
    assert not any(x["relation"] in ("CONTROLS", "ACTUATES") for x in r["relations"])


def test_process_edge_between_non_instruments_makes_no_measures():
    nodes = [occ("a", "VALVE", "HV-101"), occ("b", "EQUIPMENT", "V-101", x=.4), port("p", "a", "PROCESS_UNKNOWN"), port("q", "b", "NOZZLE")]
    r = cl.build_loops([graph(nodes, [edge("e", "p", "q", "a", "b", kind="DRAWN_CONNECTS")])])
    assert r["relations"] == []


def test_untagged_or_unparseable_occurrences_form_no_loops():
    nodes = [occ("a", "INSTRUMENT", None), occ("b", "INSTRUMENT", "NPS 20", x=.3)]
    assert cl.build_loops([graph(nodes, [])])["loops"] == []


# ---------------------------------------------------------------- safety guard
def test_guard_rejects_sil_ipl_and_credit_fields():
    for bad in ({"sil_rating": 2}, {"x": [{"IPL_credit": True}]}, {"nested": {"safeguard_credit": "yes"}}, {"pfd": 0.01}):
        with pytest.raises(ValueError):
            cl.assert_no_safety_claims(bad)
    cl.assert_no_safety_claims({"safety_credit": "NOT_ASSESSED"})


def test_every_emitted_record_says_credit_not_assessed():
    r = cl.build_loops([control_loop_graph()], {1: [{"id": "w", "text": "SIS", "bbox": {"x0": .1, "y0": .1, "x1": .2, "y1": .2}}]})
    for group in ("loops", "relations", "protective_device_mentions", "text_mentions"):
        assert all(x["safety_credit"] == "NOT_ASSESSED" for x in r[group])
    assert all(x["review_state"] == "PROPOSED_UNVERIFIED" for x in r["loops"] + r["relations"])


def test_loops_are_deterministic():
    assert cl.build_loops([control_loop_graph()]) == cl.build_loops([control_loop_graph()])
