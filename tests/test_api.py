from __future__ import annotations
import io
import json
import pytest
from pypdf import PdfReader, PdfWriter
from pid_reader.api import (
    ReadParams, RefusedInput, LimitExceeded, read_pid, sha256_hex, result_sha256,
)
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import check_extraction

SCHEMA=Path(__file__).resolve().parents[1]/"contracts/worksheet_r1_schemas/pid_extraction.schema.json"


def test_pdf_extraction_real_content(synthetic_pdf):
    result=read_pid(synthetic_pdf,ReadParams(),document_revision_id="test-rev-a",filename="synthetic.pdf",expected_sha256=sha256_hex(synthetic_pdf))
    assert result["document"]["page_count"]==1
    assert any(x["text"]=="V-101" and x["class"]=="VESSEL" for x in result["objects"])
    assert any(x["text"]=="PT-101" and x["class"]=="INSTRUMENT" for x in result["objects"])
    assert any(x["text"]=="XV-201" and x["class"]=="VALVE_ONOFF" for x in result["objects"])
    assert any(x["class"]=="LINE" for x in result["objects"])
    assert all(x["status"]=="UNVERIFIED" for x in result["objects"])
    assert any(x["direction"]=="UNKNOWN" for x in result["connections"])
    assert check_extraction.check(result)==[]
    assert check_extraction.schema_check(result,SCHEMA)==[]


def test_deterministic_content(synthetic_pdf):
    a=read_pid(synthetic_pdf,ReadParams())
    b=read_pid(synthetic_pdf,ReadParams())
    assert a["provenance"]["result_sha256"]==b["provenance"]["result_sha256"]
    assert result_sha256(a)==a["provenance"]["result_sha256"]
    assert a["objects"]==b["objects"]


def test_refuse_sha_mismatch(synthetic_pdf):
    with pytest.raises(RefusedInput) as e:
        read_pid(synthetic_pdf,ReadParams(),expected_sha256="1"*64)
    assert e.value.code=="PID_SHA_MISMATCH"


def test_refuse_non_pdf():
    with pytest.raises(RefusedInput) as e:
        read_pid(b"not a PDF",ReadParams())
    assert e.value.code=="PID_MALFORMED"


def test_refuse_raised_limits(synthetic_pdf):
    with pytest.raises(RefusedInput):
        read_pid(synthetic_pdf,ReadParams(max_pdf_bytes=20*1024*1024))


def test_refuse_unknown_parameter(synthetic_pdf):
    with pytest.raises(RefusedInput) as e:
        read_pid(synthetic_pdf,ReadParams(extras={"remote":True}))
    assert e.value.code=="PID_UNKNOWN_PARAMETER"


def test_page_selection(synthetic_pdf):
    doc=read_pid(synthetic_pdf,ReadParams(pages=(1,)))
    assert len(doc["pages"])==1
    with pytest.raises(RefusedInput):
        read_pid(synthetic_pdf,ReadParams(pages=(2,)))


def test_raster_refused_but_visible(raster_pdf):
    doc=read_pid(raster_pdf,ReadParams())
    assert doc["pages"][0]["classification"]=="RASTER_ONLY"
    assert doc["pages"][0]["read_status"]=="REFUSED"
    assert len(doc["unreadable_regions"])==1
    assert check_extraction.check(doc)==[]
    assert check_extraction.schema_check(doc,SCHEMA)==[]


def test_encrypted_refused(synthetic_pdf):
    reader=PdfReader(io.BytesIO(synthetic_pdf))
    writer=PdfWriter()
    for pg in reader.pages:writer.add_page(pg)
    writer.encrypt("secret")
    out=io.BytesIO();writer.write(out)
    with pytest.raises(RefusedInput) as e:
        read_pid(out.getvalue(),ReadParams())
    assert e.value.code=="PID_ENCRYPTED"


def test_cancel(synthetic_pdf):
    from pid_reader.api import CancelToken, Cancelled
    token=CancelToken();token.cancel()
    with pytest.raises(Cancelled):read_pid(synthetic_pdf,ReadParams(),cancel=token)
