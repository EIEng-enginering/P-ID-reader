"""Rev S offline raster evidence regression and safety tests (synthetic only)."""
from __future__ import annotations

import copy
from io import BytesIO
import json
from pathlib import Path
import sqlite3

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter
pytest.importorskip("cv2")
pytest.importorskip("numpy")
pytest.importorskip("pypdfium2")

from pid_reader.api import ReadParams, LimitExceeded, RefusedInput, canonical_json, read_pid, sha256_hex
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.raster_geometry import (
    SCHEMA, analyze_raster_geometry, raster_available, validate_raster_result)
from pid_reader.engineering.pipeline import analyze_drawing
from pid_reader.cli import main

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'synthetic_raster_filled_valves.pdf'


@pytest.fixture(scope='module')
def pdf():
    return FIXTURE.read_bytes()


@pytest.fixture(scope='module')
def raster(pdf):
    return analyze_raster_geometry(pdf)


def _extract(pdf):
    return read_pid(pdf,ReadParams(),filename='raster.pdf')


def test_raster_backend_available_here():
    assert raster_available()  # development fixture; skipped dependencies are not production proof


def test_scan_has_no_native_vector_strokes_and_two_filled_candidates(pdf,raster):
    with pdfplumber.open(BytesIO(pdf)) as drawing:
        assert len(drawing.pages[0].lines)==0
    assert raster['schema']==SCHEMA
    assert len(raster['stroke_candidates']) >= 1
    assert len(raster['filled_valve_candidates'])==2
    assert {c['orientation'] for c in raster['filled_valve_candidates']}=={'HORIZONTAL_AXIS','VERTICAL_AXIS'}
    assert all(c['status']=='PROPOSED_UNVERIFIED' for c in raster['filled_valve_candidates'])
    assert all('not a confirmed' in c['limitations'] for c in raster['filled_valve_candidates'])
    assert all(x['role']=='RASTER_LINEWORK_UNKNOWN' for x in raster['stroke_candidates'])
    assert validate_raster_result(raster,pdf)==[]


def test_no_isolated_arrowhead_or_x_crossing_as_valve(raster):
    centres=[v['centre'] for v in raster['filled_valve_candidates']]
    assert all(not (.40<c[0]<.48 and .72<c[1]<.9) for c in centres)
    assert all(not (.74<c[0]<.87 and .60<c[1]<.85) for c in centres)


def test_deterministic_hashes_and_r1_unchanged(pdf,raster):
    assert raster==analyze_raster_geometry(pdf)
    e=_extract(pdf)
    assert e['schema_version']==1
    assert 'stroke_candidates' not in e and 'filled_valve_candidates' not in e
    assert e['provenance']['result_sha256']
    assert raster['source_sha256']==e['document']['sha256']


def test_wrong_source_rejected_even_if_result_rehashed(pdf,raster):
    modified=copy.deepcopy(raster)
    modified['source_sha256']='0'*64
    modified['result_sha256']=sha256_hex(canonical_json({k:v for k,v in modified.items() if k!='result_sha256'}).encode())
    assert any('source hash' in x for x in validate_raster_result(modified,pdf))


def test_rehashed_changed_glyph_identity_rejected(pdf,raster):
    modified=copy.deepcopy(raster)
    modified['filled_valve_candidates'][0]['bbox']['x0']+=.01
    modified['result_sha256']=sha256_hex(canonical_json({k:v for k,v in modified.items() if k!='result_sha256'}).encode())
    assert any('glyph identity' in x for x in validate_raster_result(modified,pdf))


def test_changed_result_hash_rejected(pdf,raster):
    changed=copy.deepcopy(raster)
    changed['warnings'].append({'code':'MADE_UP','page':1})
    assert any('content hash' in x for x in validate_raster_result(changed,pdf))


