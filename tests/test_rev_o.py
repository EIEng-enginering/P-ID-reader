"""Rev O: batch imports and conservative source-revision comparisons.

Only synthetic controlled drawings. Not an engineering accuracy benchmark.
"""
from __future__ import annotations
import json
import sqlite3
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from pid_reader.api import ReadParams, read_pid, result_sha256
from pid_reader.cli import main
from pid_reader.engineering.batch import start_batch, resume_batch, collect_files
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.revisions import compare_extractions


def pdf(*, x=60, extra_tag=None, text='SYNTHETIC TEST DRAWING'):
    out=BytesIO();c=Canvas(out,pagesize=(500,300),pageCompression=0,invariant=1)
    c.setFont('Helvetica',12)
    c.drawString(20,250,text)
    c.drawString(x,150,'P-101')
    c.drawString(200,150,'PT-201')
    if extra_tag:c.drawString(345,100,extra_tag)
    c.save()
    return out.getvalue()


def add(db,raw,name='source.pdf',revision='A',drawing='PID-001'):
    r=read_pid(raw,ReadParams(),filename=name,document_revision_id=revision)
    eid=db.add_extraction(r,raw)
    db.register_drawing(eid,drawing_no=drawing,revision_label=revision,
                        facility='Synthetic Plant',area='100',actor='Test Engineer',reason='Controlled example')
    return eid,r


def test_revision_added_removed_and_source_snapshots(tmp_path):
    with ProjectStore(tmp_path/'project.sqlite') as db:
        e1,r1=add(db,pdf(),name='rA.pdf',revision='A')
        e2,r2=add(db,pdf(extra_tag='V-301'),name='rB.pdf',revision='B')
        cid,delta=db.compare_revisions(e1,e2)
        assert delta['source_state']=='DIFFERENT_SOURCE_BYTES'
        assert any(e['tag']=='V-301' and e['kind']=='ADDED_ON_DRAWING' for e in delta['events'])
        assert any(e['tag']=='P-101' and e['kind']=='SAME_READING' for e in delta['events'])
        assert delta['before']['registration']['revision_label']=='A'
        assert delta['after']['registration']['revision_label']=='B'
        assert delta['unmatched_before']  # Notes are not silently paired as equipment.
        db.register_drawing(e2,drawing_no='PID-001',revision_label='RECATALOGUED',
            facility='Synthetic Plant',area='100',actor='Test Engineer',reason='Fix metadata')
        assert db.get_revision_comparison(cid)==delta
        assert db.verify_audit_chain()
        cid2,delta2=db.compare_revisions(e1,e2)
        assert cid!=cid2
        assert delta2['after']['registration']['revision_label']=='RECATALOGUED'
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute('UPDATE revision_comparison SET result_sha256=? WHERE comparison_id=?',('0'*64,cid))


def test_position_change_distinguished_from_content_change():
    b=read_pid(pdf(x=60),ReadParams(),filename='A.pdf')
    a=read_pid(pdf(x=100),ReadParams(),filename='B.pdf')
    diff=compare_extractions(b,a)
    assert any(e['tag']=='P-101' and e['kind']=='POSITION_CHANGED' for e in diff['events'])
    assert not any(e['kind']=='INTERPRETATION_CHANGED' for e in diff['events'])


def test_same_source_new_extractor_not_a_drawing_change():
    raw=pdf()
    before=read_pid(raw,ReadParams(),filename='same.pdf')
    after=deepcopy(before)
    for obj in after['objects']:
        if obj['text']=='P-101':
            obj['attributes']={'synthetic_tag_note':'test'}
            break
    after['provenance']['result_sha256']=result_sha256(after)
    result=compare_extractions(before,after)
    assert result['source_state']=='SAME_SOURCE_DIFFERENT_EXTRACTION'
    assert any(x['kind']=='INTERPRETATION_CHANGED' for x in result['events'])
    assert compare_extractions(before,before)['source_state']=='IDENTICAL_EXTRACTION'


def test_duplicates_cannot_be_silently_merged():
    raw=pdf()
    b=read_pid(raw,ReadParams(),filename='A.pdf')
    a=deepcopy(b)
    item=next(x for x in a['objects'] if x['text']=='P-101')
    dupe=deepcopy(item);dupe['id']='obj-second-synthetic'
    a['objects'].append(dupe)
    a['provenance']['result_sha256']=result_sha256(a)
    delta=compare_extractions(b,a)
    row=next(x for x in delta['events'] if x['tag']=='P-101')
    assert row['kind']=='AMBIGUOUS_DUPLICATE_TAG'
    assert len(row['after_object_ids'])==2


