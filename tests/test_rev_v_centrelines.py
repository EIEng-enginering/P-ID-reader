"""Rev V: raster-centreline data integrity, geometry negatives, and reviewed-only trace."""
from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from pid_reader.api import ReadParams, read_pid, canonical_json, sha256_hex
from pid_reader.engineering.raster_geometry import analyze_raster_geometry
from pid_reader.engineering.raster_network import build_raster_network
from pid_reader.engineering.raster_centrelines import (
    build_raster_centrelines, validate_raster_centrelines, trace_reviewed_centrelines,
    _gap_candidate,
)
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.findings import list_findings, review_finding
from pid_reader.cli import main
from test_rev_u_raster_network import _input, _ocr, DRAWING


@pytest.fixture(scope='module')
def source():return DRAWING.read_bytes()


@pytest.fixture(scope='module')
def raw(source):return analyze_raster_geometry(source)


def _drawn(raw):
    lines=[((100,100),(150,100)),((160,100),(220,100)),
           ((100,210),(200,210)),((100,217),(200,217)),
           ((125,290),(200,290)),((162,250),(162,330)),
           ((100,450),(200,450)),((101,450),(199,450))]
    return _input(raw,lines)


def test_hypotheses_and_gap_negatives(raw):
    r=_drawn(raw);n=build_raster_network(r);out=build_raster_centrelines(r,n)
    assert out['statistics']['source_strokes']==8
    assert out['statistics']['duplicate_strokes']==1
    assert len(out['centrelines'])==7
    assert len(out['gap_candidates'])==1
    assert out['gap_candidates'][0]['gap_px']==10
    assert out['gap_candidates'][0]['status']=='UNRESOLVED'
    assert all(not c.get('is_pipe') for c in out['centrelines'])
    assert validate_raster_centrelines(out,r,n)==[]
    assert build_raster_centrelines(r,n)==out
    assert _gap_candidate((0,0),(100,0),(95,0),(180,0)) is None  # overlap
    assert _gap_candidate((0,0),(100,0),(110,7),(200,7)) is None  # parallel line
    assert _gap_candidate((0,0),(100,0),(110,0),(110,100)) is None  # elbow not collinear
    assert _gap_candidate((0,0),(100,0),(122,0),(200,0)) is None  # too wide


def test_tamper_and_mismatched_source_refused(raw):
    r=_drawn(raw);n=build_raster_network(r);out=build_raster_centrelines(r,n)
    f=copy.deepcopy(out);f['gap_candidates'][0]['status']='VERIFIED_PIPE'
    f['result_sha256']=sha256_hex(canonical_json({k:v for k,v in f.items() if k!='result_sha256'}).encode())
    assert validate_raster_centrelines(f,r,n)
    n2=copy.deepcopy(n);n2['source_sha256']='a'*64
    n2['result_sha256']=sha256_hex(canonical_json({k:v for k,v in n2.items() if k!='result_sha256'}).encode())
    with pytest.raises(ValueError,match='hash mismatch'):build_raster_centrelines(r,n2)


def test_source_role_context_is_not_silently_discarded(raw):
    r=_drawn(raw)
    o=_ocr(r['source_sha256'],r['page_frames'][0],(98,98,222,103))
    n=build_raster_network(r,o)
    out=build_raster_centrelines(r,n)
    assert len(out['centrelines'])==7
    assert out['gap_candidates']
    assert any(x['context_warning']=='TEXT_OR_SYMBOL_CONTEXT_REVIEW' for x in out['gap_candidates'])
    assert validate_raster_centrelines(out,r,n)==[]


def test_small_changes_to_stroke_coordinates_change_evidence(raw):
    r=_drawn(raw);n=build_raster_network(r);out=build_raster_centrelines(r,n)
    r2=copy.deepcopy(r)
    r2['stroke_candidates'][0]['endpoints'][0][0]+=.02
    r2['result_sha256']=sha256_hex(canonical_json({k:v for k,v in r2.items() if k!='result_sha256'}).encode())
    assert validate_raster_centrelines(out,r2,n)


def _store(tmp_path,source,raw):
    r=_drawn(raw)
    x=read_pid(source,ReadParams(),filename='raster.pdf')
    db=ProjectStore(tmp_path/'raster.sqlite')
    eid=db.add_extraction(x,source_pdf_bytes=source)
    rid=db.add_raster_analysis(eid,r)
    net=build_raster_network(r)
    nid=db.add_raster_network_analysis(eid,rid,net)
    lines=build_raster_centrelines(r,net)
    aid=db.add_raster_centreline_analysis(eid,rid,nid,lines)
    return db,eid,rid,nid,aid,lines


