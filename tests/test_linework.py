"""Vector glyph, line-style and persistence checks; not engineering accuracy validation."""
from __future__ import annotations

from io import BytesIO
import json
import sqlite3
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from pid_reader.api import ReadParams, read_pid, canonical_json, sha256_hex
from pid_reader.engineering.topology import analyze_pdf_topology
from pid_reader.engineering.symbols import build_symbol_proposals
from pid_reader.engineering.linework import build_linework_proposals, validate_linework_proposals
from pid_reader.engineering.project import ProjectStore, DDL
from pid_reader.engineering.migrations import MIGRATION_2, MIGRATION_3


def _draw_bowtie(c, x, y, a, b, orientation="HORIZONTAL"):
    # Two complete side rails prevent accidentally classifying a plain X.
    for dx,dy in ((-a,-b),(-a,b),(a,-b),(a,b)):
        c.line(x,y,x+dx,y+dy)
    if orientation=="HORIZONTAL":
        c.line(x-a,y-b,x-a,y+b)
        c.line(x+a,y-b,x+a,y+b)
        c.line(x-a-70,y,x-a,y)
        c.line(x+a,y,x+a+70,y)
    else:
        c.line(x-a,y-b,x+a,y-b)
        c.line(x-a,y+b,x+a,y+b)
        c.line(x,y-b-40,x,y-b)
        c.line(x,y+b,x,y+b+40)


def sample_pdf():
    stream=BytesIO()
    c=canvas.Canvas(stream,pagesize=(600,650),pageCompression=0)
    c.setFont("Helvetica",10)
    c.drawString(40,610,"SYNTHETIC VALVE AND LINE-STYLE TEST - NOT A PLANT")
    _draw_bowtie(c,235,440,22,14,"HORIZONTAL")
    c.drawString(222,470,"XV-101")
    _draw_bowtie(c,425,355,16,24,"VERTICAL")
    c.drawString(445,365,"XV-102")
    # X crossing without the two rails MUST NOT be classified as a valve.
    c.line(95,520,135,560)
    c.line(95,560,135,520)
    # Solid/dashed cross-style contact is unresolved, not a signal tap.
    c.setDash(4,2)
    c.line(85,170,275,170)
    c.setDash()
    c.line(180,150,180,190)
    c.save()
    return stream.getvalue()


def run_layers():
    pdf=sample_pdf()
    extraction=read_pid(pdf,ReadParams(),filename="linework.pdf")
    geometry=analyze_pdf_topology(pdf)
    symbols=build_symbol_proposals(extraction,geometry)
    result=build_linework_proposals(extraction,geometry,symbols)
    return pdf,extraction,geometry,symbols,result


def test_six_stroke_valves_two_orientations_and_ports():
    _,e,g,s,r=run_layers()
    assert validate_linework_proposals(r,e,g,s)==[]
    assert len(r["valve_candidates"])==2
    assert {v["orientation"] for v in r["valve_candidates"]}=={"HORIZONTAL_AXIS","VERTICAL_AXIS"}
    assert len(r["valve_port_candidates"])==4
    assert {p["side"] for p in r["valve_port_candidates"]}=={"LEFT","RIGHT","TOP","BOTTOM"}
    assert all(v["status"]=="PROPOSED_UNVERIFIED" for v in r["valve_candidates"])
    assert all("not a verified valve" in v["limitations"] for v in r["valve_candidates"])
    assert all(len(v["evidence_segment_ids"])==6 for v in r["valve_candidates"])


def test_dash_is_signal_style_not_confirmed_instrument_connection():
    _,_,g,_,r=run_layers()
    assert any(x["role"]=="SIGNAL_STYLE_CANDIDATE" for x in r["stroke_roles"])
    assert any(x["role"]=="SOLID_UNCLASSIFIED_LINEWORK" for x in r["stroke_roles"])
    assert any(x["role"]=="VALVE_GLYPH_STROKE" for x in r["stroke_roles"])
    assert r["mixed_style_contacts"]
    assert all(c["status"]=="UNRESOLVED" for c in r["mixed_style_contacts"])
    assert all("not proof" in c["limitations"] for c in r["mixed_style_contacts"])
    # Cross-style contacts do not change the frozen R1 connection model.
    assert all(x["type"]=="UNKNOWN" for x in read_pid(sample_pdf(),ReadParams())["connections"])


def test_identical_analyses_deterministic_and_r1_unmodified():
    pdf,e,g,s,r=run_layers()
    assert r==build_linework_proposals(e,g,s)
    assert read_pid(pdf,ReadParams(),filename="linework.pdf")==e or (
        read_pid(pdf,ReadParams(),filename="linework.pdf")["provenance"]["result_sha256"]==e["provenance"]["result_sha256"])
    assert "valve_candidates" not in e
    assert "mixed_style_contacts" not in e


