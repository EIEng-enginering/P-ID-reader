"""Claude Windows-3.12 increment R01: OCR backends, link safety. Synthetic input only."""
from __future__ import annotations
import json
from pathlib import Path

import sqlite3
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


def test_entry_dispatch_routes_worker_flags(monkeypatch, tmp_path):
    import pid_reader.entry as entry
    import pid_reader.worker as w
    seen = {}
    monkeypatch.setattr(w, 'main', lambda a: seen.setdefault('a', a) and 0)
    assert entry.main(['--pid-worker', 'run', '--x'], default='cli') == 0
    assert seen['a'] == ['run', '--x']


def test_dexpi_adapter_refuses_instead_of_faking_conformance():
    from pid_reader.engineering import dexpi
    assert dexpi.STATUS == 'NOT_IMPLEMENTED'
    with pytest.raises(dexpi.DexpiNotAvailable):
        dexpi.export_dexpi(object(), 'x.xml')


def test_html_and_csv_hide_unlabelled_strokes_but_json_keeps_them(tmp_path):
    from pid_reader.engineering.reports import make_report, report_csv, report_html
    pdf = (FIX / 'synthetic_catalog_symbols.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='c.pdf')
    strokes = [o for o in extraction['objects'] if o['class'] == 'LINE' and not o['text']]
    assert strokes, 'fixture should contain unlabelled strokes'
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        db.add_extraction(extraction, source_pdf_bytes=pdf)
        report = make_report(db)
        assert len(report['readings']) == len(extraction['objects'])           # JSON/audit record is complete
        html, csv_text = report_html(report), report_csv(report)
        assert 'V-101' in html and 'Summary' in html and 'not listed' in html
        assert csv_text.count('\n') < len(report['readings'])                  # strokes omitted by default
        full = report_csv(report, include_strokes=True)
        assert full.count('\n') >= len(report['readings'])


# ---- outlined-lettering sheets: stacked instrument tags and sparse-text detection --------------

def _w(i, text, x, y, w=0.006, h=0.006):
    return {"id": f"w{i}", "text": text, "bbox": {"x0": x, "y0": y, "x1": x + w, "y1": y + h}, "raw_ocr_score": 0.9}


def test_stacked_bubble_text_is_joined_into_one_instrument_tag():
    from pid_reader.engineering.standalone_read import _stacked_instrument_tags
    words = [_w(1, "PIT", .553, .441), _w(2, "100", .554, .446, h=.005), _w(3, "00", .554, .4461, h=.003),   # overlapping OCR boxes + fragment
             _w(4, "PSHH", .386, .434, w=.009, h=.005), _w(5, "201", .387, .437, w=.007, h=.007),
             _w(6, "HOLD", .519, .390, w=.01), _w(7, "100", .52, .396),                                   # words, not instrument functions
             _w(8, "FC", .487, .517), _w(9, "16", .476, .515)]                                              # 2-letter text beside a size: not stacked
    got = {t["text"] for t in _stacked_instrument_tags(words)}
    assert got == {"PIT-100", "PSHH-201"}


def test_stacked_tag_needs_alignment_below_the_letters():
    from pid_reader.engineering.standalone_read import _stacked_instrument_tags
    far_right = [_w(1, "PIC", .30, .30), _w(2, "102", .45, .305)]
    above = [_w(1, "PIC", .30, .30), _w(2, "102", .30, .24)]
    assert _stacked_instrument_tags(far_right) == [] and _stacked_instrument_tags(above) == []


def test_text_poor_but_graphics_rich_sheet_is_flagged_for_ocr():
    import io
    from reportlab.pdfgen import canvas
    from pid_reader.engineering.standalone_read import _sparse_vector_pages
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(600, 400), pageCompression=0, invariant=1)
    for i in range(900):
        c.line(10 + i % 500, 10 + i // 3 % 300, 15 + i % 500, 20 + i // 3 % 300)
    c.drawString(20, 380, 'TITLE ONLY')
    c.save()
    assert _sparse_vector_pages(out.getvalue(), [1]) == [1]
    assert _sparse_vector_pages((FIX / 'synthetic_pid_vector.pdf').read_bytes(), [1]) == []


def test_report_includes_analysis_layers_and_connectivity(tmp_path):
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.reports import make_report, report_html, verify_report
    pdf = (FIX / 'synthetic_catalog_symbols.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='c.pdf')
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine=None)
        report = make_report(db)
        assert verify_report(report)
        block = report['analysis'][0]
        assert block['layers']['symbols']['count'] > 0 and block['layers']['geometry']['count'] > 0
        assert block['connectivity']['node_counts']
        html = report_html(report)
        for needle in ('Analysis layers', 'Proposed connectivity', 'Findings', 'Outline symbols'):
            assert needle in html
        assert 'Valves / line styles' in html
        assert make_report(db, include_analysis=False)['analysis'] == []


def test_tag_from_bubble_lines_accepts_stacked_and_single_line_forms_only():
    from pid_reader.engineering.standalone_read import _tag_from_bubble_lines as t
    assert t(["0", "PIT", "100"]) == ("PIT", "100", "PIT-100")        # leading loop-number zero ignored
    assert t(["ZSC", "201"])[2] == "ZSC-201"
    assert t(["PIC 102"])[2] == "PIC-102"
    assert t(["FBV", "200"])[2] == "FBV-200"
    assert t(["IF"]) is None                                          # symbol label, no number
    assert t(["HOLD", "100"]) is None                                 # not an instrument function
    assert t(["NEW", "2015"]) is None
    assert t([]) is None


# ---- sheet information -------------------------------------------------------

def _ow(text, x, y, w=0.05, h=0.01, page=1):
    return {"text": text, "page": page, "bbox": {"x0": x, "y0": y, "x1": x + w, "y1": y + h}}


def test_sheet_fields_title_block_line_sizes_and_set_points():
    from pid_reader.engineering.sheet_fields import sheet_fields, flatten
    empty = {"objects": []}
    words = [_ow("REV", .85, .93, .02), _ow("C", .88, .93, .01), _ow("0209-01-ML-02-001", .70, .94, .12),
             _ow("Page", .60, .96, .03), _ow("1", .64, .96, .01), _ow("of", .66, .96, .01), _ow("2", .68, .96, .01),
             _ow("February", .10, .96, .05), _ow("2015", .16, .96, .03),
             _ow("NPS", .40, .50, .02), _ow("20", .43, .50, .01),
             _ow("NPS", .50, .60, .02), _ow("30", .53, .60, .01), _ow("x", .55, .60, .01), _ow("NPS", .57, .60, .02), _ow("20", .60, .60, .01),
             _ow("SP=3450kPa(g)", .55, .70, .10), _ow("6\"-P-1501-A1A", .30, .30, .12),
             _ow("dN", .20, .20, .02), _ow("1", .23, .20, .01)]
    f = sheet_fields(empty, words)
    tb = f["title_block"]
    assert tb["drawing_number"][0]["text"] == "0209-01-ML-02-001" and tb["drawing_number"][0]["in_title_block_zone"]
    assert [i["text"] for i in tb["revision"]] == ["C"]
    assert tb["sheet"][0]["text"] == "1 of 2" and any("2015" in d["text"] for d in tb["date"])
    sizes = {i["size"] for i in f["line_sizes"]}
    assert {"20", "30 x 20"} <= sizes and "1" not in sizes            # lowercase "dN 1" is not a DN size
    assert f["set_points"][0]["value"] == "3450" and f["set_points"][0]["gauge_or_abs"] == "gauge"
    assert f["line_numbers"][0]["text"] == '6"-P-1501-A1A'
    assert all(i["status"] == "PROPOSED_UNVERIFIED" for i in f["line_sizes"] + f["set_points"])
    assert flatten(f)


def test_sheet_fields_prefers_native_text_and_keeps_alternatives():
    from pid_reader.engineering.sheet_fields import sheet_fields
    ex = {"objects": [{"text": "DWG-A1-ZZ-001", "page": 1, "bbox": {"x0": .7, "y0": .9, "x1": .8, "y1": .92}}]}
    ocr = [_ow("DWG-A1-ZZ-001", .71, .905, .08, .01), _ow("OTHER-12-AB-345", .2, .5, .1)]   # first overlaps native text
    f = sheet_fields(ex, ocr)
    texts = [i["text"] for i in f["title_block"]["drawing_number"]]
    assert texts.count("DWG-A1-ZZ-001") == 1 and "OTHER-12-AB-345" in texts        # no duplicate, alternative kept
    assert texts[0] == "DWG-A1-ZZ-001"                                              # title-block zone candidate first


# ---- teach-by-example symbol search -------------------------------------------

def _valve_sheet():
    """Page with several identical bow-tie valves (one vertical), a plain circle and text."""
    import io
    from reportlab.pdfgen import canvas
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(842, 595), pageCompression=0, invariant=1)

    def bow(x, y, a=14, b=10):
        for dx, dy in ((-a, -b), (-a, b), (a, -b), (a, b)):
            c.line(x, y, x + dx, y + dy)
        c.line(x - a, y - b, x - a, y + b)
        c.line(x + a, y - b, x + a, y + b)
    for x, y in ((150, 400), (350, 400), (550, 400), (250, 200)):
        c.line(x - 60, y, x - 14, y)
        c.line(x + 14, y, x + 60, y)
        bow(x, y)
    c.circle(650, 200, 18)
    c.drawString(50, 560, 'TEACH TEST SHEET')
    c.save()
    return out.getvalue()