def test_database_review_idempotence_and_audit(tmp_path,source,raw):
    db,eid,rid,nid,aid,lines=_store(tmp_path,source,raw)
    with db:
        assert aid==db.add_raster_centreline_analysis(eid,rid,nid,lines)
        assert db.get_raster_centreline_analysis(aid)==lines
        gaps=db.list_raster_centreline_gaps(aid)
        assert len(gaps)==1
        gid=gaps[0]['candidate_id']
        assert len(list_findings(db,eid,'raster_centrelines'))==1
        with pytest.raises(ValueError):db.review_raster_centreline_gap(gid,actor='',decision='UNRESOLVED',reason='Too uncertain')
        decision=review_finding(db,'raster_centrelines',gid,actor='Engineer',decision='SEPARATE_AS_DRAWN',reason='Ink has a real gap')
        assert db.latest_raster_centreline_review(gid)['decision']=='SEPARATE_AS_DRAWN'
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('DELETE FROM raster_centreline_decision WHERE decision_id=?',(decision,))
        assert db.verify_audit_chain()
        assert db.export_extraction(eid)['document']['sha256']==read_pid(source,ReadParams(),filename='raster.pdf')['document']['sha256']


def test_reviewed_only_graph_and_optional_exploration(tmp_path,source,raw):
    db,eid,rid,nid,aid,lines=_store(tmp_path,source,raw)
    with db:
        gap=db.list_raster_centreline_gaps(aid)[0]
        a,b=gap['candidate']['centreline_ids']
        assert trace_reviewed_centrelines(db,aid,a)['centreline_ids']==[a]
        exploratory=trace_reviewed_centrelines(db,aid,a,include_unreviewed=True)
        assert set(exploratory['centreline_ids'])=={a,b}
        assert exploratory['traversed_edges'][0]['provisional']
        db.review_raster_centreline_gap(gap['candidate_id'],actor='Engineer',
                  decision='CONTINUOUS_AS_DRAWN',reason='One continuous drawn pipe segment')
        accepted=trace_reviewed_centrelines(db,aid,a)
        assert set(accepted['centreline_ids'])=={a,b}
        assert accepted['traversed_edges'][0]['review_state']=='CONTINUOUS_AS_DRAWN'
        db.review_raster_centreline_gap(gap['candidate_id'],actor='Engineer',
                  decision='REJECTED',reason='Corrected interpretation after inspection')
        assert trace_reviewed_centrelines(db,aid,a)['centreline_ids']==[a]
        assert trace_reviewed_centrelines(db,aid,a,include_unreviewed=True)['centreline_ids']==[a]
        with pytest.raises(KeyError):trace_reviewed_centrelines(db,aid,'not-a-real-centreline')
        with pytest.raises(ValueError):trace_reviewed_centrelines(db,aid,a,max_hops=0)


def test_reviewed_raster_contact_can_extend_traced_paths(tmp_path,source,raw):
    db,eid,rid,nid,aid,lines=_store(tmp_path,source,raw)
    with db:
        gap=db.list_raster_centreline_gaps(aid)[0]
        a,b=gap['candidate']['centreline_ids']
        db.review_raster_centreline_gap(gap['candidate_id'],actor='Engineer',
                  decision='SEPARATE_AS_DRAWN',reason='Line gap is not joined')
        # The network also contains duplicate-free raster contact proposals.
        for c in db.list_raster_network_contacts(nid):
            native=c['candidate']
            amap={sid:row['id'] for row in lines['centrelines'] for sid in row['source_stroke_ids']}
            linked=[amap.get(s) for s in native['stroke_ids']]
            if set(linked)=={a,b}:
                db.review_raster_network_contact(c['candidate_id'],actor='Engineer',
                     decision='CONTACT_AS_DRAWN',reason='Contact as reviewed on source')
                assert set(trace_reviewed_centrelines(db,aid,a)['centreline_ids'])=={a,b}
                break


def test_migrate_existing_v11_database_with_backup(tmp_path,source):
    x=read_pid(source,ReadParams(),filename='old.pdf');path=tmp_path/'old.sqlite'
    with ProjectStore(path) as db:eid=db.add_extraction(x,source_pdf_bytes=source)
    with sqlite3.connect(path) as c:
        for table in ('raster_centreline_decision','raster_centreline_gap','raster_centreline_analysis'):
            c.execute(f'DROP TABLE {table}')
        c.execute("UPDATE project_meta SET value='11' WHERE key='standalone_schema'")
    with ProjectStore(path) as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        assert db.export_extraction(eid)==x
        assert db.verify_audit_chain()
    with sqlite3.connect(next(tmp_path.glob('old.sqlite.pre-v12-*.sqlite'))) as b:
        assert b.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='11'


def test_cli_new_commands(tmp_path,source,raw,capsys):
    db,eid,rid,nid,aid,lines=_store(tmp_path,source,raw)
    db.close()
    path=tmp_path/'raster.sqlite'
    assert main(['raster-gaps',str(path),aid,'--limit','30'])==0
    assert len(json.loads(capsys.readouterr().out))==1
    assert main(['trace-raster-centrelines',str(path),aid,lines['centrelines'][0]['id']])==0
    assert 'physical plant connectivity' in capsys.readouterr().out
    assert main(['analyze-raster-centrelines',str(path),eid,rid,nid])==0
    assert json.loads(capsys.readouterr().out)['analysis_id']==aid


