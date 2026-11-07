"""Rev M source-bound path and drawing-set tests. Synthetic fixtures are not benchmarks."""
from __future__ import annotations

from io import BytesIO
from copy import deepcopy
from pathlib import Path
import json
import sqlite3

import pytest
from reportlab.pdfgen import canvas

from pid_reader.api import ReadParams, read_pid
from pid_reader.cli import main
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.topology import analyze_pdf_topology
from pid_reader.engineering.symbols import build_symbol_proposals
from pid_reader.engineering.linework import build_linework_proposals
from pid_reader.engineering.signal_links import build_signal_links
from pid_reader.engineering.signal_paths import trace_signal_path
from pid_reader.engineering.project_links import build_crosssheet_matches


def signal_fixture():
    out=BytesIO()
    c=canvas.Canvas(out,pagesize=(600,400),pageCompression=0,invariant=1)
    c.circle(110,260,24)
    c.drawCentredString(110,255,'PT-101')
    c.circle(410,260,24)
    c.drawCentredString(410,255,'PT-102')
    c.setDash(3,3)
    c.line(134,260,250,260)
    c.line(250,260,386,260)
    c.setDash()
    c.save()
    return out.getvalue()


def evidence():
    raw=signal_fixture()
    extraction=read_pid(raw,ReadParams(),filename='instrument-loop-not-proven.pdf')
    geometry=analyze_pdf_topology(raw)
    symbols=build_symbol_proposals(extraction,geometry)
    linework=build_linework_proposals(extraction,geometry,symbols)
    links=build_signal_links(extraction,geometry,symbols,linework)
    assert len(links['candidates'])==2
    assert len(geometry['contact_candidates'])==1
    return raw,extraction,geometry,symbols,linework,links


def test_trace_does_not_automatically_connect_or_claim_loop():
    _,e,g,s,l,sl=evidence()
    start=sl['candidates'][0]['segment_id']
    r=trace_signal_path(e,g,s,l,sl,{}, {}, start)
    assert len(r['segments'])==1
    assert r['contacts']==[]
    assert r['instrument_outline_endpoints']==[]
    assert 'loop' in r['limitations']
    assert trace_signal_path(e,g,s,l,sl,{}, {}, start)['result_sha256']==r['result_sha256']


def test_reviewed_stroke_and_endpoint_evidence_enables_trace():
    _,e,g,s,l,sl=evidence()
    start=sl['candidates'][0]['segment_id']
    contact=g['contact_candidates'][0]['id']
    reviews={c['id']:'SUPPORTED_AS_DRAWN' for c in sl['candidates']}
    result=trace_signal_path(e,g,s,l,sl,{contact:'CONNECTED_AS_DRAWN'},reviews,start)
    assert len(result['segments'])==2
    assert len(result['contacts'])==1
    assert len(result['instrument_outline_endpoints'])==2
    assert all(x['state']=='REVIEWED_ENDPOINT_AS_DRAWN' for x in result['instrument_outline_endpoints'])


def test_proposal_mode_keeps_unreviewed_distinct():
    _,e,g,s,l,sl=evidence()
    start=sl['candidates'][0]['segment_id']
    r=trace_signal_path(e,g,s,l,sl,{}, {}, start,include_unreviewed=True)
    assert len(r['segments'])==2
    assert all(x['state']=='UNREVIEWED_GEOMETRIC_CONTACT' for x in r['contacts'])
    assert all(x['state']=='UNREVIEWED_ENDPOINT_PROPOSAL' for x in r['instrument_outline_endpoints'])


def test_explicit_disconnection_overrides_proposal_mode():
    _,e,g,s,l,sl=evidence()
    start=sl['candidates'][0]['segment_id']
    r=trace_signal_path(e,g,s,l,sl,{g['contact_candidates'][0]['id']:'NOT_CONNECTED_AS_DRAWN'},
                        {},start,include_unreviewed=True)
    assert len(r['segments'])==1
    assert r['contacts']==[]