def test_bad_revision_hash_and_duplicate_ids_rejected():
    e=read_pid(pdf(),ReadParams(),filename='base.pdf')
    tamper=deepcopy(e);tamper['objects'][0]['text']='forged'
    with pytest.raises(ValueError,match='hash'):
        compare_extractions(e,tamper)
    dup=deepcopy(e);dup['objects'].append(deepcopy(dup['objects'][0]))
    dup['provenance']['result_sha256']=result_sha256(dup)
    with pytest.raises(ValueError,match='duplicated'):
        compare_extractions(e,dup)


def test_batch_imports_and_resumes_without_repeating_committed_entries(tmp_path):
    a=tmp_path/'A.pdf';b=tmp_path/'B.pdf'
    a.write_bytes(pdf());b.write_bytes(pdf(extra_tag='V-301'))
    with ProjectStore(tmp_path/'project.sqlite') as db:
        bid=start_batch(db,[a,b],actor='Engineer A')
        partial=resume_batch(db,bid,stop_after=1)
        assert partial['state']=='INCOMPLETE'
        assert partial['counts']=={'total':2,'completed':1,'imported':1,'failed':0}
        complete=resume_batch(db,bid)
        assert complete['state']=='COMPLETE'
        assert complete['counts']['imported']==2
        assert resume_batch(db,bid)['outcomes']==complete['outcomes']
        assert db.db.execute('SELECT count(*) FROM extraction').fetchone()[0]==2
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute('DELETE FROM batch_import_outcome WHERE batch_id=?',(bid,))


def test_changed_file_between_preflight_and_resume_is_rejected(tmp_path):
    p=tmp_path/'a.pdf';p.write_bytes(pdf())
    with ProjectStore(tmp_path/'project.sqlite') as db:
        bid=start_batch(db,[p],actor='Engineer B')
        p.write_bytes(pdf(x=130))
        job=resume_batch(db,bid)
        assert job['counts']['failed']==1
        assert job['state']=='COMPLETE_WITH_FAILURES'
        assert 'changed' in job['outcomes'][0]['detail']
        assert db.db.execute('SELECT count(*) FROM extraction').fetchone()[0]==0
        assert db.verify_audit_chain()


def test_bad_pdf_in_batch_does_not_corrupt_other_sources(tmp_path):
    a=tmp_path/'bad.pdf'; b=tmp_path/'good.pdf'
    a.write_bytes(b'not a PDF');b.write_bytes(pdf())
    with ProjectStore(tmp_path/'project.sqlite') as db:
        bid=start_batch(db,[a,b],actor='Engineer')
        job=resume_batch(db,bid)
        assert job['counts']['imported']==1 and job['counts']['failed']==1
        assert job['state']=='COMPLETE_WITH_FAILURES'
        assert db.db.execute('SELECT count(*) FROM extraction').fetchone()[0]==1
        assert db.verify_audit_chain()


def test_oversize_preflight_recorded_without_partial_import(tmp_path):
    p=tmp_path/'large.pdf'; p.write_bytes(pdf()+b' ' * (16*1024*1024))
    with ProjectStore(tmp_path/'p.sqlite') as db:
        job=resume_batch(db,start_batch(db,[p],actor='Tester'))
        assert job['outcomes'][0]['status']=='FAILED'
        assert 'PID_LIMIT_BYTES' in job['outcomes'][0]['detail']


def test_batch_rejects_symlink_duplicate_and_non_pdf(tmp_path):
    p=tmp_path/'a.pdf'; p.write_bytes(pdf())
    alias=tmp_path/'link.pdf'
    try:
        alias.symlink_to(p)
    except OSError:
        pytest.skip('Symlink creation needs Windows Developer Mode/elevation; see test_batch_rejects_windows_reparse_point')
    with pytest.raises(ValueError,match='Symlink'):
        collect_files([alias])
    with pytest.raises(ValueError,match='more than once'):
        collect_files([p,p])
    with pytest.raises(ValueError,match='eligible'):
        collect_files([tmp_path/'missing.pdf'])
    with pytest.raises(ValueError,match='eligible'):
        collect_files([tmp_path/'a.txt'])