def test_find_similar_locates_other_valves_and_not_the_example_or_circle():
    from pid_reader.engineering.example_matching import find_similar
    pdf = _valve_sheet()
    # example = the valve at (150,400) in page points, converted to a normalised top-left box
    box = {"x0": (150 - 17) / 842, "y0": 1 - (400 + 13) / 595, "x1": (150 + 17) / 842, "y1": 1 - (400 - 13) / 595}
    r = find_similar(pdf, 1, box, threshold=0.75)
    centres = sorted(((m["bbox"]["x0"] + m["bbox"]["x1"]) / 2 * 842, (1 - (m["bbox"]["y0"] + m["bbox"]["y1"]) / 2) * 595) for m in r["matches"])
    near = lambda p, q: abs(p[0] - q[0]) < 12 and abs(p[1] - q[1]) < 12
    for target in ((350, 400), (550, 400)):
        assert any(near(c, target) for c in centres), (target, centres)
    assert not any(near(c, (150, 400)) for c in centres)           # the example itself is not proposed
    assert not any(near(c, (650, 200)) for c in centres)           # a plain circle is not a valve
    assert all(m["score"] >= 0.75 for m in r["matches"])


def test_find_similar_refuses_bad_examples():
    from pid_reader.engineering.example_matching import find_similar
    pdf = _valve_sheet()
    with pytest.raises(ValueError):
        find_similar(pdf, 1, {"x0": .01, "y0": .01, "x1": .03, "y1": .03})           # blank paper
    with pytest.raises(ValueError):
        find_similar(pdf, 1, {"x0": .1, "y0": .1, "x1": .101, "y1": .101})           # too small
    with pytest.raises(ValueError):
        find_similar(pdf, 1, {"x0": 0, "y0": 0, "x1": 1, "y1": 1})                   # whole page
    with pytest.raises(ValueError):
        find_similar(pdf, 2, {"x0": .1, "y0": .1, "x1": .2, "y1": .2})               # no such page