def test_invalid_selection_and_dpi(pdf):
    with pytest.raises(RefusedInput):analyze_raster_geometry(pdf,pages=(1,1))
    with pytest.raises(RefusedInput):analyze_raster_geometry(pdf,pages=(2,))
    with pytest.raises(RefusedInput):analyze_raster_geometry(pdf,dpi=60)
    with pytest.raises(RefusedInput):analyze_raster_geometry(b'not a PDF')


def test_explicit_pixel_budget_refuses_instead_of_partial(pdf):
    with pytest.raises(LimitExceeded):
        analyze_raster_geometry(pdf,max_pixels=10)


def test_source_mapped_to_media_on_crop_and_rotation(pdf):
    source=PdfReader(BytesIO(pdf))
    writer=PdfWriter()
    page=source.pages[0]
    page.cropbox.lower_left=(20,20)
    page.cropbox.upper_right=(480,350)
    page.rotate(90)
    writer.add_page(page)
    output=BytesIO();writer.write(output)
    changed=output.getvalue()
    result=analyze_raster_geometry(changed)
    assert validate_raster_result(result,changed)==[]
    assert result['page_frames'][0]['transform']['rotation']==90
    assert result['page_frames'][0]['transform']['crop_origin'] != [0,0]
    assert all(0<=x<=1 for s in result['stroke_candidates'] for p in s['endpoints'] for x in p)


def test_persist_idempotent_review_audit_and_no_host_writes(tmp_path,pdf,raster):
    path=tmp_path/'raster.sqlite'
    source_extract=_extract(pdf)
    with ProjectStore(path) as db:
        assert db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        eid=db.add_extraction(source_extract,source_pdf_bytes=pdf)
        aid=db.add_raster_analysis(eid,raster)
        assert aid==db.add_raster_analysis(eid,raster)
        assert db.get_raster_analysis(aid)==raster
        candidates=db.list_raster_valves(aid)
        assert len(candidates)==2
        candidate=candidates[0]['candidate_id']
        with pytest.raises(ValueError):db.review_raster_valve(candidate,actor='',decision='ACCEPTED_AS_READING',reason='looks plausible')
        with pytest.raises(KeyError):db.review_raster_valve('unknown',actor='Engineer',decision='REJECTED',reason='not in drawing')
        decision=db.review_raster_valve(candidate,actor='Engineer',decision='UNRESOLVED',reason='Legend verification pending')
        assert db.latest_raster_review(candidate)['decision']=='UNRESOLVED'
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:db.db.execute('DELETE FROM raster_valve_decision WHERE decision_id=?',(decision,))
        assert db.export_extraction(eid)==source_extract
    with ProjectStore(path) as recovered:
        assert recovered.get_raster_analysis(aid)==raster
        assert recovered.verify_audit_chain()


def test_raster_import_requires_embedded_source_and_correct_document(tmp_path,pdf,raster):
    with ProjectStore(tmp_path/'missing.sqlite') as db:
        eid=db.add_extraction(_extract(pdf))
        with pytest.raises(ValueError):db.add_raster_analysis(eid,raster)
    with ProjectStore(tmp_path/'mismatch.sqlite') as db:
        from reportlab.pdfgen.canvas import Canvas
        bio=BytesIO();c=Canvas(bio);c.drawString(100,100,'P-200');c.save()
        other=bio.getvalue()
        eid=db.add_extraction(_extract(other),source_pdf_bytes=other)
        with pytest.raises(ValueError):db.add_raster_analysis(eid,raster)


def test_v9_upgrade_preserves_existing_rows_and_creates_backup(tmp_path,pdf):
    path=tmp_path/'legacy.sqlite'
    source_extract=_extract(pdf)
    with ProjectStore(path) as db:
        eid=db.add_extraction(source_extract,source_pdf_bytes=pdf)
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE raster_valve_decision')
        db.execute('DROP TABLE raster_valve_candidate')
        db.execute('DROP TABLE raster_analysis')
        db.execute("UPDATE project_meta SET value='9' WHERE key='standalone_schema'")
        db.commit()
    with ProjectStore(path) as upgraded:
        assert upgraded.migration_backup is not None
        assert upgraded.export_extraction(eid)==source_extract
        assert upgraded.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='13'
        assert upgraded.verify_audit_chain()
    backup=next(tmp_path.glob('legacy.sqlite.pre-v13-*.sqlite'))
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]=='9'


