"""Rev R stress and negative tests: geometry is NOT verified pipe connectivity."""
from __future__ import annotations
import io
import pytest
from reportlab.pdfgen import canvas

from pid_reader.api import LimitExceeded
from pid_reader.engineering import topology


def many_isolated_strokes(cols=100, rows=55):
    """5,500 independent 2.1pt vectors, clear 3.9pt gaps."""
    out = io.BytesIO()
    page_width = max(700, cols * 6 + 20)
    page_height = max(420, rows * 6 + 20)
    c = canvas.Canvas(out, pagesize=(page_width, page_height), pageCompression=1)
    for row in range(rows):
        for col in range(cols):
            x, y = 12 + 6 * col, 12 + 6 * row
            c.line(x, y, x + 2.1, y)
    c.save()
    return out.getvalue()


def compact_strokes(n=30):
    out=io.BytesIO(); c=canvas.Canvas(out, pagesize=(300,300))
    for i in range(n):
        c.line(20, 20 + i*2, 240, 20 + i*2)
    c.save();return out.getvalue()


def test_more_than_4000_vectors_is_supported_and_complete():
    pdf=many_isolated_strokes()
    res=topology.analyze_pdf_topology(pdf)
    assert len(res['segments'])==5500
    assert not res['contact_candidates']
    assert topology.validate_topology_result(res)==[]
    assert res['algorithm']=='vector-topology-0.3-bounded-index'
    assert all(x['status']=='PROPOSED_GEOMETRY' for x in res['segments'])


def test_dense_work_budget_refuses_instead_of_silently_dropping(monkeypatch):
    monkeypatch.setattr(topology,'MAX_PAIRS_EVALUATED',5)
    with pytest.raises(LimitExceeded,match='pair work budget'):
        topology.analyze_pdf_topology(compact_strokes())


def test_stroke_cap_refuses_without_partial_result(monkeypatch):
    monkeypatch.setattr(topology,'MAX_SEGMENTS',10)
    with pytest.raises(LimitExceeded,match='Too many native vector segments'):
        topology.analyze_pdf_topology(compact_strokes())


def test_grid_membership_budget_refuses_without_partial_result(monkeypatch):
    monkeypatch.setattr(topology,'MAX_GRID_MEMBERSHIPS',3)
    with pytest.raises(LimitExceeded,match='spatial index work budget'):
        topology.analyze_pdf_topology(compact_strokes())


def test_output_size_budget_refuses_without_partial_result(monkeypatch):
    monkeypatch.setattr(topology,'MAX_TOPOLOGY_BYTES',120)
    with pytest.raises(LimitExceeded,match='8 MiB'):
        topology.analyze_pdf_topology(compact_strokes(2))


def test_old_analysis_versions_still_validate():
    res=topology.analyze_pdf_topology(compact_strokes(4))
    res['algorithm']='vector-topology-0.2'
    from pid_reader.api import canonical_json, sha256_hex
    res['result_sha256']=sha256_hex(canonical_json({k:v for k,v in res.items() if k!='result_sha256'}).encode())
    assert topology.validate_topology_result(res)==[]


def test_contact_sets_and_hashes_stable():
    pdf=compact_strokes(5)
    first=topology.analyze_pdf_topology(pdf)
    second=topology.analyze_pdf_topology(pdf)
    assert first==second
    assert all(x['status']=='UNRESOLVED' for x in first['contact_candidates'])