def test_signal_path_rejects_foreign_reviews_forgery_and_unknown_strokes():
    _,e,g,s,l,sl=evidence()
    start=sl['candidates'][0]['segment_id']
    with pytest.raises(ValueError,match='review'):
        trace_signal_path(e,g,s,l,sl,{'forged':'CONNECTED_AS_DRAWN'}, {},start)
    with pytest.raises(ValueError,match='review'):
        trace_signal_path(e,g,s,l,sl,{}, {'forged':'SUPPORTED_AS_DRAWN'},start)
    with pytest.raises(ValueError,match='Starting stroke'):
        trace_signal_path(e,g,s,l,sl,{}, {},'unknown')
    with pytest.raises(ValueError,match='hop'):
        trace_signal_path(e,g,s,l,sl,{}, {},start,max_hops=-1)
    forged=deepcopy(sl);forged['candidates'][0]['symbol_id']='forged'
    with pytest.raises(ValueError,match='Signal proposals'):
        trace_signal_path(e,g,s,l,forged,{}, {},start)


def stored_signal(db):
    raw,e,g,s,l,sl=evidence()
    eid=db.add_extraction(e,raw)
    gid=db.add_geometry_analysis(eid,g)
    sid=db.add_symbol_analysis(eid,gid,s)
    lid=db.add_linework_analysis(eid,gid,sid,l)
    aid=db.add_signal_analysis(eid,gid,sid,lid,sl)
    return eid,gid,sid,lid,aid,g,sl


def test_signal_trace_persists_snapshot_with_review_history(tmp_path):
    with ProjectStore(tmp_path/'test.sqlite') as db:
        eid,gid,sid,lid,aid,g,sl=stored_signal(db)
        start=sl['candidates'][0]['segment_id']
        draft=db.trace_signal(aid,start,persist=True)
        assert len(draft['segments'])==1
        saved=draft['persisted_trace_id']
        assert db.get_signal_trace_snapshot(saved)['result_sha256']==draft['result_sha256']
        geo=db.list_geometry_candidates(gid)[0]['candidate_id']
        db.review_geometry(geo,actor='Engineer One',decision='CONNECTED_AS_DRAWN',reason='Endpoint touch on drawing')
        for row in db.list_signal_candidates(aid):
            db.review_signal(row['candidate_id'],actor='Engineer One',decision='SUPPORTED_AS_DRAWN',
                             reason='Line terminates at outline')
        reviewed=db.trace_signal(aid,start,persist=True)
        assert len(reviewed['segments'])==2
        assert len(reviewed['instrument_outline_endpoints'])==2
        assert db.get_signal_trace_snapshot(saved)['result_sha256']==draft['result_sha256']
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute('DELETE FROM signal_trace_snapshot WHERE trace_id=?',(saved,))


def small_pdf(name):
    out=BytesIO();c=canvas.Canvas(out,pagesize=(350,250),pageCompression=0,invariant=1)
    c.drawString(40,150,'OFFPAGE ' + name);c.save()
    return out.getvalue()


def add_source(db,name,revision):
    raw=small_pdf(name)
    extracted=read_pid(raw,ReadParams(),filename=name+'.pdf',document_revision_id=revision)
    return db.add_extraction(extracted,raw)


def catalog(db,ids):
    for rev,eid in enumerate(ids):
        db.register_drawing(eid,drawing_no=f'PID-{rev+1}',revision_label='A',
                            facility='Test Plant',area='100',actor='Drawing reviewer',reason='Imported for review')


def mark(db,eid,label='TO SHEET B'):
    return db.annotate_offpage(eid,page=1,bbox={'x0':.1,'y0':.2,'x1':.2,'y1':.3},
                               label=label,actor='Drawing reviewer',reason='Arrow label read manually')


