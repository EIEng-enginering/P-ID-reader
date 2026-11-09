"""Deterministic engineering-geometry tests, NOT physical plant validation."""
from __future__ import annotations
import io
import json
import sqlite3
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from pid_reader.api import ReadParams, read_pid
from pid_reader.engineering.topology import analyze_pdf_topology, verify_topology_result, _segment_contact
from pid_reader.engineering.project import ProjectStore, DDL


def source_pdf():
    output=io.BytesIO()
    c=canvas.Canvas(output,pagesize=(600,650),pageCompression=0)
    # X-shaped crossing in the interior of both strokes.
    c.line(100,550,200,550)
    c.line(150,500,150,600)
    # Endpoint-interior junction (tee).
    c.line(100,450,200,450)
    c.line(150,450,150,415)
    # Both strokes meet at endpoints.
    c.line(100,350,150,350)
    c.line(150,350,200,330)
    # Collinear overlap (not two layers of process pipe).
    c.line(100,250,200,250)
    c.line(150,250,240,250)
    # Dashed signal-style stroke, geometry only.
    c.setDash(4,3);c.line(100,190,250,190);c.setDash()
    c.circle(320,520,15)
    c.drawString(360,520,"PT-101")
    c.save()
    return output.getvalue()


def test_geometry_distinguishes_touch_branch_crossing_and_overlap():
    data=analyze_pdf_topology(source_pdf())
    types={c['kind'] for c in data['contact_candidates']}
    assert 'CROSSING_AMBIGUOUS' in types
    assert 'BRANCH_TEE_AMBIGUOUS' in types
    assert 'ENDPOINT_TOUCH_CANDIDATE' in types
    assert 'COLLINEAR_OVERLAP_AMBIGUOUS' in types
    assert len(data['segments'])>=9
    assert any(s['style']=='DASHED_OR_DOTTED' for s in data['segments'])
    assert any(x['shape']=='CLOSED_NEAR_CIRCULAR_OUTLINE' for x in data['shape_candidates'])
    assert all(x['status']=='UNRESOLVED' for x in data['contact_candidates'])
    assert all('process' in x['limitation'].lower() for x in data['contact_candidates'])
    assert verify_topology_result(data)


def test_analysis_is_deterministic_and_rejects_modification():
    pdf=source_pdf()
    a=analyze_pdf_topology(pdf)
    b=analyze_pdf_topology(pdf)
    assert a==b
    a['contact_candidates'][0]['kind']='FAKE_CONNECTION'
    assert not verify_topology_result(a)


def test_no_diagonal_endpoint_false_positive():
    a={'raw_pts':[(0,0),(10,10)]}
    b={'raw_pts':[(0,10),(10,0)]}
    assert _segment_contact(a,b)[0]=='CROSSING_AMBIGUOUS'
    assert _segment_contact({'raw_pts':[(0,0),(0,10)]},{'raw_pts':[(2,0),(2,10)]}) is None


def test_geometry_persistence_and_immutable_reviews(tmp_path):
    pdf=source_pdf()
    extraction=read_pid(pdf,ReadParams())
    with ProjectStore(tmp_path/'drawing.sqlite') as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        eid=db.add_extraction(extraction,source_pdf_bytes=pdf)
        topology=analyze_pdf_topology(pdf)
        aid=db.add_geometry_analysis(eid,topology)
        assert db.add_geometry_analysis(eid,topology)==aid
        candidates=db.list_geometry_candidates(aid)
        assert len(candidates)==len(topology['contact_candidates'])
        cid=candidates[0]['candidate_id']
        with pytest.raises(ValueError):db.review_geometry(cid,actor='Engineer',decision='CONNECTED_AS_DRAWN',reason='')
        did=db.review_geometry(cid,actor='Engineer',decision='NOT_CONNECTED_AS_DRAWN',reason='Lines cross without a joining dot')
        assert did.startswith('gdec-')
        assert db.latest_geometry_decision(cid)['decision']=='NOT_CONNECTED_AS_DRAWN'
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('DELETE FROM geometry_decision WHERE decision_id=?',(did,))
        backup=db.backup(tmp_path/'backup.sqlite')
        assert backup.exists()
    with ProjectStore(tmp_path/'backup.sqlite') as db2:
        assert db2.verify_audit_chain()
        assert db2.latest_geometry_decision(cid)['actor']=='Engineer'