def test_spatial_index_scales_for_separated_strokes(raw):
    lines=[((x*70+10,y*85+10),(x*70+44,y*85+10)) for x in range(16) for y in range(10)]
    r=_input(raw,lines)
    out=build_raster_centrelines(r,build_raster_network(r))
    assert len(out['centrelines'])==160
    assert out['statistics']['gap_pair_checks']<600
    assert not out['gap_candidates']


def test_jsonschema_and_positive_reviewed_contact_trace(tmp_path,source,raw):
    from jsonschema import Draft202012Validator
    schema_path=Path(__file__).resolve().parents[1]/'contracts'/'standalone_raster_centrelines_v1.schema.json'
    schema=json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    r=_drawn(raw);n=build_raster_network(r);out=build_raster_centrelines(r,n)
    Draft202012Validator(schema).validate(out)
    # Two strokes meeting exactly on the page create an unresolved proposal,
    # not a graph edge, until the engineer reviews that exact source contact.
    connected=_input(raw,[((100,100),(180,100)),((180,100),(260,100))])
    net=build_raster_network(connected)
    assert net['contact_candidates']
    derived=build_raster_centrelines(connected,net)
    assert len(derived['centrelines'])==2
    assert not derived['gap_candidates']
    Draft202012Validator(schema).validate(derived)
    with ProjectStore(tmp_path/'review.sqlite') as db:
        x=read_pid(source,ReadParams(),filename='raster.pdf')
        eid=db.add_extraction(x,source_pdf_bytes=source)
        rid=db.add_raster_analysis(eid,connected)
        nid=db.add_raster_network_analysis(eid,rid,net)
        cid=db.add_raster_centreline_analysis(eid,rid,nid,derived)
        first=derived['centrelines'][0]['id']
        assert trace_reviewed_centrelines(db,cid,first)['centreline_ids']==[first]
        contact=db.list_raster_network_contacts(nid)[0]
        db.review_raster_network_contact(contact['candidate_id'],actor='Engineer',
               decision='CONTACT_AS_DRAWN',reason='Drawing line junction confirmed')
        assert len(trace_reviewed_centrelines(db,cid,first)['centreline_ids'])==2
        db.review_raster_network_contact(contact['candidate_id'],actor='Engineer',
               decision='NOT_CONTACT_AS_DRAWN',reason='Engineering source shows separate line')
        assert trace_reviewed_centrelines(db,cid,first)['centreline_ids']==[first]
        assert db.verify_audit_chain()


def test_cropped_rotation_frame_invariance(raw):
    from pid_reader.engineering.raster_network import _frame, _source
    import copy
    r=_drawn(raw)
    # Reproject the same strokes to a manufactured 90-degree rotated crop
    # while preserving the required source hash references and provenance.
    frame=copy.deepcopy(r['page_frames'][0])
    frame['transform']={'media_size':[600.,400.],'crop_origin':[0.,0.],
                         'render_size':[600.,400.],'rotation':90,
                         'coordinate_frame':'PDFPLUMBER_MEDIA_NORMALIZED_V1'}
    frame['width_px']=800;frame['height_px']=1200
    rotated=copy.deepcopy(r)
    rotated['page_frames']=[frame]
    # Existing media coords are invariant, but their rendered pixel frame moves.
    rotated['result_sha256']=sha256_hex(canonical_json({k:v for k,v in rotated.items() if k!='result_sha256'}).encode())
    from pid_reader.engineering.raster_geometry import validate_raster_result
    assert not validate_raster_result(rotated)
    net=build_raster_network(rotated)
    out=build_raster_centrelines(rotated,net)
    assert len(out['centrelines'])==7
    assert len(out['gap_candidates'])==1
    assert validate_raster_centrelines(out,rotated,net)==[]


def test_end_to_end_scan_only_pipeline_and_idempotent_analyses(tmp_path):
    from pid_reader.engineering.pipeline import analyze_drawing
    source_path=Path(__file__).resolve().parents[1]/'fixtures'/'synthetic_raster_centrelines_gaps.pdf'
    source=source_path.read_bytes()
    with ProjectStore(tmp_path/'scan.sqlite') as db:
        eid=db.add_extraction(read_pid(source,ReadParams(),filename=source_path.name),source_pdf_bytes=source)
        run=analyze_drawing(db,eid,ocr_engine=None)
        assert run['stages']['raster_centrelines']['status']=='DONE'
        assert run['counts']['raster_gaps']>=1
        assert run['counts']['raster_centrelines']>=5
        assert len(list_findings(db,eid,'raster_centrelines'))==run['counts']['raster_gaps']
        again=analyze_drawing(db,eid,ocr_engine=None)
        assert again['analyses']['raster_centrelines']==run['analyses']['raster_centrelines']
        assert db.verify_audit_chain()
        assert db.export_extraction(eid)['document']['sha256']==sha256_hex(source)