def test_batch_rejects_windows_reparse_point(tmp_path, monkeypatch):
    # Simulates a junction/symlink/placeholder: Windows reports FILE_ATTRIBUTE_REPARSE_POINT.
    import pathlib
    p=tmp_path/'a.pdf'; p.write_bytes(pdf())
    real=pathlib.Path.lstat
    def fake(self,*a,**k):
        st=real(self,*a,**k)
        if self.name=='a.pdf':
            class S:
                st_file_attributes=0x400
                def __getattr__(s,n): return getattr(st,n)
            return S()
        return st
    monkeypatch.setattr(pathlib.Path,'lstat',fake)
    with pytest.raises(ValueError):
        collect_files([p])


def test_project_search_keeps_provenance_reviews_and_literal_percent(tmp_path):
    with ProjectStore(tmp_path/'project.sqlite') as db:
        e,r=add(db,pdf(extra_tag='V-301'))
        rows=db.search_project(tag='P-101',object_class='PUMP',facility='Synthetic Plant')
        assert len(rows)==1
        row=rows[0]
        assert row['extraction_id']==e
        assert row['document_sha256']==r['document']['sha256']
        assert row['revision_label']=='A'
        assert row['latest_reading_review'] is None
        db.review(row['observation_id'],actor='Reviewer',decision='ACCEPTED_AS_READING',reason='Printed tag checked')
        assert db.search_project(tag='P-101')[0]['latest_reading_review']=='ACCEPTED_AS_READING'
        assert not db.search_project(tag='%')
        assert not db.search_project(tag='_')
        assert not db.search_project(drawing_no='different')
        with pytest.raises(ValueError):
            db.search_project(limit=10001)


def test_migration_from_v8_preserves_prior_extractions_and_backup(tmp_path):
    dbpath=tmp_path/'v8.sqlite'
    with ProjectStore(dbpath) as db:
        eid,_=add(db,pdf())
    import pid_reader.engineering.migrations as m
    old_sql=m.MIGRATION_9
    # Simulate the previous v8 schema using a temporary copy of the original file.
    with sqlite3.connect(dbpath) as raw:
        for t in ('batch_import_outcome','batch_import_run','revision_comparison'):
            raw.execute(f'DROP TABLE {t}')
        raw.execute("UPDATE project_meta SET value='8' WHERE key='standalone_schema'")
    with ProjectStore(dbpath) as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='9'
        assert db.export_extraction(eid)
        assert db.verify_audit_chain()
    backups=list(tmp_path.glob('v8.sqlite.pre-v9-*.sqlite'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as b:
        assert b.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='8'


def test_cli_rev_o_end_to_end(tmp_path,capsys):
    a=tmp_path/'A.pdf';b=tmp_path/'B.pdf';dbpath=tmp_path/'p.sqlite'
    a.write_bytes(pdf());b.write_bytes(pdf(extra_tag='V-301'))
    assert main(['batch-import',str(dbpath),str(a),str(b),'--actor','CLI test'])==0
    info=json.loads(capsys.readouterr().out)
    assert info['counts']['imported']==2
    assert main(['batch-status',str(dbpath),info['batch_id']])==0
    batch=json.loads(capsys.readouterr().out)
    ids=[x['extraction_id'] for x in batch['outcomes']]
    assert main(['compare-revisions',str(dbpath),*ids])==0
    compare=json.loads(capsys.readouterr().out)
    assert compare['events']>0
    assert main(['revision-comparison',str(dbpath),compare['comparison_id']])==0
    assert json.loads(capsys.readouterr().out)['schema'].endswith('diff-v1')
    assert main(['project-search',str(dbpath),'--tag','P-101','--object-class','PUMP'])==0
    assert len(json.loads(capsys.readouterr().out))==2


def test_same_bytes_different_filenames_keep_original_extraction_metadata(tmp_path):
    raw=pdf()
    a=tmp_path/'A.pdf';b=tmp_path/'B.pdf'
    a.write_bytes(raw);b.write_bytes(raw)
    with ProjectStore(tmp_path/'p.sqlite') as db:
        job=resume_batch(db,start_batch(db,[a,b],actor='Engineer'))
        assert job['counts']['imported']==2
        rows=db.search_project(tag='P-101',object_class='PUMP')
        assert {r['source_name'] for r in rows}=={'A.pdf','B.pdf'}
        assert len({r['document_sha256'] for r in rows})==1
        assert {r['extraction_id'] for r in rows}=={i['extraction_id'] for i in job['outcomes']}
