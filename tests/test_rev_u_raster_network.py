"""Rev U synthetic geometry and source-linked raster-network regression.

The hand-authored Hough observations exercise graph logic; independently
rendered scan-only drawings are smoke tested separately. Neither proves
industrial piping accuracy.
"""
from __future__ import annotations

from io import BytesIO
import copy
import json
import sqlite3
from pathlib import Path

import pytest
import pdfplumber
from reportlab.pdfgen.canvas import Canvas

from pid_reader.api import ReadParams,read_pid,canonical_json,sha256_hex,stable_id,LimitExceeded
from pid_reader.engineering.raster_geometry import analyze_raster_geometry, ALGORITHM as RASTER_ALGORITHM,validate_raster_result
from pid_reader.engineering.raster_network import build_raster_network,validate_raster_network,_source,_frame
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.pipeline import analyze_drawing
from pid_reader.engineering.findings import list_findings,review_finding
from pid_reader.cli import main

ROOT=Path(__file__).resolve().parents[1]
DRAWING=ROOT/'fixtures'/'synthetic_raster_outline_valves.pdf'

@pytest.fixture(scope='module')
def source():return DRAWING.read_bytes()

@pytest.fixture(scope='module')
def raw(source):return analyze_raster_geometry(source)


def _input(raw,geometry):
    result=copy.deepcopy(raw)
    result['filled_valve_candidates']=[]
    result['outline_valve_candidates']=[]
    result['stroke_candidates']=[]
    frame=result['page_frames'][0];f=_frame(frame)
    for a,b in geometry:
        points=[_source(f,frame,a),_source(f,frame,b)]
        # Raster-stroke identities normally sort the observed pixel endpoints;
        # for test data retain each pair's lexical direction deterministically.
        sid=stable_id('raster-stroke',result['source_sha256'],1,points[0],points[1],RASTER_ALGORITHM)
        result['stroke_candidates'].append({'id':sid,'page':1,'endpoints':points,
            'status':'PROPOSED_UNVERIFIED','role':'RASTER_LINEWORK_UNKNOWN',
            'limitations':'Unverified synthetic drawing geometry; no process connection.'})
    result['stroke_candidates'].sort(key=lambda c:c['id'])
    result['result_sha256']=sha256_hex(canonical_json({k:v for k,v in result.items() if k!='result_sha256'}).encode())
    assert validate_raster_result(result)==[]
    return result


def _lines():
    return [((100,100),(200,100)),((200,100),(280,100)),
            ((120,230),(220,230)),((170,195),(170,265)),
            ((350,160),(450,160)),((410,160),(410,210)),
            ((100,320),(220,320)),((102,320),(218,320)),
            ((400,355),(500,355)),((2,2),(650,2))]


def _ocr(source_hash,frame,bbox):
    f=_frame(frame)
    a=_source(f,frame,(bbox[0],bbox[1]));b=_source(f,frame,(bbox[2],bbox[3]))
    box={'x0':a[0],'y0':a[1],'x1':b[0],'y1':b[1]}
    word={'id':stable_id('ocr',source_hash,1,box,'LABEL-101'),
          'text':'LABEL-101','page':1,'bbox':box,
          'raw_ocr_score':.89,'review_state':'PROPOSED','engine':'local_tesseract'}
    r={'adapter':'standalone_ocr_preview_v3','source_sha256':source_hash,
       'algorithm':'tesseract-word-ocr-v3','coordinate_frame':'PDFPLUMBER_MEDIA_NORMALIZED_V1',
       'engine_version':'synthetic-test','dpi':144,'selected_pages':[1],
       'page_count':1,'pages':[{'page':1,'render_transform':copy.deepcopy(frame['transform']),
                                'words':[word],'limitations':'Synthetic OCR evidence, unverified'}],
       'limitations':'Synthetic OCR evidence, unverified'}
    r['result_sha256']=sha256_hex(canonical_json(r).encode())
    return r