def test_cli_preview_import_query_review(tmp_path,pdf,capsys):
    drawing=tmp_path/'source.pdf';drawing.write_bytes(pdf)
    preview=tmp_path/'preview.json'
    assert main(['raster-preview',str(drawing),'--output-json',str(preview)])==0
    assert json.loads(preview.read_text())['schema']==SCHEMA
    dbpath=str(tmp_path/'cli.sqlite')
    assert main(['import-pdf',dbpath,str(drawing),'--ocr','off'])==0
    with ProjectStore(dbpath) as db:
        extraction=db.db.execute('SELECT extraction_id FROM extraction').fetchone()[0]
    assert main(['analyze-raster',dbpath,extraction])==0
    imported=json.loads(capsys.readouterr().out.splitlines()[-1])
    assert imported['filled_valves']==2
    aid=imported['analysis_id']
    assert main(['raster-valves',dbpath,aid])==0
    candidates=json.loads(capsys.readouterr().out)
    assert len(candidates)==2
    assert main(['review-raster-valve',dbpath,candidates[0]['candidate_id'],
                 '--actor','Engineer','--decision','UNRESOLVED',
                 '--reason','Pending source confirmation'])==0


def test_pipeline_runs_raster_on_scan_only_pages(tmp_path,pdf):
    with ProjectStore(tmp_path/'pipeline.sqlite') as db:
        eid=db.add_extraction(_extract(pdf),source_pdf_bytes=pdf)
        outcome=analyze_drawing(db,eid,ocr_engine=None,use_example_catalogue=False)
        assert outcome['stages']['raster']['status']=='DONE'
        assert outcome['counts']['raster_filled_valves']==2
        assert db.get_raster_analysis(outcome['analyses']['raster'])['source_sha256']==sha256_hex(pdf)


def test_optional_dependency_does_not_touch_r1_worker(pdf,monkeypatch):
    from pid_reader.engineering import raster_geometry
    def missing():raise RuntimeError('No offline raster backend')
    monkeypatch.setattr(raster_geometry,'_dependencies',missing)
    assert raster_geometry.raster_available() is False
    assert read_pid(pdf,ReadParams())['schema_version']==1


def test_oversized_render_downscales_with_explicit_warning(pdf):
    result=analyze_raster_geometry(pdf,dpi=240,max_pixels=500_000)
    assert 'DOWNSCALED_RENDER' in [w['code'] for w in result['warnings']]
    assert result['page_frames'][0]['render_dpi']<240
    assert validate_raster_result(result,pdf)==[]


def test_blank_scanned_page_does_not_invent_lines():
    from reportlab.pdfgen import canvas
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    page=Image.new('RGB',(300,200),'white')
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(300,200))
    c.drawImage(ImageReader(page),0,0,width=300,height=200);c.showPage();c.save()
    pdf=stream.getvalue()
    result=analyze_raster_geometry(pdf)
    assert len(result['stroke_candidates'])==0
    assert len(result['filled_valve_candidates'])==0
    assert result['warnings'][0]['code']=='NO_RASTER_INK'


def test_dark_page_is_refused_instead_of_false_positives():
    from reportlab.pdfgen import canvas
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    page=Image.new('RGB',(300,200),'black')
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(300,200))
    c.drawImage(ImageReader(page),0,0,width=300,height=200);c.showPage();c.save()
    with pytest.raises(RefusedInput,match='Dark-background'):
        analyze_raster_geometry(stream.getvalue())