def test_rehashed_forgery_is_rejected():
    _,e,g,s,r=run_layers()
    r["valve_candidates"][0]["orientation"]="VERTICAL_AXIS" if r["valve_candidates"][0]["orientation"]=="HORIZONTAL_AXIS" else "HORIZONTAL_AXIS"
    r["result_sha256"]=sha256_hex(canonical_json({k:v for k,v in r.items() if k!="result_sha256"}).encode())
    assert "Linework proposals differ from source-derived algorithm output" in validate_linework_proposals(r,e,g,s)


def test_wrong_symbol_source_rejected():
    _,e,g,s,_=run_layers()
    s["source_sha256"]="0"*64
    with pytest.raises(Exception): build_linework_proposals(e,g,s)


def test_linework_persistence_and_audited_review(tmp_path):
    pdf,e,g,s,r=run_layers()
    with ProjectStore(tmp_path/"project.sqlite") as store:
        assert store.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=="13"
        eid=store.add_extraction(e,source_pdf_bytes=pdf)
        gid=store.add_geometry_analysis(eid,g)
        sid=store.add_symbol_analysis(eid,gid,s)
        aid=store.add_linework_analysis(eid,gid,sid,r)
        assert store.add_linework_analysis(eid,gid,sid,r)==aid
        assert store.get_linework_analysis(aid)==r
        items=store.list_linework_candidates(aid)
        assert len(items)>=2
        candidate=next(x["candidate_id"] for x in items if x["kind"]=="BOWTIE_VALVE_GEOMETRY_CANDIDATE")
        with pytest.raises(ValueError):
            store.review_linework(candidate,actor="",decision="ACCEPTED_AS_READING",reason="Seen on drawing")
        with pytest.raises(ValueError):
            store.review_linework(candidate,actor="Engineer",decision="ACCEPTED_AS_READING",reason="ok")
        did=store.review_linework(candidate,actor="Engineer",decision="UNRESOLVED",reason="Needs symbol legend")
        assert store.latest_linework_review(candidate)["decision"]=="UNRESOLVED"
        assert store.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with store.db:
                store.db.execute("DELETE FROM linework_decision WHERE decision_id=?",(did,))
        backup=store.backup(tmp_path/"project_copy.sqlite")
    with ProjectStore(backup) as restored:
        assert restored.latest_linework_review(candidate)["actor"]=="Engineer"
        assert restored.verify_audit_chain()
        assert restored.get_linework_analysis(aid)==r


def test_migrate_v3_with_unmodified_original_records(tmp_path):
    pdf,e,g,s,r=run_layers()
    p=tmp_path/"legacy.sqlite"
    with sqlite3.connect(p) as db:
        db.executescript(DDL)
        db.execute("INSERT INTO project_meta VALUES('standalone_schema','1')")
        db.commit()
        db.executescript(MIGRATION_2)
        db.executescript(MIGRATION_3)
        assert db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=="3"
    with ProjectStore(p) as upgraded:
        assert upgraded.migration_backup and upgraded.migration_backup.exists()
        assert upgraded.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=="13"
        assert upgraded.db.execute("SELECT name FROM sqlite_master WHERE name='linework_candidate'").fetchone()
    with sqlite3.connect(next(tmp_path.glob('legacy.sqlite.pre-v12-*.sqlite'))) as old:
        assert old.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=="3"


def test_cli_analyze_and_review_linework(tmp_path,capsys):
    from pid_reader.cli import main
    pdf,e,g,s,r=run_layers()
    file=tmp_path/"drawing.pdf"; file.write_bytes(pdf)
    dest=tmp_path/"project.sqlite"
    resultfile=tmp_path/"linework.json"
    assert main(["import-pdf",str(dest),str(file)])==0
    with ProjectStore(dest) as store:
        eid=store.db.execute("SELECT extraction_id FROM extraction").fetchone()[0]
    assert main(["analyze-topology",str(dest),eid])==0
    with ProjectStore(dest) as store:
        gid=store.db.execute("SELECT analysis_id FROM geometry_analysis").fetchone()[0]
    assert main(["analyze-symbols",str(dest),eid,gid])==0
    with ProjectStore(dest) as store:
        sid=store.db.execute("SELECT analysis_id FROM symbol_analysis").fetchone()[0]
    assert main(["analyze-linework",str(dest),eid,gid,sid,"--output-json",str(resultfile)])==0
    with ProjectStore(dest) as store:
        aid=store.db.execute("SELECT analysis_id FROM linework_analysis").fetchone()[0]
    assert main(["linework-candidates",str(dest),aid])==0
    with ProjectStore(dest) as store:
        cid=store.list_linework_candidates(aid)[0]["candidate_id"]
    assert main(["review-linework",str(dest),cid,"--actor","Engineer","--decision","UNRESOLVED","--reason","Need legend and piping drawing"])==0
    assert json.loads(resultfile.read_text())["schema"]=="pid-reader-standalone-linework-v1"


