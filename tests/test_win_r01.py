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


# ---- full analysis pipeline -------------------------------------------------

def test_pipeline_runs_all_layers_and_is_idempotent(tmp_path):
    from pid_reader.engineering.pipeline import analyze_drawing, STAGES
    pdf = (FIX / 'synthetic_symbols_ports.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='s.pdf')
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        seen = []
        out = analyze_drawing(db, eid, ocr_engine=None, progress=lambda s, f, m: seen.append(s))
        assert set(out['stages']) == set(STAGES)
        assert out['stages']['geometry']['status'] == 'DONE'
        assert out['stages']['symbols']['status'] == 'DONE'
        assert out['stages']['ocr']['status'] == 'SKIPPED'
        assert out['stages']['text_links']['status'] == 'SKIPPED'
        assert seen and seen[-1] == 'done'
        again = analyze_drawing(db, eid, ocr_engine=None)
        assert again['analyses'] == out['analyses']
        assert db.verify_audit_chain()


@pytest.mark.skipif(not ocr_source.rapidocr_available(), reason='RapidOCR (optional) not installed')
def test_pipeline_with_rapidocr_links_tags(tmp_path):
    from pid_reader.engineering.pipeline import analyze_drawing
    pdf = (FIX / 'synthetic_symbols_ports.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='s.pdf')
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        out = analyze_drawing(db, eid, ocr_engine='rapidocr')
        assert out['stages']['ocr']['status'] == 'DONE', out['stages']['ocr']
        assert out['stages']['text_links']['status'] == 'DONE', out['stages']['text_links']


def test_pipeline_cancel_stops_cleanly(tmp_path):
    from pid_reader.api import CancelToken, Cancelled
    from pid_reader.engineering.pipeline import analyze_drawing
    pdf = (FIX / 'synthetic_symbols_ports.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='s.pdf')
    token = CancelToken()
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        def stop(stage, frac, msg):
            if stage == 'symbols':
                token.cancel()
        with pytest.raises(Cancelled):
            analyze_drawing(db, eid, ocr_engine=None, progress=stop, cancel=token)
        assert db.verify_audit_chain()


# ---- process isolation ------------------------------------------------------
import os
import sys
import time


def test_isolated_reader_matches_in_process_result():
    from pid_reader.engineering.isolation import read_pid_isolated
    pdf = (FIX / 'synthetic_pid_vector.pdf').read_bytes()
    direct = read_pid(pdf, ReadParams(), filename='v.pdf')
    isolated = read_pid_isolated(pdf, ReadParams(), filename='v.pdf')
    strip = lambda r: {k: v for k, v in r.items() if k != 'provenance'}
    assert strip(isolated) == strip(direct)
    assert isolated['provenance']['input_sha256'] == direct['provenance']['input_sha256']


def test_isolated_reader_maps_refusal_codes():
    from pid_reader.api import RefusedInput
    from pid_reader.engineering.isolation import read_pid_isolated
    with pytest.raises(RefusedInput) as exc:
        read_pid_isolated(b'%PDF-1.4 not really a pdf', ReadParams())
    assert exc.value.code in ('PID_MALFORMED', 'PID_ENCRYPTED')


def test_isolated_reader_cancel_kills_child():
    from pid_reader.api import Cancelled
    from pid_reader.engineering.isolation import read_pid_isolated
    pdf = (FIX / 'synthetic_pid_vector.pdf').read_bytes()
    t0 = time.monotonic()
    with pytest.raises(Cancelled):
        read_pid_isolated(pdf, ReadParams(), should_cancel=lambda: True)
    assert time.monotonic() - t0 < 10


def test_run_limited_timeout_kills_process():
    from pid_reader.engineering.isolation import run_limited
    t0 = time.monotonic()
    code, _err, reason = run_limited([sys.executable, '-c', 'import time; time.sleep(60)'],
                                     env=dict(os.environ), cwd=os.getcwd(), timeout_s=1, memory_mb=512)
    assert reason == 'timeout' and time.monotonic() - t0 < 15


def test_run_limited_memory_cap_stops_memory_hog():
    from pid_reader.engineering.isolation import run_limited, memory_cap_enforced
    if not memory_cap_enforced():
        pytest.skip('memory cap not enforceable here (already inside a non-nestable job)')
    code, _err, reason = run_limited(
        [sys.executable, '-c', 'x = bytearray(1500 * 1024 * 1024); print(len(x))'],
        env=dict(os.environ), cwd=os.getcwd(), timeout_s=60, memory_mb=512)
    assert reason == '' and code != 0


# ---- batch with isolation / cancellation -----------------------------------

def _copy_fixtures(tmp_path, names):
    import shutil
    out = []
    for n in names:
        shutil.copy(FIX / n, tmp_path / n)
        out.append(tmp_path / n)
    return out


def test_batch_isolated_imports_and_records_outcomes(tmp_path):
    from pid_reader.engineering.batch import start_batch, resume_batch
    files = _copy_fixtures(tmp_path, ['synthetic_pid_vector.pdf', 'synthetic_rev_o_a.pdf'])
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        bid = start_batch(db, files, actor='Tester')
        ticks = []
        job = resume_batch(db, bid, isolated=True, progress=lambda d, t, n: ticks.append((d, t, n)))
        assert job['counts']['imported'] == 2 and job['state'] == 'COMPLETE'
        assert len(ticks) == 2 and ticks[0][1] == 2
        assert db.verify_audit_chain()


def test_batch_cancel_leaves_remaining_files_resumable(tmp_path):
    from pid_reader.engineering.batch import start_batch, resume_batch
    files = _copy_fixtures(tmp_path, ['synthetic_pid_vector.pdf', 'synthetic_rev_o_a.pdf', 'synthetic_rev_o_b.pdf'])
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        bid = start_batch(db, files, actor='Tester')
        calls = {'n': 0}
        def cancel_after_first():
            calls['n'] += 1
            return calls['n'] > 3   # a few polls: lets file 1 start, then cancels
        job = resume_batch(db, bid, isolated=True, should_cancel=cancel_after_first)
        assert job['state'] == 'INCOMPLETE'
        done_before = job['counts']['completed']
        assert done_before < 3
        job = resume_batch(db, bid, isolated=True)          # safe resume
        assert job['state'] == 'COMPLETE' and job['counts']['imported'] == 3


# ---- unified findings -------------------------------------------------------

@pytest.mark.parametrize('fixture', ['synthetic_catalog_symbols.pdf', 'synthetic_signal_links.pdf'])
def test_findings_cover_layers_and_review_round_trips(tmp_path, fixture):
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering import findings
    pdf = (FIX / fixture).read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename=fixture)
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine='rapidocr' if ocr_source.rapidocr_available() else None)
        total = 0
        for layer in findings.LAYERS:
            items = findings.list_findings(db, eid, layer)
            total += len(items)
            for it in items:
                assert it['state'] == 'PROPOSED'
                assert it['page'] >= 1
                if it['bbox'] is not None:
                    assert 0 <= it['bbox']['x0'] < it['bbox']['x1'] <= 1
        assert total > 0
        # review one finding of the first populated layer, state flips, audit chain intact
        layer = next(l for l in findings.LAYERS if findings.list_findings(db, eid, l))
        first = findings.list_findings(db, eid, layer)[0]
        decision = findings.DECISIONS[layer][-1] if findings.DECISIONS[layer][-1] == 'UNRESOLVED' else 'UNRESOLVED'
        findings.review_finding(db, layer, first['id'], actor='Reviewer A', decision=decision,
                                reason='Checked against printed drawing')
        again = findings.list_findings(db, eid, layer)[0]
        assert again['state'] == decision
        assert db.verify_audit_chain()
        with pytest.raises(ValueError):
            findings.review_finding(db, layer, first['id'], actor='X', decision='NOPE', reason='bad one')
        counts = findings.finding_counts(db, eid)
        assert counts[layer]['reviewed'] >= 1


# ---- scanned (image-only) drawings via standalone reader --------------------

def _scanned_pdf():
    import io
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    src = (FIX / 'synthetic_pid_vector.pdf').read_bytes()
    image = pdfium.PdfDocument(src)[0].render(scale=2.2).to_pil().convert('L')
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(595, 842), pageCompression=0, invariant=1)
    c.drawImage(ImageReader(image), 0, 0, 595, 842)
    c.save()
    return out.getvalue()


