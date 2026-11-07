"""Rev T: conservative scanned bowtie/central-ring proposals, not plant validation."""
from __future__ import annotations

import copy
from io import BytesIO
import json
from pathlib import Path

import pytest
import jsonschema
import pdfplumber
from pypdf import PdfReader, PdfWriter

pytest.importorskip('cv2')
pytest.importorskip('numpy')
pytest.importorskip('pypdfium2')

from pid_reader.api import ReadParams, read_pid, sha256_hex, canonical_json
from pid_reader.engineering.raster_geometry import (
    SCHEMA, ALGORITHM, SCHEMA_V1, ALGORITHM_V1, analyze_raster_geometry,
    validate_raster_result)
from pid_reader.engineering.project import ProjectStore
from pid_reader.engineering.findings import list_findings, review_finding
from pid_reader.engineering.raster_outlines import find_outline_valves

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/'fixtures/synthetic_raster_outline_valves.pdf'
FILLED=ROOT/'fixtures/synthetic_raster_filled_valves.pdf'

@pytest.fixture(scope='module')
def source():return FILE.read_bytes()

@pytest.fixture(scope='module')
def observations(source):return analyze_raster_geometry(source)


def test_scan_only_three_outlined_shapes_and_no_filled(source,observations):
    with pdfplumber.open(BytesIO(source)) as p:
        assert p.pages[0].lines==[] and p.pages[0].curves==[]
    assert observations['schema']==SCHEMA and observations['algorithm']==ALGORITHM
    assert observations['filled_valve_candidates']==[]
    items=observations['outline_valve_candidates']
    assert len(items)==3
    assert sorted(x['orientation'] for x in items)==['HORIZONTAL_AXIS','HORIZONTAL_AXIS','VERTICAL_AXIS']
    assert sorted(x['style'] for x in items)==['CENTRAL_RING_OBSERVED','PLAIN_OUTLINE','PLAIN_OUTLINE']
    assert all(x['status']=='PROPOSED_UNVERIFIED' and 'not a confirmed' in x['limitations'] for x in items)
    assert validate_raster_result(observations,source)==[]


def test_negative_x_crossings_rectangle_and_hairlines(observations):
    # x ~980,200: simple crossing; ~950,455: crossed rectangle;
    # ~235,690: two isolated long diagonals. None has glyph identity.
    mids=[x['centre'] for x in observations['outline_valve_candidates']]
    assert not any(.79<x<.86 and .18<y<.33 for x,y in mids)
    assert not any(.75<x<.87 and .50<y<.64 for x,y in mids)
    assert not any(.13<x<.27 and .76<y<.95 for x,y in mids)


def test_long_diagonal_strokes_are_unverified_only(observations):
    # The diagonal X at lower left was invisible in Rev S's axis-only Hough.
    assert any(abs((v['endpoints'][1][0]-v['endpoints'][0][0]))>.10
               and abs((v['endpoints'][1][1]-v['endpoints'][0][1]))>.10
               for v in observations['stroke_candidates'])
    assert all(r['role']=='RASTER_LINEWORK_UNKNOWN' for r in observations['stroke_candidates'])
    assert 'connections' not in observations


