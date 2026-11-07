"""Rev L: source-verified signal hypotheses, project tag conventions and crop coordinates."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
import sqlite3

import pytest
from pypdf import PdfReader,PdfWriter
from reportlab.pdfgen import canvas

from pid_reader.api import ReadParams,read_pid,canonical_json,sha256_hex
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.topology import analyze_pdf_topology
from pid_reader.engineering.symbols import build_symbol_proposals
from pid_reader.engineering.linework import build_linework_proposals
from pid_reader.engineering.signal_links import build_signal_links,validate_signal_links
from pid_reader.engineering.tag_profiles import (parse_tag,validate_profile,example_profile,
    profile_hash,evaluate_text_links,validate_profiled_tags)
from pid_reader.formats.page_coordinates import frame_from_pdfplumber,PageFrame
from pid_reader.formats.ocr_source import ocr_pdf_preview


def signal_pdf() -> bytes:
    stream=BytesIO()
    c=canvas.Canvas(stream,pagesize=(600,400),pageCompression=0,invariant=1)
    c.circle(180,250,25);c.drawCentredString(180,246,'PT-101')
    c.setDash(3,3);c.line(205,250,290,250);c.setDash()
    c.line(155,250,120,250)
    c.circle(180,100,25);c.drawCentredString(180,96,'PT-102')
    c.setDash(3,3);c.line(120,100,240,100);c.setDash()
    c.save()
    return stream.getvalue()


def evidence():
    src=signal_pdf();e=read_pid(src,ReadParams());g=analyze_pdf_topology(src)
    s=build_symbol_proposals(e,g);l=build_linework_proposals(e,g,s)
    return src,e,g,s,l,build_signal_links(e,g,s,l)


def test_signal_endpoint_contact_is_proposal_only():
    src,e,g,s,l,links=evidence()
    assert len(links['candidates']) == 1
    c=links['candidates'][0]
    assert c['segment_style']=='DASHED_OR_DOTTED'
    assert c['review_state']=='PROPOSED_UNVERIFIED'
    assert c['candidate_kind']=='SIGNAL_STYLE_ENDPOINT_TO_INSTRUMENT_OUTLINE'
    assert validate_signal_links(links,e,g,s,l)==[]
    assert 'signal_links' not in e
    assert len(e['loop_proposals'])==0


def test_signal_detection_is_deterministic_and_false_crossing_is_not_connected():
    _,e,g,s,l,out=evidence()
    assert out == build_signal_links(e,g,s,l)
    assert len([x for x in l['stroke_roles'] if x['role']=='SIGNAL_STYLE_CANDIDATE'])==2
    assert len(out['candidates'])==1


def test_signal_rehashed_forgery_is_rejected():
    _,e,g,s,l,out=evidence()
    tampered=deepcopy(out)
    tampered['candidates'][0]['point']=[.2,.2]
    tampered['result_sha256']=sha256_hex(canonical_json({k:v for k,v in tampered.items() if k!='result_sha256'}).encode())
    assert validate_signal_links(tampered,e,g,s,l)


def test_cross_document_signal_rejected():
    _,e,g,s,l,out=evidence()
    changed=deepcopy(e)
    changed['document']['sha256']='f'*64
    with pytest.raises(ValueError):
        build_signal_links(changed,g,s,l)


def test_signal_decisions_are_append_only_and_audited(tmp_path):
    src,e,g,s,l,out=evidence()
    with ProjectStore(tmp_path/'project.sqlite') as db:
        eid=db.add_extraction(e,source_pdf_bytes=src)
        gid=db.add_geometry_analysis(eid,g)
        sid=db.add_symbol_analysis(eid,gid,s)
        lid=db.add_linework_analysis(eid,gid,sid,l)
        aid=db.add_signal_analysis(eid,gid,sid,lid,out)
        assert db.add_signal_analysis(eid,gid,sid,lid,out)==aid
        candidates=db.list_signal_candidates(aid)
        assert len(candidates)==1
        cid=candidates[0]['candidate_id']
        assert candidates[0]['latest_review'] is None
        db.review_signal(cid,actor='Engineer One',decision='SUPPORTED_AS_DRAWN',reason='Drawing line terminates on instrument ring')
        db.review_signal(cid,actor='Engineer Two',decision='UNRESOLVED',reason='Instrument legend must be checked')
        assert db.latest_signal_review(cid)['decision']=='UNRESOLVED'
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute("DELETE FROM signal_decision WHERE candidate_id=?",(cid,))
        assert db.verify_audit_chain()


def test_signal_db_blocks_forged_rehashed_input(tmp_path):
    src,e,g,s,l,out=evidence()
    with ProjectStore(tmp_path/'project.sqlite') as db:
        eid=db.add_extraction(e,source_pdf_bytes=src)
        gid=db.add_geometry_analysis(eid,g);sid=db.add_symbol_analysis(eid,gid,s)
        lid=db.add_linework_analysis(eid,gid,sid,l)
        forged=deepcopy(out);forged['candidates'][0]['point']=[.5,.5]
        forged['result_sha256']=sha256_hex(canonical_json({k:v for k,v in forged.items() if k!='result_sha256'}).encode())
        with pytest.raises(ValueError):
            db.add_signal_analysis(eid,gid,sid,lid,forged)


def test_profile_parser_handles_site_conventions_without_training():
    profile=example_profile()
    profile['separators']=['-','_','.','']
    a=parse_tag('PT_101',profile)
    assert len(a)==1 and a[0]['class_proposal']=='INSTRUMENT'
    assert parse_tag('P.007A',profile)[0]['class_proposal']=='PUMP'
    assert parse_tag('V-123',profile)[0]['class_proposal']=='VESSEL'
    assert parse_tag('XX-123',profile)==[]
    assert parse_tag('PT_101; SELECT *',profile)==[]


def test_profiles_preserve_ambiguity_without_uncontrolled_regex():
    profile=example_profile()
    profile['prefix_classes']['PT']=['INSTRUMENT','OTHER']
    results=parse_tag('PT-101',profile)
    assert {x['class_proposal'] for x in results}=={'INSTRUMENT','OTHER'}
    p=deepcopy(profile);p['prefix_classes']={'(a+)+':['INSTRUMENT']}
    with pytest.raises(ValueError):validate_profile(p)


def test_versioned_profile_immutable_and_audited(tmp_path):
    profile=example_profile()
    with ProjectStore(tmp_path/'p.sqlite') as db:
        a=db.register_tag_profile(profile)
        assert db.register_tag_profile(profile)==a
        assert db.get_tag_profile(a)==profile
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute('DELETE FROM tag_profile WHERE profile_id=?',(a,))
        assert db.verify_audit_chain()
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='9'


def test_source_tag_profile_evaluation_is_reproducible(tmp_path):
    from test_text_links import layers
    source,e,g,s,ocr,links=layers()
    profile=example_profile()
    result=evaluate_text_links(links,profile)
    assert not validate_profiled_tags(result,links)
    assert result['tag_profile_sha256']==profile_hash(profile)
    assert any(x['class_hypotheses'] for p in result['entries'] for x in p['alternatives'])
    with ProjectStore(tmp_path/'p.sqlite') as db:
        eid=db.add_extraction(e,source_pdf_bytes=source)
        gid=db.add_geometry_analysis(eid,g)
        sid=db.add_symbol_analysis(eid,gid,s)
        oid=db.add_ocr_analysis(eid,ocr)
        tid=db.add_text_link_analysis(eid,sid,oid,links)
        pid=db.register_tag_profile(profile)
        aid,got=db.evaluate_tag_profile(tid,pid)
        assert got==result
        assert db.evaluate_tag_profile(tid,pid)[0]==aid
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute('DELETE FROM tag_profile_evaluation WHERE evaluation_id=?',(aid,))


def test_profile_evaluation_rejects_rehash_edited_records():
    from test_text_links import layers
    links=layers()[-1]
    output=evaluate_text_links(links,example_profile())
    bad=deepcopy(output);bad['entries'][0]['alternatives'].append({'source_text':'INVENTED'})
    bad['result_sha256']=sha256_hex(canonical_json({k:v for k,v in bad.items() if k!='result_sha256'}).encode())
    assert validate_profiled_tags(bad,links)


def cropped_rotated_pdf(rotation: int) -> bytes:
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(600,400),invariant=1,pageCompression=0)
    c.line(140,140,300,140);c.drawString(160,200,'PT-101');c.save()
    original=PdfReader(BytesIO(stream.getvalue()));p=original.pages[0]
    p.cropbox.lower_left=(90,50);p.cropbox.upper_right=(510,350)
    p.rotate(rotation)
    writer=PdfWriter();writer.add_page(p)
    out=BytesIO();writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_render_crop_transform_round_trip_matches_rotated_page(rotation):
    import pdfplumber
    src=cropped_rotated_pdf(rotation)
    with pdfplumber.open(BytesIO(src)) as pdf:
        page=pdf.pages[0]
        frame=frame_from_pdfplumber(page)
        assert frame.rotation == rotation
        assert (frame.crop_width,frame.crop_height) == ((420,300) if rotation in (0,180) else (300,420))
        for point in ((.3,.35),(.5,.5),(.65,.6)):
            # Source points inside the crop are reversible in rendered coordinates.
            try: ux,uy=frame.media_to_render(*point)
            except ValueError: continue
            x,y=frame.render_to_media(ux,uy)
            assert (x,y)==pytest.approx(point,abs=1e-9)
        line=page.lines[0]
        x,y=line['pts'][0]
        media=(x/frame.media_width,y/frame.media_height)
        crop=frame.media_to_render(*media)
        assert 0<=crop[0]<=1 and 0<=crop[1]<=1
        assert frame.render_to_media(*crop)==pytest.approx(media,abs=1e-9)


def test_ocr_preview_returns_media_frame_after_crop_rotation(monkeypatch):
    pytest.importorskip('pypdfium2')
    pytess=pytest.importorskip('pytesseract')
    src=cropped_rotated_pdf(90)
    def fake_words(image,*,output_type,timeout):
        return {'text':['PT-101'],'conf':['90'],'left':[30],'top':[40],'width':[80],'height':[20]}
    monkeypatch.setattr(pytess,'image_to_data',fake_words)
    result=ocr_pdf_preview(src,dpi=144)
    assert result['adapter']=='standalone_ocr_preview_v3'
    assert result['coordinate_frame']=='PDFPLUMBER_MEDIA_NORMALIZED_V1'
    page=result['pages'][0]
    meta=page['render_transform']
    assert meta['rotation']==90
    assert meta['render_size']==[300.,420.]
    frame=PageFrame(meta['media_size'][0],meta['media_size'][1],*meta['crop_origin'],*meta['render_size'],meta['rotation'])
    box=page['words'][0]['bbox']
    left=30/(300*2);top=40/(420*2)
    assert box['x0']==pytest.approx(frame.render_to_media(left,top)[0],abs=1e-6)
    assert box['y0']==pytest.approx(frame.render_to_media(left,top)[1],abs=1e-6)
    # MediaBox coordinates remain valid for storage and matching against pdfplumber.
    assert box['x0']>left


def test_invalid_frame_rejected():
    with pytest.raises(ValueError):PageFrame(100,100,80,0,40,50,0)
    with pytest.raises(ValueError):PageFrame(100,100,0,0,100,100,45)
    f=PageFrame(100,100,0,0,100,100,0)
    with pytest.raises(ValueError):f.render_to_media(-.1,.5)


def test_v5_database_upgrade_creates_backup(tmp_path):
    dbfile=tmp_path/'legacy.sqlite'
    with ProjectStore(dbfile) as db:
        db.db.execute("UPDATE project_meta SET value='5' WHERE key='standalone_schema'")
        # This produces a stale version label but retains the v6 tables. For a
        # real old database we must remove new schema objects before reopen.
        names=[r[0] for r in db.db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND (name LIKE 'block_%signal_%' OR name LIKE 'block_%tag_%')")]
        for name in names:db.db.execute(f'DROP TRIGGER "{name}"')
        for table in ('signal_decision','signal_candidate','signal_analysis','tag_profile_evaluation','tag_profile'):
            db.db.execute(f'DROP TABLE {table}')
        db.db.commit()
    with ProjectStore(dbfile) as db:
        assert db.migration_backup is not None and db.migration_backup.exists()
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='9'
        assert db.verify_audit_chain()
    with sqlite3.connect(next(tmp_path.glob('legacy.sqlite.pre-v9-*.sqlite'))) as old:
        assert old.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='5'


def test_cropped_pdf_rejects_legacy_ocr_coordinates_even_with_matching_hash(tmp_path):
    from pid_reader.api import stable_id
    src=cropped_rotated_pdf(90)
    e=read_pid(src,ReadParams())
    h=e['document']['sha256']
    box={'x0':.1,'y0':.15,'x1':.2,'y1':.19}
    word={'id':stable_id('ocr',h,1,box,'PT-101'),'text':'PT-101','page':1,'bbox':box,
          'raw_ocr_score':.8,'review_state':'PROPOSED','engine':'local_tesseract'}
    ocr={'adapter':'standalone_ocr_preview_v2','source_sha256':h,
         'algorithm':'tesseract-word-ocr-v2','engine_version':'synthetic',
         'selected_pages':[1],'page_count':1,'pages':[{'page':1,'words':[word]}]}
    ocr['result_sha256']=sha256_hex(canonical_json(ocr).encode('utf-8'))
    with ProjectStore(tmp_path/'p.sqlite') as db:
        eid=db.add_extraction(e,source_pdf_bytes=src)
        with pytest.raises(ValueError,match='cropped page'):
            db.add_ocr_analysis(eid,ocr)


def test_cropped_v3_ocr_stores_transformed_words_and_cannot_forge_frame(tmp_path,monkeypatch):
    pytess=pytest.importorskip('pytesseract')
    src=cropped_rotated_pdf(270)
    monkeypatch.setattr(pytess,'image_to_data',lambda image,**kwargs:
        {'text':['PT-101'],'conf':['79'],'left':[50],'top':[50],'width':[55],'height':[18]})
    ocr=ocr_pdf_preview(src,dpi=144)
    e=read_pid(src,ReadParams())
    with ProjectStore(tmp_path/'p.sqlite') as db:
        eid=db.add_extraction(e,source_pdf_bytes=src)
        oid=db.add_ocr_analysis(eid,ocr)
        assert db.add_ocr_analysis(eid,ocr)==oid
        assert len(db.list_ocr_words(oid))==1
        altered=deepcopy(ocr)
        altered['pages'][0]['render_transform']['crop_origin'][0]+=10
        altered['result_sha256']=sha256_hex(canonical_json({k:v for k,v in altered.items() if k!='result_sha256'}).encode())
        with pytest.raises(ValueError):db.add_ocr_analysis(eid,altered)


def test_contract_schemas_for_new_independent_modules():
    from pathlib import Path
    from jsonschema import validate
    src,e,g,s,l,out=evidence()
    folder=Path(__file__).resolve().parents[1]/'contracts'
    sig=json.loads((folder/'standalone_signal_links_v1.schema.json').read_text())
    validate(out,sig)
    from test_text_links import layers
    tags=evaluate_text_links(layers()[-1],example_profile())
    spec=json.loads((folder/'standalone_profiled_tags_v1.schema.json').read_text())
    validate(tags,spec)