def test_crosssheet_matches_require_explicit_source_annotations(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        a=add_source(db,'Sheet-A','R1')
        b=add_source(db,'Sheet-B','R1')
        catalog(db,[a,b])
        aid, result=db.analyze_crosssheet([a,b])
        assert result['candidates']==[]
        assert db.trace_drawings(aid,a)['links']==[]
        mark(db,a);mark(db,b)
        mid, match=db.analyze_crosssheet([a,b])
        assert len(match['candidates'])==1
        assert match['candidates'][0]['state']=='PROPOSED_UNVERIFIED'
        rows=db.list_crosssheet_candidates(mid)
        assert len(rows)==1 and rows[0]['latest_review'] is None
        assert db.trace_drawings(mid,a)['links']==[]
        pro=db.trace_drawings(mid,a,include_unreviewed=True)
        assert len(pro['links'])==1 and pro['links'][0]['state']=='UNREVIEWED_MATCH_PROPOSAL'
        db.review_crosssheet(rows[0]['candidate_id'],actor='Engineer',decision='LINKED_AS_DRAWN',
                             reason='Matching connector on both sheets')
        accepted=db.trace_drawings(mid,a)
        assert len(accepted['links'])==1
        assert len(accepted['documents'])==2
        assert accepted['links'][0]['state']=='REVIEWED_MATCH_AS_DRAWN'
        assert db.verify_audit_chain()


def test_crosssheet_no_matching_labels_and_case_insensitive_matching(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        a=add_source(db,'Sheet-A','R1');b=add_source(db,'Sheet-B','R2')
        catalog(db,[a,b]);mark(db,a,'LINE 50');mark(db,b,'LINE 51')
        aid, result=db.analyze_crosssheet([a,b]);assert not result['candidates']
        mark(db,b,' line 50 ')
        aid, result=db.analyze_crosssheet([a,b]);assert len(result['candidates'])==1
        assert result['candidates'][0]['label_key']=='line 50'


def test_crosssheet_three_endpoints_remain_ambiguous(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        ids=[add_source(db,n,'R1') for n in ('A','B','C')]
        catalog(db,ids)
        for eid in ids:mark(db,eid,'PROCESS 111')
        _,result=db.analyze_crosssheet(ids)
        assert len(result['candidates'])==3
        assert all(x['ambiguity']=='MULTIPLE_CANDIDATE_ENDPOINTS' for x in result['candidates'])


def test_crosssheet_disconnection_and_revision_scope(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        a=add_source(db,'Sheet-A','R1');b=add_source(db,'Sheet-B','R1');c=add_source(db,'Sheet-B-v2','R2')
        catalog(db,[a,b,c]);mark(db,a);mark(db,b);mark(db,c)
        mid, result=db.analyze_crosssheet([a,b])
        rows=db.list_crosssheet_candidates(mid)
        assert len(rows)==1
        db.review_crosssheet(rows[0]['candidate_id'],actor='Engineer',decision='NOT_LINKED_AS_DRAWN',
                             reason='Does not represent connector')
        assert db.trace_drawings(mid,a,include_unreviewed=True)['links']==[]
        assert {r['extraction_id'] for r in db.list_drawings()}=={a,b,c}
        # The third imported revision was not selected and never appears in old analysis.
        assert c not in {x for x in result['selected_extractions']}


def test_project_catalogue_history_search_and_immutable_audit(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        a=add_source(db,'Drawing-A','R1')
        db.register_drawing(a,drawing_no='PD-100',revision_label='A',facility='Onshore',
                            area='Separation',actor='Alice',reason='Initial metadata')
        db.register_drawing(a,drawing_no='PD-100',revision_label='B',facility='Onshore',
                            area='Separation',actor='Bob',reason='Corrected drawing revision')
        rows=db.list_drawings(search='PD-100')
        assert len(rows)==1 and rows[0]['revision_label']=='B'
        assert db.db.execute('SELECT count(*) FROM drawing_registration').fetchone()[0]==2
        assert db.list_drawings(search='not-present')==[]
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute("UPDATE drawing_registration SET revision_label='Z'")


def test_rejects_invalid_bbox_page_and_unregistered_analysis(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        a=add_source(db,'A','R1');b=add_source(db,'B','R1')
        with pytest.raises(ValueError,match='Page'):
            db.annotate_offpage(a,page=2,bbox={'x0':.1,'y0':.2,'x1':.2,'y1':.3},
                                label='X',actor='Engineer',reason='Manual review')
        with pytest.raises(ValueError,match='bounding box'):
            db.annotate_offpage(a,page=1,bbox={'x0':.9,'y0':.2,'x1':.2,'y1':.3},
                                label='X',actor='Engineer',reason='Manual review')
        with pytest.raises(ValueError,match='registered'):
            db.analyze_crosssheet([a,b])


def test_crosssheet_source_hash_and_foreign_annotation_rejected():
    sources={'extA':'a'*64,'extB':'b'*64}
    good=[{'annotation_id':'aa','extraction_id':'extA','source_sha256':'a'*64,'label':'X'},
          {'annotation_id':'bb','extraction_id':'extB','source_sha256':'b'*64,'label':'X'}]
    assert len(build_crosssheet_matches(good,['extA','extB'],sources)['candidates'])==1
    bad=deepcopy(good);bad[1]['source_sha256']='f'*64
    with pytest.raises(ValueError,match='mismatch'):
        build_crosssheet_matches(bad,['extA','extB'],sources)
    bad=deepcopy(good);bad[1]['annotation_id']='aa'
    with pytest.raises(ValueError,match='Duplicate'):
        build_crosssheet_matches(bad,['extA','extB'],sources)


def test_crosssheet_review_requires_name_and_reason(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        a=add_source(db,'A','R1');b=add_source(db,'B','R1')
        catalog(db,[a,b]);mark(db,a);mark(db,b)
        mid,_=db.analyze_crosssheet([a,b]);cand=db.list_crosssheet_candidates(mid)[0]['candidate_id']
        with pytest.raises(ValueError):
            db.review_crosssheet(cand,actor='',decision='LINKED_AS_DRAWN',reason='Not sure')
        with pytest.raises(ValueError):
            db.review_crosssheet(cand,actor='Engineer',decision='LINKED_AS_DRAWN',reason='')
        with pytest.raises(ValueError):
            db.review_crosssheet(cand,actor='Engineer',decision='APPROVED_FOR_PLANT',reason='Bad choice')


def test_rev_l_database_upgrades_to_v7_and_creates_backup(tmp_path):
    dbfile=tmp_path/'legacy.sqlite'
    with ProjectStore(dbfile) as db:
        add_source(db,'Legacy','R1')
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='12'
    with sqlite3.connect(dbfile) as connection:
        # Mimic the former v6 metadata on the same additive schema. No destructive migration.
        connection.execute("UPDATE project_meta SET value='6' WHERE key='standalone_schema'")
    with ProjectStore(dbfile) as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='12'
        assert db.db.execute('SELECT count(*) FROM extraction').fetchone()[0]==1
        assert db.verify_audit_chain()
    backups=list(tmp_path.glob('legacy.sqlite.pre-v12-*.sqlite'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as old:
        assert old.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='6'


def test_cli_project_catalogue(tmp_path,capsys):
    name=str(tmp_path/'db.sqlite')
    with ProjectStore(name) as db:
        eid=add_source(db,'CLIDrawing','R1')
    assert main(['register-drawing',name,eid,'--drawing-no','PID-010','--revision','A',
                 '--facility','Test','--area','Utilities','--actor','Engineer','--reason','Imported by reviewer'])==0
    assert main(['drawings',name,'--search','PID-010'])==0
    output=capsys.readouterr().out
    assert 'PID-010' in output


def test_dashed_crossing_not_assumed_connected():
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(500,350),pageCompression=0,invariant=1)
    c.setDash(3,3);c.line(60,160,420,160);c.line(240,70,240,270);c.setDash();c.save()
    raw=stream.getvalue()
    e=read_pid(raw,ReadParams())
    g=analyze_pdf_topology(raw)
    s=build_symbol_proposals(e,g)
    l=build_linework_proposals(e,g,s)
    sl=build_signal_links(e,g,s,l)
    crosses=[x for x in g['contact_candidates'] if x['kind']=='CROSSING_AMBIGUOUS']
    assert len(crosses)==1
    first=g['segments'][0]['id']
    r=trace_signal_path(e,g,s,l,sl,{}, {},first)
    assert len(r['segments'])==1
    assert r['contacts']==[]
    proposal=trace_signal_path(e,g,s,l,sl,{}, {},first,include_unreviewed=True)
    assert len(proposal['segments'])==2
    assert proposal['contacts'][0]['state']=='UNREVIEWED_GEOMETRIC_CONTACT'
    reviewed=trace_signal_path(e,g,s,l,sl,{crosses[0]['id']:'CONNECTED_AS_DRAWN'}, {},first)
    assert len(reviewed['segments'])==2
    assert reviewed['contacts'][0]['state']=='REVIEWED_CONNECTED_AS_DRAWN'


def test_rev_m_standalone_output_schemas_are_valid():
    import jsonschema
    base=Path(__file__).resolve().parents[1]/'contracts'
    _,e,g,s,l,sl=evidence()
    result=trace_signal_path(e,g,s,l,sl,{}, {},sl['candidates'][0]['segment_id'])
    jsonschema.validate(result,json.loads((base/'standalone_signal_path_v1.schema.json').read_text()))
    keys={'one':'a'*64,'two':'b'*64}
    matches=build_crosssheet_matches([{'annotation_id':'a1','extraction_id':'one','source_sha256':'a'*64,'label':'REF-1'},
                                     {'annotation_id':'a2','extraction_id':'two','source_sha256':'b'*64,'label':'REF-1'}],
                                     ['one','two'],keys)
    jsonschema.validate(matches,json.loads((base/'standalone_crosssheet_v1.schema.json').read_text()))


def test_actual_v6_project_fixture_migrates_without_losing_rows(tmp_path):
    import shutil
    original=Path(__file__).resolve().parents[1]/'fixtures'/'legacy_v6_demo.sqlite'
    output=tmp_path/'migrating_old.sqlite'
    shutil.copy2(original,output)
    with sqlite3.connect(output) as connection:
        old_version=connection.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]
        old_count=connection.execute('SELECT count(*) FROM extraction').fetchone()[0]
    assert old_version=='6'
    with ProjectStore(output) as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='12'
        assert db.db.execute('SELECT count(*) FROM extraction').fetchone()[0]==old_count
        assert db.verify_audit_chain()
    assert list(tmp_path.glob('migrating_old.sqlite.pre-v12-*.sqlite'))


def test_crosssheet_snapshot_does_not_reinterpret_old_drawing_metadata(tmp_path):
    with ProjectStore(tmp_path/'db.sqlite') as db:
        a=add_source(db,'SHEET-OLD','A');b=add_source(db,'SHEET-OTHER','A')
        catalog(db,[a,b]);mark(db,a);mark(db,b)
        aid,result=db.analyze_crosssheet([a,b])
        cand=db.list_crosssheet_candidates(aid)[0]['candidate_id']
        db.review_crosssheet(cand,actor='Engineer',decision='LINKED_AS_DRAWN',
                             reason='Drawing connector labels match')
        before=db.trace_drawings(aid,a)['documents']
        db.register_drawing(a,drawing_no='CORRECTED-NUMBER',revision_label='B',
                            facility='Test Plant',area='100',actor='Engineer',reason='Metadata correction')
        after=db.trace_drawings(aid,a)['documents']
        assert before==after
        assert db.list_drawings(search='CORRECTED-NUMBER')[0]['revision_label']=='B'
        assert result['drawing_catalogue_snapshot'][a]['drawing_no']=='PID-1'