def test_json_schema_accepts_fixture_result():
    from jsonschema import Draft202012Validator
    schema=json.loads((Path(__file__).resolve().parents[1]/"contracts"/"standalone_linework_v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(run_layers()[4]))==[]


def test_drawing_graph_requires_human_review_and_never_traverses_valve_glyph(tmp_path):
    from pid_reader.engineering.drawing_graph import trace_drawing_segments
    pdf,e,g,s,r=run_layers()
    # Find a non-glyph contact between two strokes and check proposal mode.
    roles={x["segment_id"]:x["role"] for x in r["stroke_roles"]}
    contact=next(c for c in g["contact_candidates"] if
                 all(roles[x]!="VALVE_GLYPH_STROKE" for x in c["segment_ids"]))
    start,target=contact["segment_ids"]
    no_review=trace_drawing_segments(g,r,{},start)
    assert len(no_review["nodes"])==1 and not no_review["edges"]
    proposed=trace_drawing_segments(g,r,{},start,include_unreviewed=True)
    assert target in {x["segment_id"] for x in proposed["nodes"]}
    assert any(x["state"]=="UNREVIEWED_CONTACT_PROPOSAL" for x in proposed["edges"])
    reviewed=trace_drawing_segments(g,r,{contact["id"]:"CONNECTED_AS_DRAWN"},start)
    assert target in {x["segment_id"] for x in reviewed["nodes"]}
    assert any(x["state"]=="REVIEWED_CONNECTED_AS_DRAWN" for x in reviewed["edges"])
    rejected=trace_drawing_segments(g,r,{contact["id"]:"NOT_CONNECTED_AS_DRAWN"},start,include_unreviewed=True)
    assert contact["id"] not in {x["id"] for x in rejected["edges"]}
    assert "not a confirmed physical" in reviewed["limitations"]


def test_database_trace_reflects_latest_append_only_decision(tmp_path):
    pdf,e,g,s,r=run_layers()
    roles={x["segment_id"]:x["role"] for x in r["stroke_roles"]}
    contact=next(c for c in g["contact_candidates"] if all(roles[x]!="VALVE_GLYPH_STROKE" for x in c["segment_ids"]))
    start=contact["segment_ids"][0]
    with ProjectStore(tmp_path/"graph.sqlite") as store:
        eid=store.add_extraction(e,source_pdf_bytes=pdf)
        gid=store.add_geometry_analysis(eid,g)
        sid=store.add_symbol_analysis(eid,gid,s)
        aid=store.add_linework_analysis(eid,gid,sid,r)
        pre=store.trace_drawing(aid,start)
        assert len(pre["nodes"])==1
        candidates=store.list_geometry_candidates(gid)
        candidate_id=next(x["candidate_id"] for x in candidates if x["geometry"]["id"]==contact["id"])
        store.review_geometry(candidate_id,actor="Engineer",decision="CONNECTED_AS_DRAWN",reason="Join shown on PDF")
        post=store.trace_drawing(aid,start)
        assert len(post["nodes"])>=2
        store.review_geometry(candidate_id,actor="Engineer",decision="NOT_CONNECTED_AS_DRAWN",reason="Subsequent closer review")
        withdrawn=store.trace_drawing(aid,start)
        assert contact["id"] not in {x["id"] for x in withdrawn["edges"]}
        assert store.verify_audit_chain()


def test_open_crossing_without_rails_never_becomes_valve():
    out=BytesIO()
    c=canvas.Canvas(out,pagesize=(600,650),pageCompression=0)
    c.line(300,300,325,322)
    c.line(300,322,325,300)
    c.line(300,300,325,300)  # unrelated horizontal line, not both side rails
    c.save()
    pdf=out.getvalue()
    e=read_pid(pdf,ReadParams())
    g=analyze_pdf_topology(pdf)
    s=build_symbol_proposals(e,g)
    r=build_linework_proposals(e,g,s)
    assert not r["valve_candidates"]
    assert not r["valve_port_candidates"]


def test_reviewed_glyph_contacts_do_not_become_pipe_paths():
    from pid_reader.engineering.drawing_graph import trace_drawing_segments
    _,_,g,_,r=run_layers()
    roles={x["segment_id"]:x["role"] for x in r["stroke_roles"]}
    touching=next(x for x in g["contact_candidates"] if
                  any(roles[s]=="VALVE_GLYPH_STROKE" for s in x["segment_ids"]))
    start=touching["segment_ids"][0]
    graph=trace_drawing_segments(g,r,{touching["id"]:"CONNECTED_AS_DRAWN"},start)
    assert touching["id"] not in {e["id"] for e in graph["edges"]}
    assert "not a confirmed physical" in graph["limitations"]
