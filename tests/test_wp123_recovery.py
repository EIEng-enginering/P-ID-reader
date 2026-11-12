"""WP01-03: proposal-only engineering recovery acceptance and adversarial tests."""
from __future__ import annotations
import csv
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pytest

from pid_reader.engineering.wp123_recovery import (
    _parse_text,read_ocr_csv,read_detectors,infer_regions,recover_readings,
    clean_detector_proposals,associate_readings,recover_wp123,validate_wp123,save_wp123)
from pid_reader.engineering.wp123_bubbles import circle_candidates_from_image

PDF=b'%PDF-1.4\nsynthetic source used only for hashed evidence contract\n'

def word(i,text,x,y,w=.04,h=.015,score=.9):
    return {'id':f'ocr-{i}','text':text,'bbox':{'x0':x,'y0':y,'x1':x+w,'y1':y+h},
            'raw_score':score,'page':1,'review_state':'PROPOSED_UNVERIFIED'}

def detect(i,x,y,cls='instrumentation',score=.9,w=.07,h=.04):
    return {'id':f'det-{i}','bbox':{'x0':x,'y0':y,'x1':x+w,'y1':y+h},
            'coarse_class':cls,'raw_score':score,'page':1,
            'model_confidence_status':'LEADING','review_state':'PROPOSED_UNVERIFIED'}

@pytest.mark.parametrize('value,kind',[
    ('FE-2202','INSTRUMENT_TAG'),('V-2201','EQUIPMENT_TAG'),('PIC-220101','INSTRUMENT_TAG'),
    ('Q-2200','PACKAGE_REFERENCE'),('DR-22202-33.4-C3S-XXS','PIPE_LINE_NUMBER'),
    ('GHS-22203-168.3-C3S-80','PIPE_LINE_NUMBER')])
def test_valid_tag_and_line_grammar(value,kind):
    assert _parse_text(value)[0]==kind

@pytest.mark.parametrize('value',['BRV15','C3S','A1S','600#','SPECTRAENERGYMIDSTREAM',
   'ANFOLO','D','C','220101','GHS--22203-168.3-C3S-80','2007/02/08','5-VALVE','TO FLARE'])
def test_reject_document_text_as_tag(value):
    assert _parse_text(value) is None


def test_split_fe_reconstructed_only_with_geometric_alignment():
    words=[word('a','FE-',.2,.2,w=.019),word('b','2202',.220,.2),
           word('c','FE-',.2,.3,w=.019),word('d','2206',.42,.3)]
    entries,_=recover_readings(words,[])
    assert [r['text_candidate'] for r in entries]==['FE-2202']
    assert entries[0]['components']['joined_ocr'] is True


def test_contained_ocr_line_fragment_is_not_equipment():
    words=[word('line','PF-00019-14.3-A3S-40',.2,.2,w=.17),
           word('partial','P-00019',.201,.2,w=.053)]
    entries,rejected=recover_readings(words,[])
    assert [r['kind'] for r in entries]==['PIPE_LINE_NUMBER']
    assert any(r['reason']=='OCR_SUBSTRING_OF_PIPE_LINE' for r in rejected)


def test_unrelated_duplicate_tags_at_different_places_preserved():
    entries,_=recover_readings([word('a','FE-2206',.2,.1),word('b','FE-2206',.7,.7)],[])
    assert len(entries)==2


def test_overlapping_same_tag_ocr_dedup():
    entries,_=recover_readings([word('a','FE-2206',.2,.1),word('b','FE-2206',.201,.1)],[])
    assert len(entries)==1
    assert entries[0]['ocr_ids']==['ocr-a','ocr-b']


def test_bottom_document_region_isolated_from_objects():
    ww=[word('title','PIPING',.65,.88),word('type','INSTRUMENTATION',.72,.90),
        word('wrong','V-1111',.77,.92),word('right','V-2201',.55,.40)]
    regions=infer_regions(ww)
    assert len(regions)==1
    entries,rejected=recover_readings(ww,regions)
    assert [r['text_candidate'] for r in entries]==['V-2201']
    assert any(x['text']=='V-1111' for x in rejected)


def test_no_automatic_universal_border_mask():
    assert infer_regions([word('a','FE-2202',.97,.05)])==[]
    assert len(infer_regions([],profile='s418'))==3


def test_bad_score_and_bad_bbox_csv_refused(tmp_path):
    path=tmp_path/'words.csv'
    path.write_text('text,x0,y0,x1,y1,score\nPT-101,0.1,0.2,0.3,0.4,nan\n')
    with pytest.raises(ValueError):read_ocr_csv(path)
    path.write_text('text,x0,y0,x1,y1,score\nPT-101,0.1,0.2,1.1,0.4,0.9\n')
    with pytest.raises(ValueError):read_ocr_csv(path)