def test_geometry_source_mismatch(tmp_path):
    pdf=source_pdf()
    data=read_pid(pdf,ReadParams())
    top=analyze_pdf_topology(pdf)
    with ProjectStore(tmp_path/'project.sqlite') as db:
        eid=db.add_extraction(data)
        top['source_sha256']='f'*64
        top['result_sha256']='f'*64
        with pytest.raises(ValueError):db.add_geometry_analysis(eid,top)


def test_upgrade_v1_creates_backup_and_preserves_data(tmp_path):
    p=tmp_path/'legacy.sqlite'
    with sqlite3.connect(p) as db:
        db.executescript(DDL)
        db.execute("INSERT INTO project_meta(key,value) VALUES('standalone_schema','1')")
        db.commit()
    with ProjectStore(p) as project:
        assert project.migration_backup is not None
        assert project.migration_backup.exists()
        assert project.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        assert project.db.execute("SELECT name FROM sqlite_master WHERE name='geometry_candidate'").fetchone()
    with sqlite3.connect(next(tmp_path.glob('legacy.sqlite.pre-v13-*.sqlite'))) as original:
        assert original.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='1'
        assert not original.execute("SELECT name FROM sqlite_master WHERE name='geometry_candidate'").fetchone()


def test_newer_schema_refused(tmp_path):
    p=tmp_path/'future.sqlite'
    with sqlite3.connect(p) as db:
        db.executescript(DDL)
        db.execute("INSERT INTO project_meta(key,value) VALUES('standalone_schema','100')")
        db.commit()
    with pytest.raises(ValueError,match='newer'):
        ProjectStore(p)


def test_standalone_analyzer_not_in_host_schema():
    pdf=source_pdf()
    original=read_pid(pdf,ReadParams())
    top=analyze_pdf_topology(pdf)
    assert 'contact_candidates' not in original
    assert 'connections' in original
    assert 'contact_candidates' in top
    assert 'connections' not in top


def test_geometry_rejects_forged_relationship_even_if_rehashed(tmp_path):
    from pid_reader.api import canonical_json, sha256_hex
    pdf=source_pdf()
    extraction=read_pid(pdf,ReadParams())
    topology=analyze_pdf_topology(pdf)
    # Attacker or faulty adapter recomputes digest after inventing an endpoint.
    topology['contact_candidates'][0]['segment_ids'][0]='stroke-not-present'
    body={k:v for k,v in topology.items() if k!='result_sha256'}
    topology['result_sha256']=sha256_hex(canonical_json(body).encode('utf-8'))
    with ProjectStore(tmp_path/'test.sqlite') as db:
        eid=db.add_extraction(extraction)
        with pytest.raises(ValueError,match='cross-page segments'):
            db.add_geometry_analysis(eid,topology)


def test_cli_analyze_topology_roundtrip(tmp_path):
    from pid_reader.cli import main
    pdf=source_pdf()
    src=tmp_path/'source.pdf';src.write_bytes(pdf)
    proj=tmp_path/'case.sqlite';out=tmp_path/'topology.json'
    assert main(['init-project',str(proj)])==0
    assert main(['import-pdf',str(proj),str(src)])==0
    with ProjectStore(proj) as db:
        eid=db.db.execute('SELECT extraction_id FROM extraction').fetchone()[0]
    assert main(['analyze-topology',str(proj),eid,'--output-json',str(out)])==0
    assert verify_topology_result(json.loads(out.read_text()))


def test_topology_validator_rejects_bad_page_counter_safely():
    from pid_reader.engineering.topology import validate_topology_result
    from pid_reader.api import canonical_json, sha256_hex
    result=analyze_pdf_topology(source_pdf())
    result['page_count']='not-a-number'
    result['result_sha256']=sha256_hex(canonical_json({k:v for k,v in result.items() if k!='result_sha256'}).encode('utf-8'))
    assert 'Invalid document page count' in validate_topology_result(result)


def test_standalone_topology_json_schema():
    from jsonschema import Draft202012Validator
    root=Path(__file__).resolve().parents[1]
    schema=json.loads((root/'contracts/standalone_topology_v1.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    result=analyze_pdf_topology(source_pdf())
    assert list(Draft202012Validator(schema).iter_errors(result))==[]
