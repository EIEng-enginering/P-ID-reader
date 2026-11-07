from __future__ import annotations
from io import BytesIO
import sqlite3
from pypdf import PdfReader,PdfWriter
import pytest
from pid_reader.api import ReadParams, read_pid, RefusedInput
from pid_reader.engineering.project import ProjectStore


def test_rotated_page_normalised_boxes(synthetic_pdf):
    r=PdfReader(BytesIO(synthetic_pdf))
    w=PdfWriter();w.add_page(r.pages[0].rotate(90))
    dest=BytesIO();w.write(dest)
    out=read_pid(dest.getvalue(),ReadParams())
    assert out["pages"][0]["rotation"] in (0,90,180,270)
    for o in out["objects"]:
        b=o["bbox"]
        assert 0<=b["x0"]<b["x1"]<=1
        assert 0<=b["y0"]<b["y1"]<=1


def test_case_insensitive_tag_category_and_verbatim():
    from pid_reader.formats.pdf_source import _parse_tag
    category,parsed,score=_parse_tag("pt-123")
    assert category=="INSTRUMENT"
    assert parsed["normalised_tag"]=="PT-123"
    category,parsed,score=_parse_tag('6"-P-1501-A1A')
    assert category=="LINE"
    assert score<1.0


def test_append_only_audit_and_chain(synthetic_pdf,tmp_path):
    data=read_pid(synthetic_pdf,ReadParams())
    with ProjectStore(tmp_path/"chain.sqlite") as db:
        db.add_extraction(data)
        oid=db.list_objects()[0]["observation_id"]
        db.review(oid,actor="Synthetic Reviewer",decision="REJECTED",reason="Synthetic rejection demonstration")
        assert db.verify_audit_chain()
        with pytest.raises(sqlite3.DatabaseError):
            with db.db:
                db.db.execute("UPDATE audit_event SET event_json='{}' WHERE event_id=1")
        assert db.verify_audit_chain()


def test_source_bytes_must_match_result(synthetic_pdf,tmp_path):
    data=read_pid(synthetic_pdf,ReadParams())
    with ProjectStore(tmp_path/"hash.sqlite") as db:
        with pytest.raises(ValueError):
            db.add_extraction(data,source_pdf_bytes=b"not the same")