def test_frozen_r1_reader_still_refuses_scanned_page():
    from pid_reader.api import RefusedInput
    scanned = _scanned_pdf()
    result = read_pid(scanned, ReadParams(), filename='scan.pdf')
    assert result['pages'][0]['read_status'] == 'REFUSED'
    assert not result['objects']


@pytest.mark.skipif(not ocr_source.rapidocr_available(), reason='RapidOCR (optional) not installed')
def test_standalone_reader_ocr_reads_scanned_page_and_passes_r1_schema_check(tmp_path):
    from pid_reader.engineering.standalone_read import read_pid_standalone
    scanned = _scanned_pdf()
    result = read_pid_standalone(scanned, ReadParams(), filename='scan.pdf', ocr_engine='rapidocr')
    assert result['pages'][0]['read_status'] == 'READ'
    texts = {o['text'] for o in result['objects']}
    assert 'V-101' in texts
    assert all(o['attributes']['source'] == 'OCR' and o['confidence'] <= 0.55 and o['status'] == 'UNVERIFIED'
               for o in result['objects'])
    assert result['provenance']['models'] and all(m['licence'] == 'Apache-2.0' for m in result['provenance']['models'])
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
    import check_extraction
    schema = Path(__file__).resolve().parents[1] / 'contracts/worksheet_r1_schemas/pid_extraction.schema.json'
    assert check_extraction.check(result) == []
    assert check_extraction.schema_check(result, schema) == []
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(result, source_pdf_bytes=scanned)
        assert db.list_objects(extraction_id=eid, text='V-101')


