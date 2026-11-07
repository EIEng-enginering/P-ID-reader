"""Rev P synthetic evidence-first registers, offline reports and GUI source contract.

All tests here verify software behaviour, NOT independent P&ID recognition.
"""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from reportlab.pdfgen.canvas import Canvas

from pid_reader.api import ReadParams, read_pid
from pid_reader.cli import main
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.workspace import register_page, drawing_graph_view, crosssheet_graph_view
from pid_reader.engineering.reports import make_report, verify_report, report_csv, report_html, save_report


def pdf(name='P-101', note='READING ONLY') -> bytes:
    b=BytesIO()
    c=Canvas(b,pagesize=(500,300),pageCompression=0,invariant=1)
    c.setFont('Helvetica',12)
    c.drawString(40,240,name)
    c.drawString(40,210,note)
    c.line(50,100,200,100)
    c.save()
    return b.getvalue()


def imported(store, raw, name, rev):
    result=read_pid(raw,ReadParams(),filename=name,document_revision_id=rev)
    eid=store.add_extraction(result,source_pdf_bytes=raw)
    store.register_drawing(eid,drawing_no='PID-001',revision_label=rev,
                           facility='Synthetic',area='100',actor='Tester',reason='Test drawing')
    return eid


def test_paged_register_keeps_source_and_review_state(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        a=imported(db,pdf('P-101'),'A.pdf','A')
        b=imported(db,pdf('P-102'),'B.pdf','B')
        allrows=register_page(db,limit=1)
        assert allrows['total']>1 and len(allrows['rows'])==1
        retrieved=[]
        for offset in range(allrows['total']):
            p=register_page(db,limit=1,offset=offset)
            retrieved.extend(p['rows'])
        assert len({x['observation_id'] for x in retrieved})==len(retrieved)
        one=register_page(db,extraction_id=a,text='P-101',limit=5)
        assert one['total']==1
        o=one['rows'][0]
        assert o['document_sha256']==hashlib.sha256(pdf('P-101')).hexdigest()
        assert o['drawing_no']=='PID-001' and o['revision_label']=='A'
        assert o['state']=='PROPOSED'
        db.review(o['observation_id'],actor='QA',decision='ACCEPTED_AS_READING',reason='Source reading')
        assert register_page(db,state='PROPOSED')['total']==allrows['total']-1
        accepted=register_page(db,state='ACCEPTED_AS_READING')
        assert accepted['total']==1 and accepted['rows'][0]['reviewed_by']=='QA'
        assert register_page(db,extraction_id=b,text='P-102')['total']==1
        assert db.verify_audit_chain()


def test_register_filter_literal_escape_and_boundaries(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        imported(db,pdf('P-101'),'A.pdf','A')
        assert register_page(db,text='%')['total']==0
        assert register_page(db,text='_')['total']==0
        assert register_page(db,object_class='PUMP',drawing_no='PID-001')['total']==1
        for opt in ({'limit':0}, {'limit':251}, {'offset':-1}, {'offset':1.3},
                    {'state':'VERIFIED_AS_BUILT'}, {'text':'x'*151}):
            with pytest.raises(ValueError):register_page(db,**opt)


def test_reports_are_deterministic_source_linked_and_do_not_mutate_project(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        a=imported(db,pdf('P-101'),'A.pdf','A')
        before=db.db.execute('SELECT count(*) FROM audit_event').fetchone()[0]
        report=make_report(db,extraction_ids=[a]); second=make_report(db,extraction_ids=[a])
        assert second==report and verify_report(report)
        assert report['selection']['source_count']==1
        assert report['sources'][0]['source_sha256']==hashlib.sha256(pdf('P-101')).hexdigest()
        assert report['summary']['reading_count']>=2
        assert report['limits']['engineering_validation']=='NOT_PERFORMED'
        assert db.db.execute('SELECT count(*) FROM audit_event').fetchone()[0]==before
        changed=deepcopy(report);changed['readings'][0]['tag_text']='Tampered'
        assert not verify_report(changed)
        with pytest.raises(ValueError,match='limit'):
            make_report(db,extraction_ids=[a],max_records=1)
        assert db.verify_audit_chain()


def test_html_escapes_untrusted_source_text_and_csv_prevents_formulas(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        imported(db,pdf('P-101'),'A.pdf','A')
        r=make_report(db)
        fake=deepcopy(r)
        fake['readings'][0]['tag_text']='<script>alert(1)</script>'
        fake['readings'][0]['source_name']='=HYPERLINK("https://evil.example")'
        fake['readings'][0]['drawing_no']='@SUM(1,2)'
        fake.pop('report_sha256')
        fake['report_sha256']=hashlib.sha256(json.dumps(fake,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        assert verify_report(fake)
        html=report_html(fake)
        assert '&lt;script&gt;' in html and '<script>' not in html
        csv_text=report_csv(fake)
        rows=list(csv.reader(csv_text.splitlines()))
        assert rows[0][0].startswith('DRAWING READINGS ONLY')
        assert any(cell.startswith("'=HYPERLINK") for row in rows for cell in row)
        assert any(cell.startswith("'@SUM") for row in rows for cell in row)


def test_save_report_is_atomic_create_only_and_never_truncates(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        imported(db,pdf(),'A.pdf','A')
        r=make_report(db)
        dest=tmp_path/'report.html'
        save_report(r,dest,fmt='html')
        original=dest.read_bytes()
        with pytest.raises(FileExistsError):save_report(r,dest,fmt='html')
        assert dest.read_bytes()==original
        assert not list(tmp_path.glob('.pid-report-*'))
        save_report(r,dest,fmt='json',overwrite=True)
        assert json.loads(dest.read_text())['report_sha256']==r['report_sha256']
        with pytest.raises(ValueError):save_report(r,tmp_path/'invalid',fmt='exe')
        with pytest.raises(FileNotFoundError):save_report(r,tmp_path/'missing'/'report.json',fmt='json')


def test_source_graph_lists_proposals_without_upgrading_acceptance(tmp_path):
    source=Path(__file__).resolve().parents[1]/'fixtures'/'synthetic_pid_vector.pdf'
    with ProjectStore(tmp_path/'p.sqlite') as db:
        raw=source.read_bytes();eid=imported(db,raw,'vector.pdf','A')
        graph=drawing_graph_view(db,extraction_id=eid)
        assert graph['edge_status']=='SOURCE_PROPOSAL_UNVERIFIED'
        assert graph['total']==len(db.export_extraction(eid)['connections'])
        accepted=drawing_graph_view(db,extraction_id=eid,accepted_endpoints_only=True)
        assert accepted['total']==0
        for row in db.list_objects(extraction_id=eid,limit=1000):
            db.review(row['observation_id'],actor='Test Reviewer',decision='ACCEPTED_AS_READING',reason='Reading only')
        accepted=drawing_graph_view(db,extraction_id=eid,accepted_endpoints_only=True)
        assert accepted['total']==graph['total']
        assert accepted['edge_status']=='SOURCE_PROPOSAL_UNVERIFIED'
        assert db.verify_audit_chain()


def test_crosssheet_view_is_unresolved_until_named_review(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        a=imported(db,pdf('TO PID-002'),'A.pdf','A')
        b=imported(db,pdf('FROM PID-001'),'B.pdf','B')
        box={'x0':.1,'y0':.1,'x1':.2,'y1':.2}
        db.annotate_offpage(a,page=1,bbox=box,label='L-100',actor='Engineer',reason='Visible connector')
        db.annotate_offpage(b,page=1,bbox=box,label='L-100',actor='Engineer',reason='Visible connector')
        aid,_=db.analyze_crosssheet([a,b])
        view=crosssheet_graph_view(db,analysis_id=aid)
        assert view['rows']
        assert view['rows'][0]['state']=='UNRESOLVED'
        cid=view['rows'][0]['candidate_id']
        db.review_crosssheet(cid,actor='Engineer',decision='LINKED_AS_DRAWN',reason='Compared both drawings')
        reviewed=crosssheet_graph_view(db,analysis_id=aid)
        assert reviewed['rows'][0]['state']=='LINKED_AS_DRAWN'
        assert 'plant' in reviewed['notice']


def test_report_handles_empty_project_and_unknown_source(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        empty=make_report(db)
        assert empty['summary']['reading_count']==0
        assert empty['selection']['source_count']==0
        assert verify_report(empty)
        with pytest.raises(KeyError):make_report(db,extraction_ids=['ext-does-not-exist'])
        with pytest.raises(ValueError):make_report(db,extraction_ids=['same','same'])


def test_refuses_tampered_audit_log_before_reporting(tmp_path):
    with ProjectStore(tmp_path/'p.sqlite') as db:
        imported(db,pdf(),'A.pdf','A')
        db.db.execute('DROP TRIGGER block_update_audit_event')
        db.db.execute("UPDATE audit_event SET event_hash='forged' WHERE event_id=1")
        db.db.commit()
        with pytest.raises(ValueError,match='audit'):
            make_report(db)


def test_cli_paged_register_graph_and_export(tmp_path,capsys):
    file=tmp_path/'A.pdf';file.write_bytes(pdf())
    project=tmp_path/'p.sqlite'
    assert main(['import-pdf',str(project),str(file)])==0
    assert main(['register-page',str(project),'--limit','2'])==0
    output=capsys.readouterr().out
    assert 'pid-reader-standalone-register-v1' in output
    target=tmp_path/'report.csv'
    assert main(['report-export',str(project),str(target),'--format','csv'])==0
    assert target.read_text().startswith('DRAWING READINGS ONLY')
    assert main(['graph-view',str(project)])==0
    assert 'SOURCE_PROPOSAL_UNVERIFIED' in capsys.readouterr().out
    assert main(['report-export',str(project),str(target),'--format','csv'])==2
    assert main(['report-export',str(project),str(target),'--format','csv','--overwrite'])==0


def test_new_core_modules_import_without_qt_dependency():
    code='from pid_reader.engineering import workspace,reports;print(workspace.VALID_STATES)'
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,check=True)
    assert 'PROPOSED' in result.stdout
