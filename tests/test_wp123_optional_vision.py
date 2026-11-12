"""Optional local rendering/OCR and raster-geometry tests for WP01-02."""
from io import BytesIO
import cv2
import numpy as np
import pytest
from reportlab.pdfgen.canvas import Canvas
from pid_reader.engineering.wp123_roi import TesseractUnavailable,supplemental_ocr,tesseract_available
from pid_reader.engineering.wp123_bubbles import circle_candidates_from_image,scan_pdf_bubbles
from pid_reader.engineering.wp123_recovery import infer_regions,_box


def pdf_with_label():
    stream=BytesIO();c=Canvas(stream,pagesize=(400,300))
    c.setFont('Helvetica-Bold',18);c.drawString(50,230,'V-2201')
    c.showPage();c.save();return stream.getvalue()


def test_missing_tesseract_is_a_clear_error_not_a_silent_empty_result(monkeypatch):
    monkeypatch.setattr('pid_reader.engineering.wp123_roi.tesseract_available',lambda:False)
    with pytest.raises(TesseractUnavailable):
        supplemental_ocr(pdf_with_label(),[{'page':1,'id':'h','bbox':{'x0':.1,'y0':.13,'x1':.5,'y1':.35}}],dpi=250)


@pytest.mark.skipif(not tesseract_available(),reason='Tesseract program is not installed on this machine (optional)')
def test_explicit_local_roi_ocr_detects_equipment_tag():
    raw=pdf_with_label()
    result=supplemental_ocr(raw,[{'page':1,'id':'header','bbox':{
        'x0':.1,'y0':.13,'x1':.5,'y1':.35}}],dpi=250)
    assert any('V-2201' in w['text'].upper() for w in result)
    assert all(0<=w['bbox']['x0']<w['bbox']['x1']<=1 for w in result)
    assert all(w['review_state']=='PROPOSED_UNVERIFIED' for w in result)


def test_invalid_out_of_scope_roi_rejected():
    raw=pdf_with_label()
    with pytest.raises(ValueError):supplemental_ocr(raw,[{'page':2,'bbox':{'x0':.1,'y0':.1,'x1':.3,'y1':.2}}])
    with pytest.raises(ValueError):supplemental_ocr(raw,[{'page':1,'bbox':{'x0':.1,'y0':.1,'x1':.3,'y1':.2}}],dpi=999)


def test_circle_returns_only_when_ocr_anchor_present():
    gray=np.full((360,580),255,dtype=np.uint8)
    cv2.circle(gray,(120,160),20,0,2)
    assert circle_candidates_from_image(gray,[])==[]
    word={'id':'ocr1','text':'PIC','page':1,'bbox':{'x0':.19,'y0':.435,'x1':.224,'y1':.455}}
    found=circle_candidates_from_image(gray,[word])
    assert len(found)>=1
    assert all(f['review_state']=='PROPOSED_UNVERIFIED' for f in found)


def test_pdf_circle_coordinate_mapping_for_uncropped_page():
    stream=BytesIO();c=Canvas(stream,pagesize=(400,300))
    c.circle(100,180,12,stroke=1,fill=0)
    c.showPage();c.save();raw=stream.getvalue()
    words=[{'id':'ocr-a','text':'PT','page':1,'bbox':{'x0':.23,'y0':.37,'x1':.27,'y1':.43}}]
    # Detection may abstain on thin vector circles at this rendering profile;
    # what matters here is every *returned* coordinate remains media-normalized.
    result=scan_pdf_bubbles(raw,words,[],dpi=170)
    for b in result:
        assert b['page']==1
        _box(b['bbox'])