def test_bad_detector_source_and_duplicate_ids_refused(tmp_path):
    path=tmp_path/'detect.json'
    d={'id':'x','bbox':{'x0':0.1,'y0':0.2,'x1':0.3,'y1':0.4},'raw_score':.7}
    path.write_text(json.dumps({'detections':[d,d]}))
    with pytest.raises(ValueError,match='Duplicated'):read_detectors(path)
    path.write_text(json.dumps({'detections':[{**d,'raw_score':float('nan')}]}))
    with pytest.raises(ValueError):read_detectors(path)


def test_weak_general_border_title_and_oversize_all_withheld():
    ds=[detect('ok',.35,.35),detect('low',.1,.2,score=.15),
        detect('title',.8,.90),detect('large',.2,.25,w=.5,h=.3),
        detect('general',.5,.25,cls='general')]
    region=infer_regions([word('one','PIPING',.65,.87),word('two','INSTRUMENTATION',.7,.90)])
    rows=clean_detector_proposals(ds,region)
    kept=[x['id'] for x in rows if x['eligibility']=='REVIEWABLE_CLASS_CANDIDATE']
    assert kept==['det-ok']
    assert any(x['filter_reason']=='DOCUMENT_METADATA_REGION' for x in rows)
    assert any(x['filter_reason']=='OVERSIZED_BOX' for x in rows)


def test_detector_duplicate_nms_and_source_boxes_survive():
    rows=clean_detector_proposals([detect('a',.3,.3),detect('b',.3,.3,score=.85)],[])
    assert [x['filter_reason'] for x in rows]==[None,'DUPLICATE_DETECTION']


def test_association_near_instrument_and_abstain_far():
    rr,_=recover_readings([word('one','PT-101',.3,.3),word('two','V-2201',.85,.4)],[])
    ds=clean_detector_proposals([detect('pt',.29,.29)],[])
    result=associate_readings(rr,ds)
    matched={x['tag_id']:x for x in result}
    pt=next(r for r in rr if r['text_candidate']=='PT-101')
    vessel=next(r for r in rr if r['text_candidate']=='V-2201')
    assert matched[pt['id']]['association_state']=='PROPOSED_UNVERIFIED'
    assert matched[pt['id']]['detector_id']=='det-pt'
    assert matched[vessel['id']]['association_state']=='NO_ELIGIBLE_NEARBY_SYMBOL'


def test_matching_abstains_when_two_tags_claim_one_symbol():
    rr,_=recover_readings([word('one','PT-101',.3,.3),word('two','PT-102',.31,.3)],[])
    ds=clean_detector_proposals([detect('x',.3,.3)],[])
    result=associate_readings(rr,ds)
    assert all(x['association_state']=='MULTIPLE_TAGS_COMPETE_FOR_SYMBOL' for x in result)
    assert all(x['detector_id'] is None for x in result)


def test_invalid_source_and_source_hash_rejected():
    with pytest.raises(ValueError):recover_wp123(b'not-pdf',[],[])
    result=recover_wp123(PDF,[],[])
    assert validate_wp123(result,PDF,[],[])==[]
    assert validate_wp123(result,PDF+b'changed',[],[])
    result['summary']['tags_proposed']=100
    assert validate_wp123(result,PDF,[],[])


def test_scanned_circle_anchored_to_instrument_code_not_empty_border():
    import cv2
    im=np.full((400,600),255,dtype=np.uint8)
    cv2.circle(im,(190,160),19,0,2)
    cv2.rectangle(im,(420,140),(460,180),0,2)
    words=[word('code','PT',(.5*0+190)/600-.008,160/400-.009,w=.016,h=.018)]
    out=circle_candidates_from_image(im,words)
    assert any('PT' in o['code_candidates'] for o in out)
    assert all(o['bbox']['x0']<.5 for o in out)


def test_csv_export_does_not_spreadsheet_inject(tmp_path):
    w=[word('bad','=SUM(1,2)',.2,.2),word('good','V-2201',.3,.2)]
    result=recover_wp123(PDF,w,[])
    save_wp123(result,tmp_path)
    rows=list(csv.DictReader(open(tmp_path/'proposed_engineering_register.csv')))
    assert len(rows)==1 and rows[0]['text_candidate']=='V-2201'
    assert json.loads((tmp_path/'wp123_result.json').read_text())['result_sha256']==result['result_sha256']


def test_ocr_anchored_bubble_input_proposal_does_not_raise_acceptance():
    bubble={'id':'bubble1','bbox':{'x0':.15,'y0':.15,'x1':.2,'y1':.2},'page':1,
        'state':'CODE_AND_NUMBER_EVIDENCE','review_state':'PROPOSED_UNVERIFIED'}
    out=recover_wp123(PDF,[],[],bubbles=[bubble])
    assert out['summary']['raster_bubbles_with_code_and_number']==1
    assert out['summary']['reviewed_engineering_objects']==0
    assert validate_wp123(out,PDF,[],[],bubbles=[bubble])==[]


def test_model_evidence_declared_different_source_rejected(tmp_path):
    path=tmp_path/'detections.json'
    path.write_text(json.dumps({'source_sha256':'a'*64,'detections':[]}),encoding='utf-8')
    with pytest.raises(ValueError,match='source PDF hash'):
        read_detectors(path,expected_source_sha256='b'*64)