def test_teach_symbol_is_stored_reviewed_audited_and_idempotent(tmp_path):
    from pid_reader.engineering import findings
    from pid_reader.engineering.examples import teach_symbol
    pdf = _valve_sheet()
    extraction = read_pid(pdf, ReadParams(), filename='valves.pdf')
    box = {"x0": (150 - 17) / 842, "y0": 1 - (400 + 13) / 595, "x1": (150 + 17) / 842, "y1": 1 - (400 - 13) / 595}
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        aid, result = teach_symbol(db, eid, page=1, bbox=box, label='Block valve', class_hint='VALVE', actor='Tester', threshold=0.75)
        assert result['matches']
        again, _ = teach_symbol(db, eid, page=1, bbox=box, label='Block valve', class_hint='VALVE', actor='Tester', threshold=0.75)
        assert again == aid                                                      # same result -> same record
        items = findings.list_findings(db, eid, 'examples')
        assert len(items) == len(result['matches']) and all(i['state'] == 'PROPOSED' for i in items)
        assert 'Block valve' in items[0]['label']
        findings.review_finding(db, 'examples', items[0]['id'], actor='Reviewer', decision='ACCEPTED_AS_READING', reason='Looks like a block valve')
        assert findings.list_findings(db, eid, 'examples')[0]['state'] == 'ACCEPTED_AS_READING'
        with pytest.raises(ValueError):
            findings.review_finding(db, 'examples', items[0]['id'], actor='R', decision='CONNECTED_AS_DRAWN', reason='wrong vocabulary')
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute("UPDATE example_match_candidate SET page=9")           # append-only
        assert db.verify_audit_chain()
        kinds = [r[0] for r in db.db.execute("SELECT event_type FROM audit_event")]
        assert 'SYMBOL_EXAMPLE_TAUGHT' in kinds and 'SYMBOL_EXAMPLE_REVIEW' in kinds