def test_clean_negative_and_positive_contact_cases(raw):
    r=_input(raw,_lines())
    out=build_raster_network(r)
    counts={row['kind'] for row in out['contact_candidates']}
    assert {'ENDPOINT_TOUCH_UNRESOLVED','T_JUNCTION_UNRESOLVED','CROSSING_UNRESOLVED'} <= counts
    assert out['duplicate_observation_groups']
    assert len(out['stroke_evidence'])==len(_lines())
    assert all(c['status']=='UNRESOLVED' and 'not verified' in c['limitations'] for c in out['contact_candidates'])
    assert validate_raster_network(out,r)==[]
    assert out==build_raster_network(r)
    assert out['statistics']['context_excluded_strokes']==1
    assert out['warnings'][0].startswith('TEXT_MASK_NOT_AVAILABLE')


def test_ocr_mask_suppresses_contextual_text_strokes_not_all_neighbouring_strokes(raw):
    r=_input(raw,_lines())
    o=_ocr(r['source_sha256'],r['page_frames'][0],(397,351,504,359))
    out=build_raster_network(r,o)
    roles={e['role'] for e in out['stroke_evidence']}
    assert 'OCR_TEXT_OVERLAP_UNRESOLVED' in roles
    assert 'UNCLASSIFIED_LINEWORK' in roles
    assert 'PAGE_FRAME_STROKE_CANDIDATE' in roles
    assert out['ocr_result_sha256']==o['result_sha256']
    assert out['statistics']['context_excluded_strokes']==1
    assert any('OCR_WORD_BOXES_PROVISIONAL' in x for x in out['warnings'])
    assert validate_raster_network(out,r,o)==[]


def test_mismatched_ocr_source_and_transform_refused(raw):
    r=_input(raw,_lines())
    o=_ocr(r['source_sha256'],r['page_frames'][0],(397,351,504,359))
    o['source_sha256']='a'*64
    o['result_sha256']=sha256_hex(canonical_json({k:v for k,v in o.items() if k!='result_sha256'}).encode())
    with pytest.raises(ValueError,match='source hashes differ'):build_raster_network(r,o)
    o=_ocr(r['source_sha256'],r['page_frames'][0],(397,351,504,359))
    o['pages'][0]['render_transform']['rotation']=180
    o['result_sha256']=sha256_hex(canonical_json({k:v for k,v in o.items() if k!='result_sha256'}).encode())
    with pytest.raises(ValueError,match='transforms disagree'):build_raster_network(r,o)


def test_rehashed_forged_contact_rejected(raw):
    r=_input(raw,_lines());out=build_raster_network(r)
    forged=copy.deepcopy(out)
    forged['contact_candidates'][0]['kind']='VERIFIED_PIPE_CONNECTION'
    forged['result_sha256']=sha256_hex(canonical_json({k:v for k,v in forged.items() if k!='result_sha256'}).encode())
    assert validate_raster_network(forged,r)


def test_cropped_rotated_source_frame_roundtrip(raw):
    frame=copy.deepcopy(raw['page_frames'][0]);transform=frame['transform']
    # Synthetic crop in the source MediaBox frame; no PDF renderer needed.
    transform['crop_origin']=[20.,30.]
    transform['render_size']=[250.,200.]
    transform['media_size']=[300.,260.]
    transform['rotation']=90
    frame['width_px']=500;frame['height_px']=400
    f=_frame(frame)
    for point in ((10.,15.),(330.,250.),(499.,399.)):
        media=_source(f,frame,point)
        nx,ny=f.media_to_render(*media)
        assert nx==pytest.approx(point[0]/500,abs=1e-6)
        assert ny==pytest.approx(point[1]/400,abs=1e-6)


def test_large_separated_set_stays_bounded(raw):
    # Hundreds of spatially separated lines do not cause quadratic pair work.
    lines=[((10+x*120,10+y*100),(50+x*120,10+y*100))
           for y in range(4) for x in range(7)]
    out=build_raster_network(_input(raw,lines))
    assert out['statistics']['pair_checks']<=8
    assert out['contact_candidates']==[]