@pytest.mark.skipif(not ocr_source.rapidocr_available(), reason='RapidOCR (optional) not installed')
def test_isolated_standalone_reader_matches_in_process_for_scanned_page():
    from pid_reader.engineering.isolation import read_pid_isolated
    from pid_reader.engineering.standalone_read import read_pid_standalone
    scanned = _scanned_pdf()
    child = read_pid_isolated(scanned, ReadParams(), filename='scan.pdf', ocr_engine='rapidocr', timeout_s=120)
    direct = read_pid_standalone(scanned, ReadParams(), filename='scan.pdf', ocr_engine='rapidocr')
    key = lambda r: sorted((o['text'], o['class'], o['page']) for o in r['objects'])
    assert key(child) == key(direct)


# ---- reader robustness: upside-down pages and touching labels ---------------

def _pdf_with(draw):
    import io
    from reportlab.pdfgen import canvas
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(600, 400), pageCompression=0, invariant=1)
    c.setFont('Helvetica', 10)
    draw(c)
    c.save()
    return out.getvalue()


def test_upside_down_page_text_is_read_in_correct_order():
    import io
    from pypdf import PdfReader, PdfWriter
    src = _pdf_with(lambda c: (c.drawString(100, 200, 'E-219'), c.drawString(300, 200, 'XV-101'), c.drawString(300, 300, 'PT-101')))
    r = PdfReader(io.BytesIO(src)); w = PdfWriter(); pg = r.pages[0]; pg.rotate(180); w.add_page(pg)
    buf = io.BytesIO(); w.write(buf)
    result = read_pid(buf.getvalue(), ReadParams(), filename='r180.pdf')
    assert {'E-219', 'XV-101', 'PT-101'} <= {o['text'] for o in result['objects']}


def test_touching_labels_are_split_into_two_readings():
    pdf = _pdf_with(lambda c: c.drawString(100, 200, 'HV-383HV-303'))
    result = read_pid(pdf, ReadParams(), filename='m.pdf')
    objs = [o for o in result['objects'] if o['class'] not in ('LINE', 'NOTE')]
    assert {o['text'] for o in objs} == {'HV-383', 'HV-303'}
    assert all(o['attributes'].get('split_from_touching_labels') == 'true' for o in objs)
    a, b = sorted(objs, key=lambda o: o['bbox']['x0'])
    assert a['bbox']['x1'] <= b['bbox']['x0'] + 1e-6


def test_normal_text_not_reversed_or_split():
    pdf = _pdf_with(lambda c: (c.drawString(100, 200, 'P-102A'), c.drawString(200, 200, 'LT-301')))
    result = read_pid(pdf, ReadParams(), filename='n.pdf')
    assert {o['text'] for o in result['objects'] if o['class'] not in ('LINE', 'NOTE')} == {'P-102A', 'LT-301'}
