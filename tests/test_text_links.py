"""Rev K integration and security regressions; only synthetic/authorised input."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import shutil

import pytest
from reportlab.pdfgen import canvas
from io import BytesIO

from pid_reader.api import ReadParams, read_pid, canonical_json, sha256_hex, stable_id
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.topology import analyze_pdf_topology
from pid_reader.engineering.symbols import build_symbol_proposals
from pid_reader.engineering.text_links import build_text_links, validate_text_links, validate_ocr_source
from pid_reader.formats.ocr_source import verify_ocr_preview


def pdf_fixture():
    output=BytesIO()
    page=canvas.Canvas(output,pagesize=(600,650),pageCompression=0,invariant=1)
    page.setFont('Helvetica',8)
    page.circle(140,500,23)
    page.drawCentredString(140,497,'PT-101')
    page.rect(300,440,100,60)
    page.drawCentredString(350,468,'V-101')
    page.line(400,470,470,470)
    page.circle(180,350,30)
    page.drawCentredString(180,357,'PT-201')
    page.drawCentredString(180,340,'PT-202')
    page.save()
    return output.getvalue()


def make_ocr(extraction, words):
    # Synthetic word locations are independent annotations, not a fake claim
    # about real Tesseract accuracy. They use the genuine standalone schema.
    digest=extraction['document']['sha256']
    entries=[]
    for text,box in words:
        entries.append({'id':stable_id('ocr',digest,1,box,text),'text':text,'page':1,
                        'bbox':box,'raw_ocr_score':0.74,'review_state':'PROPOSED',
                        'engine':'local_tesseract'})
    res={'adapter':'standalone_ocr_preview_v2','source_sha256':digest,
         'algorithm':'tesseract-word-ocr-v2','engine_version':'synthetic-test-not-a-model',
         'dpi':180,'selected_pages':[1], 'page_count':1,
         'pages':[{'page':1,'words':entries,'limitations':'Synthetic test word annotations'}],
         'limitations':'Synthetic annotation, not measured OCR accuracy'}
    res['result_sha256']=sha256_hex(canonical_json(res).encode('utf-8'))
    return res


def layers():
    src=pdf_fixture();ex=read_pid(src,ReadParams())
    geom=analyze_pdf_topology(src)
    sym=build_symbol_proposals(ex,geom)
    # x=140/600, y=(650-500)/650. The OCR box is inside the circle.
    words=[('PT-101',{'x0':.215,'y0':.226,'x1':.253,'y1':.249}),
           ('V-',{'x0':.559,'y0':.260,'x1':.571,'y1':.288}),
           ('101',{'x0':.574,'y0':.260,'x1':.594,'y1':.288})]
    ocr=make_ocr(ex,words)
    links=build_text_links(ex,sym,ocr)
    return src,ex,geom,sym,ocr,links


def test_standalone_text_links_are_source_hash_bound_and_deterministic():
    src,e,g,s,o,links=layers()
    assert verify_ocr_preview(o)
    assert validate_ocr_source(o,e)==[]
    assert links==build_text_links(e,s,o)
    assert validate_text_links(links,e,s,o)==[]
    assert len(links['proposals'])==len(s['symbol_candidates'])
    assert all(p['review_state']=='PROPOSED_UNVERIFIED' for p in links['proposals'])
    assert 'text_links' not in read_pid(src,ReadParams())


def test_native_and_ocr_matching_tag_evidence_are_both_retained():
    _,e,g,s,o,links=layers()
    tagged=[p for p in links['proposals'] if any(x['text_candidate']=='PT-101' for x in p['options'])]
    assert len(tagged)==1
    evidence=next(x['sources'] for x in tagged[0]['options'] if x['text_candidate']=='PT-101')
    assert {a['method'] for a in evidence}=={'PDF_NATIVE','OCR_TESSERACT'}


def test_multiple_native_tags_remain_ambiguous_and_unaccepted():
    _,e,g,s,o,links=layers()
    ambiguous=[p for p in links['proposals'] if {x['text_candidate'] for x in p['options']}>={'PT-201','PT-202'}]
    assert len(ambiguous)==1
    assert ambiguous[0]['association_state']=='MULTIPLE_TEXT_OPTIONS'
    assert all('confidence' not in a for p in links['proposals'] for a in p['options'])


def test_rehashed_bad_word_identity_rejected():
    _,e,g,s,o,l=layers()
    o['pages'][0]['words'][0]['id']='ocr-forged'
    o['result_sha256']=sha256_hex(canonical_json({k:v for k,v in o.items() if k!='result_sha256'}).encode('utf-8'))
    assert any('identity' in x for x in validate_ocr_source(o,e))
    with pytest.raises(ValueError):build_text_links(e,s,o)


def test_rehashed_cross_source_ocr_is_refused():
    _,e,g,s,o,l=layers()
    o['source_sha256']='f'*64
    o['result_sha256']=sha256_hex(canonical_json({k:v for k,v in o.items() if k!='result_sha256'}).encode('utf-8'))
    assert any('different source' in x for x in validate_ocr_source(o,e))


def test_rehashed_forged_link_proposal_is_not_accepted():
    _,e,g,s,o,l=layers()
    l['proposals'][0]['options'].append({'text_candidate':'ESD-888', 'tag_style':'TAG_PATTERN','sources':[]})
    l['result_sha256']=sha256_hex(canonical_json({k:v for k,v in l.items() if k!='result_sha256'}).encode('utf-8'))
    assert validate_text_links(l,e,s,o)


def test_storage_is_idempotent_audited_and_read_only_evidence_is_linked(tmp_path):
    pdf,e,g,s,o,links=layers()
    with ProjectStore(tmp_path/'k.sqlite') as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        eid=db.add_extraction(e,source_pdf_bytes=pdf)
        gid=db.add_geometry_analysis(eid,g)
        sid=db.add_symbol_analysis(eid,gid,s)
        oid=db.add_ocr_analysis(eid,o)
        assert db.add_ocr_analysis(eid,o)==oid
        lid=db.add_text_link_analysis(eid,sid,oid,links)
        assert db.add_text_link_analysis(eid,sid,oid,links)==lid
        assert db.get_ocr_analysis(oid)==o
        assert db.get_text_link_analysis(lid)==links
        assert len(db.list_ocr_words(oid,text='PT'))==1
        candidates=db.list_text_link_proposals(lid)
        assert len(candidates)==len(s['symbol_candidates'])
        row=next(c for c in candidates if any(x['text_candidate']=='PT-101' for x in c['proposal']['options']))
        p=row['proposal_id']
        with pytest.raises(ValueError,match='exact existing'):
            db.review_text_link(p,actor='Engineer',decision='ACCEPTED_AS_READING',reason='Checked drawing',selected_text='INVENTED')
        rid=db.review_text_link(p,actor='Engineer',decision='ACCEPTED_AS_READING',reason='Checked drawing',selected_text='PT-101')
        assert rid.startswith('tdec-')
        view=db.symbol_evidence(lid,row['symbol_candidate_id'])
        assert view['source_sha256']==e['document']['sha256']
        assert view['text_review']['decision']=='ACCEPTED_AS_READING'
        assert view['text_review']['selected_text']=='PT-101'
        assert {x['method'] for x in view['text_options'][0]['sources']}=={'PDF_NATIVE','OCR_TESSERACT'}
        assert 'physical' in view['limitations'] or 'installed plant' in view['limitations']
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('DELETE FROM ocr_word WHERE analysis_id=?',(oid,))
        with pytest.raises(KeyError):db.symbol_evidence('text-links-bad',row['symbol_candidate_id'])
        path=db.backup(tmp_path/'copy.sqlite')
    with ProjectStore(path) as db:
        assert db.verify_audit_chain()
        assert db.latest_text_link_review(p)['actor']=='Engineer'
        assert db.get_ocr_analysis(oid)==o


def test_reject_and_supersede_decision_without_mutating_original(tmp_path):
    pdf,e,g,s,o,links=layers()
    with ProjectStore(tmp_path/'review.sqlite') as db:
        eid=db.add_extraction(e,source_pdf_bytes=pdf)
        gid=db.add_geometry_analysis(eid,g)
        sid=db.add_symbol_analysis(eid,gid,s)
        oid=db.add_ocr_analysis(eid,o)
        lid=db.add_text_link_analysis(eid,sid,oid,links)
        item=db.list_text_link_proposals(lid)[0]
        pid=item['proposal_id']
        db.review_text_link(pid,actor='A',decision='UNRESOLVED',reason='Needs check')
        db.review_text_link(pid,actor='B',decision='EDITED_AND_ACCEPTED',reason='Corrected from drawing',selected_text='PT-123')
        assert db.latest_text_link_review(pid)['selected_text']=='PT-123'
        assert db.list_text_link_proposals(lid)[0]['proposal']['review_state']=='PROPOSED_UNVERIFIED'
        assert db.db.execute('SELECT COUNT(*) FROM text_link_decision WHERE proposal_id=?',(pid,)).fetchone()[0]==2
        assert db.verify_audit_chain()


def test_migration_v4_retains_old_records_and_produces_preupgrade_backup(tmp_path):
    from pid_reader.engineering.migrations import MIGRATION_2,MIGRATION_3,MIGRATION_4
    from pid_reader.engineering.project import DDL
    path=tmp_path/'old.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript(DDL)
        db.execute("INSERT INTO project_meta VALUES('standalone_schema','1')")
        db.commit()
        db.executescript(MIGRATION_2)
        db.executescript(MIGRATION_3)
        db.executescript(MIGRATION_4)
    with ProjectStore(path) as project:
        assert project.migration_backup is not None
        assert project.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        assert project.db.execute("SELECT name FROM sqlite_master WHERE name='text_link_decision'").fetchone()
    with sqlite3.connect(next(tmp_path.glob('old.sqlite.pre-v12-*.sqlite'))) as backup:
        assert backup.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='4'


def test_cli_ocr_and_text_links_round_trip(tmp_path,capsys):
    from pid_reader.cli import main
    pdf,e,g,s,o,links=layers()
    path=tmp_path/'s.sqlite';source=tmp_path/'source.pdf';source.write_bytes(pdf)
    ocr_path=tmp_path/'ocr.json';ocr_path.write_text(canonical_json(o),encoding='utf-8')
    assert main(['import-pdf',str(path),str(source)])==0
    with ProjectStore(path) as db:eid=db.db.execute('SELECT extraction_id FROM extraction').fetchone()[0]
    assert main(['analyze-topology',str(path),eid])==0
    with ProjectStore(path) as db:gid=db.db.execute('SELECT analysis_id FROM geometry_analysis').fetchone()[0]
    assert main(['analyze-symbols',str(path),eid,gid])==0
    with ProjectStore(path) as db:sid=db.db.execute('SELECT analysis_id FROM symbol_analysis').fetchone()[0]
    assert main(['import-ocr',str(path),eid,'--ocr-json',str(ocr_path)])==0
    with ProjectStore(path) as db:oid=db.db.execute('SELECT analysis_id FROM ocr_analysis').fetchone()[0]
    assert main(['analyze-text-links',str(path),eid,sid,oid])==0
    with ProjectStore(path) as db:
        lid=db.db.execute('SELECT analysis_id FROM text_link_analysis').fetchone()[0]
        candidate=db.list_text_link_proposals(lid)[0]
    assert main(['text-link-candidates',str(path),lid])==0
    assert main(['symbol-evidence',str(path),lid,candidate['symbol_candidate_id']])==0


@pytest.mark.skipif(not shutil.which('tesseract'),reason='Local Tesseract is optional')
def test_actual_offline_ocr_result_can_be_saved(raster_pdf,tmp_path):
    from pid_reader.formats.ocr_source import ocr_pdf_preview
    source=raster_pdf
    extraction=read_pid(source,ReadParams())
    result=ocr_pdf_preview(source)
    with ProjectStore(tmp_path/'raster.sqlite') as db:
        eid=db.add_extraction(extraction,source_pdf_bytes=source)
        aid=db.add_ocr_analysis(eid,result)
        assert db.get_ocr_analysis(aid)==result
        assert db.verify_audit_chain()


def test_rev_k_standalone_schema_accepts_real_proposals():
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema=json.loads((Path(__file__).resolve().parents[1]/'contracts/standalone_text_links_v1.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    _,e,g,s,o,links=layers()
    assert list(Draft202012Validator(schema).iter_errors(links))==[]


def test_split_ocr_fragments_not_promoted_to_independent_tag_proposals():
    _,e,g,s,o,links=layers()
    v=next(p for p in links['proposals'] if any(z['text_candidate']=='V-101' for z in p['options']))
    assert [z['text_candidate'] for z in v['options']]==['V-101']
    assert {x['text'] for x in v['unparsed_ocr_evidence']}=={'V-','101'}
    merged=next(z for z in v['options'] if z['text_candidate']=='V-101')
    assert {'PDF_NATIVE','OCR_TESSERACT'}=={source['method'] for source in merged['sources']}


def test_synthetic_fixture_has_reproducible_source_bytes():
    assert hashlib.sha256(pdf_fixture()).hexdigest()==hashlib.sha256(pdf_fixture()).hexdigest()


def test_strict_ocr_bounds_fail_even_with_recomputed_hash():
    _,e,g,s,o,links=layers()
    o['pages'][0]['words'][0]['bbox']['x1']=1.25
    o['result_sha256']=sha256_hex(canonical_json({k:v for k,v in o.items() if k!='result_sha256'}).encode())
    errors=validate_ocr_source(o,e)
    assert any('Invalid OCR word' in x for x in errors)