def test_database_persistence_review_audit_and_idempotence(tmp_path,source,raw):
    extract=read_pid(source,ReadParams(),filename='raster.pdf')
    with ProjectStore(tmp_path/'project.sqlite') as db:
        eid=db.add_extraction(extract,source_pdf_bytes=source)
        rid=db.add_raster_analysis(eid,raw)
        context=build_raster_network(raw)
        aid=db.add_raster_network_analysis(eid,rid,context)
        assert aid==db.add_raster_network_analysis(eid,rid,context)
        assert db.get_raster_network_analysis(aid)==context
        rows=db.list_raster_network_contacts(aid)
        assert rows
        cand=rows[0]['candidate_id']
        with pytest.raises(ValueError):
            db.review_raster_network_contact(cand,actor='',decision='CONTACT_AS_DRAWN',reason='observed')
        with pytest.raises(KeyError):
            db.review_raster_network_contact('fake',actor='Engineer',decision='UNRESOLVED',reason='Await review')
        d=db.review_raster_network_contact(cand,actor='Engineer',decision='UNRESOLVED',reason='Check source legend')
        assert db.latest_raster_network_review(cand)['decision']=='UNRESOLVED'
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('DELETE FROM raster_network_decision WHERE decision_id=?',(d,))
        assert db.export_extraction(eid)==extract
        finding=list_findings(db,eid,'raster_network')
        assert any(f['id']==cand for f in finding)
        review_finding(db,'raster_network',cand,actor='Engineer',decision='NOT_CONTACT_AS_DRAWN',reason='Separate ink only')
        assert db.latest_raster_network_review(cand)['decision']=='NOT_CONTACT_AS_DRAWN'


def test_database_wrong_raster_or_ocr_reference_rejected(tmp_path,source,raw):
    extract=read_pid(source,ReadParams(),filename='raster.pdf')
    with ProjectStore(tmp_path/'project.sqlite') as db:
        eid=db.add_extraction(extract,source_pdf_bytes=source)
        aid=db.add_raster_analysis(eid,raw)
        r=build_raster_network(raw)
        with pytest.raises(ValueError,match='mismatch'):
            db.add_raster_network_analysis('fake',aid,r)
        with pytest.raises(ValueError,match='mismatch'):
            db.add_raster_network_analysis(eid,aid,r,ocr_analysis_id='fake')
        r['source_sha256']='0'*64
        with pytest.raises(ValueError,match='Invalid derived'):
            db.add_raster_network_analysis(eid,aid,r)


def test_migration_v10_creates_backup_preserves_source(tmp_path,source):
    extract=read_pid(source,ReadParams(),filename='source.pdf')
    path=tmp_path/'previous.sqlite'
    with ProjectStore(path) as db:
        eid=db.add_extraction(extract,source_pdf_bytes=source)
    with sqlite3.connect(path) as db:
        for name in ('raster_network_decision','raster_network_candidate','raster_network_analysis'):
            db.execute(f'DROP TABLE {name}')
        db.execute("UPDATE project_meta SET value='10' WHERE key='standalone_schema'")
        db.commit()
    with ProjectStore(path) as upgraded:
        assert upgraded.migration_backup is not None
        assert upgraded.export_extraction(eid)==extract
        assert upgraded.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        assert upgraded.verify_audit_chain()
    with sqlite3.connect(next(tmp_path.glob('previous.sqlite.pre-v12-*.sqlite'))) as old:
        assert old.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='10'


def test_cli_and_pipeline_integration(tmp_path,source,capsys):
    dbpath=str(tmp_path/'project.sqlite');pdf=tmp_path/'drawing.pdf';pdf.write_bytes(source)
    assert main(['import-pdf',dbpath,str(pdf),'--ocr','off'])==0
    with ProjectStore(dbpath) as db:
        eid=db.db.execute('SELECT extraction_id FROM extraction').fetchone()[0]
    assert main(['analyze-raster',dbpath,eid])==0
    aid=json.loads(capsys.readouterr().out.splitlines()[-1])['analysis_id']
    assert main(['analyze-raster-network',dbpath,eid,aid])==0
    out=json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out['analysis_id']
    assert main(['raster-contacts',dbpath,out['analysis_id']])==0
    contacts=json.loads(capsys.readouterr().out)
    assert contacts
    assert main(['review-raster-contact',dbpath,contacts[0]['candidate_id'],
                 '--actor','Engineer','--decision','UNRESOLVED',
                 '--reason','Pending drawing check'])==0
    with ProjectStore(dbpath) as db:
        summary=analyze_drawing(db,eid,ocr_engine=None,use_example_catalogue=False)
        assert summary['stages']['raster_network']['status']=='DONE'
        assert 'raster_network' in summary['analyses']