def test_schema_v2_and_determinism(source,observations):
    schema=json.loads((ROOT/'contracts/standalone_raster_geometry_v2.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(observations,schema)
    assert observations==analyze_raster_geometry(source)
    assert observations['source_sha256']==sha256_hex(source)


def test_original_v1_file_still_valid_without_misreading_as_v2():
    original=json.loads((ROOT/'fixtures/synthetic_raster_observations_v1.json').read_text())
    assert original['schema']==SCHEMA_V1 and original['algorithm']==ALGORITHM_V1
    schema=json.loads((ROOT/'contracts/standalone_raster_geometry_v1.schema.json').read_text())
    jsonschema.validate(original,schema)
    assert validate_raster_result(original)==[]


def test_rehashed_outlined_bbox_and_style_forgery_rejected(source,observations):
    altered=copy.deepcopy(observations)
    altered['outline_valve_candidates'][0]['bbox']['x0']+=.012
    altered['result_sha256']=sha256_hex(canonical_json({k:v for k,v in altered.items() if k!='result_sha256'}).encode())
    assert any('outlined glyph identity' in x for x in validate_raster_result(altered,source))
    altered=copy.deepcopy(observations)
    altered['outline_valve_candidates'][0]['style']='MADE_UP'
    altered['result_sha256']=sha256_hex(canonical_json({k:v for k,v in altered.items() if k!='result_sha256'}).encode())
    assert any('outlined glyph identity' in x for x in validate_raster_result(altered,source))


def test_review_store_proposal_only_and_audit(tmp_path,source,observations):
    with ProjectStore(tmp_path/'rev-t.sqlite') as project:
        extraction=read_pid(source,ReadParams(),filename='outline.pdf')
        eid=project.add_extraction(extraction,source_pdf_bytes=source)
        aid=project.add_raster_analysis(eid,observations)
        assert aid==project.add_raster_analysis(eid,observations)
        items=project.list_raster_valves(aid)
        assert len(items)==3
        rows=list_findings(project,eid,'raster')
        assert len(rows)==3 and all(row['state']=='PROPOSED' for row in rows)
        assert any('outlined' in row['label'] for row in rows)
        decision=review_finding(project,'raster',items[0]['candidate_id'],actor='Engineer A',
                                decision='UNRESOLVED',reason='Check the site legend')
        assert decision and project.verify_audit_chain()
        assert list_findings(project,eid,'raster')[0]['state']=='UNRESOLVED'
        again=project.export_extraction(eid)
        assert again==extraction and 'outline_valve_candidates' not in again


def test_crop_rotation_boxes_canonical(source):
    src=PdfReader(BytesIO(source))
    page=src.pages[0]
    page.cropbox.lower_left=(30,20)
    page.cropbox.upper_right=(570,390)
    page.rotate(90)
    writer=PdfWriter();writer.add_page(page);out=BytesIO();writer.write(out)
    transformed=out.getvalue()
    result=analyze_raster_geometry(transformed)
    assert validate_raster_result(result,transformed)==[]
    assert all(c['bbox']['x0']<c['bbox']['x1'] and c['bbox']['y0']<c['bbox']['y1']
               for c in result['outline_valve_candidates'])


def test_filled_glyphs_not_double_counted_as_outlines():
    result=analyze_raster_geometry(FILLED.read_bytes())
    assert len(result['filled_valve_candidates'])==2
    assert result['outline_valve_candidates']==[]


def test_outline_detector_explicitly_reports_base_budget_skip(monkeypatch):
    from pid_reader.engineering import raster_outlines as alg
    import numpy as np,cv2
    monkeypatch.setattr(alg,'_find_bases',lambda image,cv,np:None)
    items,warnings=find_outline_valves(np.zeros((100,120),dtype=np.uint8),cv2,np)
    assert items==[] and len(warnings)==2
    assert all('SKIPPED_BASE_BUDGET' in x for x in warnings)


def test_full_pipeline_automatically_adds_outlines_without_host_writes(tmp_path,source):
    from pid_reader.engineering.pipeline import analyze_drawing
    with ProjectStore(tmp_path/'pipeline.sqlite') as db:
        extraction=read_pid(source,ReadParams(),filename='source.pdf')
        eid=db.add_extraction(extraction,source_pdf_bytes=source)
        report=analyze_drawing(db,eid,ocr_engine=None)
        assert report['stages']['raster']['status']=='DONE'
        assert report['counts']['raster_outlined_valves']==3
        assert report['counts']['raster_filled_valves']==0
        assert len(list_findings(db,eid,'raster'))==3
        assert db.export_extraction(eid)==extraction
        assert db.verify_audit_chain()


def test_rotated_270_boxes_are_ordered(source):
    reader=PdfReader(BytesIO(source));page=reader.pages[0]
    page.rotate(270)
    writer=PdfWriter();writer.add_page(page);out=BytesIO();writer.write(out)
    updated=out.getvalue()
    result=analyze_raster_geometry(updated)
    assert validate_raster_result(result,updated)==[]
    assert len(result['outline_valve_candidates'])>=1
    assert all(row['bbox']['x0'] < row['bbox']['x1'] and row['bbox']['y0'] < row['bbox']['y1']
               for row in result['outline_valve_candidates'])