# ---- checks, loops, canonical graph ----------------------------------------------

def _obj(text, cls, x, y, page=1, source='TEXT'):
    return {"id": f"o-{text}-{x}", "class": cls, "page": page, "text": text, "confidence": .5,
            "bbox": {"x0": x, "y0": y, "x1": x + .02, "y1": y + .01}, "attributes": {"source": source}}


def test_instrument_loops_group_by_loop_number():
    from pid_reader.engineering.checks import instrument_loops
    ex = {"objects": [_obj("PIC-102", "INSTRUMENT", .1, .1), _obj("PY-102", "INSTRUMENT", .2, .1),
                      _obj("PCV-102", "INSTRUMENT", .3, .1), _obj("PIT-101", "INSTRUMENT", .4, .1),
                      _obj("P-102", "PUMP", .5, .1)]}
    loops = {l["loop"]: [m["tag"] for m in l["members"]] for l in instrument_loops(ex)}
    assert loops == {"102": ["PCV-102", "PIC-102", "PY-102"], "101": ["PIT-101"]}


def test_consistency_checks_flag_probable_misreads_without_claiming_plant_facts():
    from pid_reader.engineering.checks import consistency_checks
    ex = {"objects": [_obj("PIC-102", "INSTRUMENT", .10, .10), _obj("PIC-102", "INSTRUMENT", .50, .50),
                      _obj("P-201", "PUMP", .30, .30), _obj("PT-900", "INSTRUMENT", .80, .80)]}
    box = lambda x, y: {"x0": x - .01, "y0": y - .01, "x1": x + .04, "y1": y + .03}
    symbols = [{"page": 1, "bbox": box(.30, .30), "candidate_class": "INSTRUMENT_BUBBLE_CANDIDATE",
                "outline_kind": "CLOSED_NEAR_CIRCULAR_OUTLINE"},                                  # equipment tag in a bubble
               {"page": 1, "bbox": {"x0": .6, "y0": .2, "x1": .613, "y1": .219}, "candidate_class": "UNCLASSIFIED_OUTLINE",
                "outline_kind": "CLOSED_NEAR_CIRCULAR_OUTLINE"}]                                   # bubble, no tag
    kinds = {c["check"] for c in consistency_checks(ex, symbols, {"title_block": {}})}
    assert {"DUPLICATE_TAG", "TAG_VS_SYMBOL", "INSTRUMENT_OUTSIDE_BUBBLE", "BUBBLE_WITHOUT_TAG", "SINGLE_MEMBER_LOOP",
            "TITLE_BLOCK_FIELD_MISSING"} <= kinds
    assert all(c["severity"] in ("INFO", "REVIEW") for c in consistency_checks(ex, symbols))


def test_canonical_graph_validates_against_spec_schema_and_graphml_parses(tmp_path):
    import json
    import jsonschema
    import xml.etree.ElementTree as ET
    from pid_reader.engineering.graph_export import canonical_graph, to_graphml
    from pid_reader.engineering.pipeline import analyze_drawing
    schema = json.loads((Path(__file__).resolve().parents[1] / 'contracts' / 'standalone_canonical_graph_v1.schema.json').read_text('utf-8'))
    pdf = (FIX / 'synthetic_catalog_symbols.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='c.pdf')
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine=None)
        g = canonical_graph(db, eid)
        errors = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(g)]
        assert errors == [], errors[:3]
        assert g['review_policy'] == 'PROPOSALS_ONLY' and g['nodes']
        assert all(n['review_state'] == 'PROPOSED_UNVERIFIED' for n in g['nodes'])
        ids = {n['id'] for n in g['nodes']}; pids = {p['id'] for p in g['ports']}
        assert all(p['owner_node_id'] in ids for p in g['ports'])                      # foreign keys
        assert all(e['from_port_id'] in pids and e['to_port_id'] in pids for e in g['edges'])
        assert len(ids) == len(g['nodes']) and canonical_graph(db, eid) == g          # unique and deterministic
        root = ET.fromstring(to_graphml(g))
        assert len(root.findall('.//{*}node')) == len(g['nodes'])