def test_host_r1_does_not_gain_raster_network_keys(source):
    r=read_pid(source,ReadParams())
    assert r['schema_version']==1
    assert 'contact_candidates' not in r and 'raster_network' not in r


def test_new_schema_and_real_scan_only_fixture():
    import jsonschema
    p=ROOT/'fixtures'/'synthetic_raster_network_context.pdf'
    source=p.read_bytes()
    with pdfplumber.open(BytesIO(source)) as doc:
        assert doc.pages[0].lines==[]
    raster=analyze_raster_geometry(source)
    result=build_raster_network(raster)
    schema=json.loads((ROOT/'contracts'/'standalone_raster_network_v1.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(result,schema)
    assert len(raster['stroke_candidates'])>20
    assert result['statistics']['duplicate_observation_groups']>0
    assert len(result['contact_candidates'])<len(raster['stroke_candidates'])*2
    assert any(item['kind']=='CROSSING_UNRESOLVED' for item in result['contact_candidates'])
    assert any(item['role']=='PAGE_FRAME_STROKE_CANDIDATE' for item in result['stroke_evidence'])
    assert validate_raster_network(result,raster)==[]


def test_local_ocr_misread_does_not_silently_erase_drawing_contacts():
    from pid_reader.formats.ocr_source import ocr_pdf_preview, tesseract_available
    if not tesseract_available():pytest.skip('Local Tesseract not installed')
    source=(ROOT/'fixtures'/'synthetic_raster_network_context.pdf').read_bytes()
    raster=analyze_raster_geometry(source)
    no_ocr=build_raster_network(raster)
    ocr=ocr_pdf_preview(source,pages=(1,),engine='tesseract')
    with_ocr=build_raster_network(raster,ocr)
    assert no_ocr['statistics']['contact_proposals']==with_ocr['statistics']['contact_proposals']
    assert with_ocr['ocr_result_sha256']==ocr['result_sha256']
    assert any('OCR_WORD_BOXES_PROVISIONAL' in w for w in with_ocr['warnings'])
    assert any(s['role']=='OCR_TEXT_OVERLAP_UNRESOLVED' for s in with_ocr['stroke_evidence'])
    assert validate_raster_network(with_ocr,raster,ocr)==[]


def test_bounded_pair_budget_refuses_without_partial_result(raw,monkeypatch):
    from pid_reader.engineering import raster_network
    r=_input(raw,_lines())
    monkeypatch.setattr(raster_network,'MAX_PAIR_CHECKS',1)
    with pytest.raises(LimitExceeded,match='budget'):
        raster_network.build_raster_network(r)


def test_real_cropped_rotated_raster_context(source):
    from pypdf import PdfReader,PdfWriter
    reader=PdfReader(BytesIO(source))
    page=reader.pages[0]
    page.cropbox.lower_left=(30,30)
    page.cropbox.upper_right=(450,350)
    page.rotate(90)
    writer=PdfWriter();writer.add_page(page)
    bio=BytesIO();writer.write(bio)
    cropped=bio.getvalue()
    r=analyze_raster_geometry(cropped)
    out=build_raster_network(r)
    assert validate_raster_network(out,r)==[]
    assert all(0<=q<=1 for c in out['contact_candidates'] for q in c['point'])


def test_sqlite_rejects_mutation_of_derived_contact_rows(tmp_path,source,raw):
    extraction=read_pid(source,ReadParams(),filename='scan.pdf')
    with ProjectStore(tmp_path/'immutable.sqlite') as db:
        eid=db.add_extraction(extraction,source_pdf_bytes=source)
        rid=db.add_raster_analysis(eid,raw)
        aid=db.add_raster_network_analysis(eid,rid,build_raster_network(raw))
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('UPDATE raster_network_analysis SET result_hash=? WHERE analysis_id=?',('0'*64,aid))
        cid=db.list_raster_network_contacts(aid)[0]['candidate_id']
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('DELETE FROM raster_network_candidate WHERE candidate_id=?',(cid,))
        assert db.verify_audit_chain()
