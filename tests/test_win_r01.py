"""Claude Windows-3.12 increment R01: OCR backends, link safety. Synthetic input only."""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from pid_reader.api import ReadParams, read_pid
from pid_reader.engineering.project import ProjectStore
from pid_reader.formats import ocr_source

FIX = Path(__file__).resolve().parents[1] / 'fixtures'


def test_unknown_engine_refused():
    with pytest.raises(ValueError):
        ocr_source.ocr_pdf_preview(b'%PDF-1.4', engine='cloud')


def test_available_engines_is_list_without_running_ocr():
    assert set(ocr_source.available_engines()) <= {'tesseract', 'rapidocr'}


@pytest.mark.skipif(not ocr_source.rapidocr_available(), reason='RapidOCR (optional) not installed')
def test_rapidocr_reads_raster_fixture_and_imports_with_validated_frame(tmp_path):
    pdf = (FIX / 'synthetic_pid_raster.pdf').read_bytes()
    result = ocr_source.ocr_pdf_preview(pdf, engine='rapidocr', dpi=150)
    assert ocr_source.verify_ocr_preview(result)
    assert result['algorithm'].startswith('rapidocr')
    texts = {w['text'] for p in result['pages'] for w in p['words']}
    assert 'V-101' in texts
    assert all(w['engine'] == 'local_rapidocr' and w['review_state'] == 'PROPOSED'
               for p in result['pages'] for w in p['words'])
    # The frozen R1 reader refuses raster-only pages; OCR is standalone evidence only.


@pytest.mark.skipif(not ocr_source.rapidocr_available(), reason='RapidOCR (optional) not installed')
def test_rapidocr_evidence_accepted_by_project_store(tmp_path):
    pdf = (FIX / 'synthetic_pid_vector.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='v.pdf')
    ocr = ocr_source.ocr_pdf_preview(pdf, engine='rapidocr', dpi=150,
                                     pages=tuple(p['page'] for p in extraction['pages']))
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        aid = db.add_ocr_analysis(eid, ocr)
        words = db.list_ocr_words(aid, text='V-101')
        assert words and words[0]['text'] == 'V-101'


def test_rapidocr_forged_engine_label_rejected(tmp_path):
    pdf = (FIX / 'synthetic_pid_vector.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='v.pdf')
    from pid_reader.engineering.text_links import validate_ocr_source
    from pid_reader.api import canonical_json, sha256_hex
    ocr = {'adapter': 'standalone_ocr_preview_v3', 'source_sha256': extraction['document']['sha256'],
           'selected_pages': [1], 'pages': [{'page': 1, 'words': [
               {'id': 'x', 'text': 'V-101', 'page': 1, 'bbox': {'x0': .1, 'y0': .1, 'x1': .2, 'y1': .2},
                'raw_ocr_score': .9, 'review_state': 'PROPOSED', 'engine': 'cloud_ocr'}]}]}
    problems = validate_ocr_source(ocr, extraction)
    assert problems