def test_report_html_includes_sheet_information_loops_and_checks(tmp_path):
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.reports import make_report, report_html, verify_report
    pdf = (FIX / 'synthetic_catalog_symbols.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='c.pdf')
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine=None)
        report = make_report(db)
        assert verify_report(report)
        block = report['analysis'][0]
        assert {'sheet_fields', 'loops', 'checks'} <= set(block)
        html = report_html(report)
        for needle in ('Sheet information', 'Instrument tags grouped by printed loop number', 'Reading checks'):
            assert needle in html
        assert 'no safety function is implied' in html


def test_xlsx_export_has_registers_loops_and_is_formula_safe(tmp_path):
    from openpyxl import load_workbook
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.xlsx_export import export_xlsx
    pdf = (FIX / 'synthetic_catalog_symbols.pdf').read_bytes()
    extraction = read_pid(pdf, ReadParams(), filename='=cmd|evil.pdf')                 # hostile file name
    with ProjectStore(tmp_path / 'p.sqlite') as db:
        eid = db.add_extraction(extraction, source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine=None)
        out = export_xlsx(db, tmp_path / 'out.xlsx')
        assert out.exists() and not list(tmp_path.glob('.pid-xlsx-*'))                # atomic, no temp left
        wb = load_workbook(out)
        assert {'Read me', 'Equipment', 'Valves', 'Instruments', 'Loops', 'Lines', 'Sheet info', 'Findings',
                'Connections', 'Checks', 'Notes', 'OCR words'} <= set(wb.sheetnames)
        tags = {r[2] for r in wb['Equipment'].iter_rows(min_row=2, values_only=True)} | \
               {r[2] for r in wb['Instruments'].iter_rows(min_row=2, values_only=True)}
        assert {'V-101', 'PT-101'} <= tags
        assert len(list(wb['Findings'].iter_rows(min_row=2))) > 5
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    assert not (isinstance(v, str) and v.startswith(('=', '+', '@'))), (ws.title, v)    # no live formulas
        assert wb['Equipment']['A2'].value.startswith("'=") or wb['Equipment']['A2'].value == "'=cmd|evil.pdf"
        with pytest.raises(FileNotFoundError):
            export_xlsx(db, tmp_path / 'nofolder' / 'x.xlsx')


def test_cli_export_xlsx_graph_teach_and_sheet_info(tmp_path, capsys):
    import json
    from pid_reader.cli import main
    pdf = tmp_path / 'valves.pdf'
    pdf.write_bytes(_valve_sheet())
    db = str(tmp_path / 'p.sqlite')
    assert main(['init-project', db]) == 0
    capsys.readouterr()
    assert main(['import-pdf', db, str(pdf), '--ocr', 'off']) == 0
    eid = json.loads(capsys.readouterr().out.strip().splitlines()[-1])['extraction_id']
    box = ['0.1573', '0.3277', '0.2027', '0.3496']      # normalised box round the valve at (150,400) pt
    assert main(['teach-symbol', db, eid, '--page', '1', '--box', *box, '--label', 'Block valve', '--kind', 'VALVE',
                 '--actor', 'Tester', '--threshold', '0.75']) == 0
    taught = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert taught['matches'] >= 2
    assert main(['export-xlsx', db, str(tmp_path / 'o.xlsx')]) == 0 and (tmp_path / 'o.xlsx').exists()
    capsys.readouterr()
    assert main(['analyze-all', db, eid, '--ocr', 'off']) == 0
    capsys.readouterr()
    for fmt, name in (('json', 'g.json'), ('graphml', 'g.graphml')):
        assert main(['graph-export', db, eid, str(tmp_path / name), '--format', fmt]) == 0
    assert json.loads((tmp_path / 'g.json').read_text('utf-8'))['review_policy'] == 'PROPOSALS_ONLY'
    capsys.readouterr()
    assert main(['sheet-info', db, eid]) == 0
    info = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert {'sheet_fields', 'loops', 'checks'} <= set(info)
