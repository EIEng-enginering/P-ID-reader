from __future__ import annotations
import shutil
import pytest

@pytest.mark.skipif(not shutil.which("tesseract"),reason="Optional local Tesseract not installed")
def test_raster_ocr_preview_is_separate_from_host(raster_pdf):
    from pid_reader.formats.ocr_source import ocr_pdf_preview
    result=ocr_pdf_preview(raster_pdf)
    assert result["adapter"]=="standalone_ocr_preview_v3"
    assert len(result["pages"])==1
    assert all(x["review_state"]=="PROPOSED" for x in result["pages"][0]["words"])
    from pid_reader.formats.ocr_source import verify_ocr_preview
    assert verify_ocr_preview(result)
    assert result["source_sha256"]
    assert all("id" in x and "bbox" in x for x in result["pages"][0]["words"])
    assert all(x["review_state"]=="PROPOSED" for x in result["pages"][0]["words"])


@pytest.mark.skipif(not shutil.which("tesseract"),reason="Optional local Tesseract not installed")
def test_standalone_ocr_rejects_reused_page_numbers(raster_pdf):
    from pid_reader.formats.ocr_source import ocr_pdf_preview
    with pytest.raises(ValueError,match="Unique"):
        ocr_pdf_preview(raster_pdf,pages=(1,1))
    with pytest.raises(ValueError,match="pixel budget"):
        ocr_pdf_preview(raster_pdf,max_pixels=1000)


@pytest.mark.skipif(not shutil.which("tesseract"),reason="Optional local Tesseract not installed")
def test_standalone_ocr_detects_tampered_word(raster_pdf):
    from pid_reader.formats.ocr_source import ocr_pdf_preview,verify_ocr_preview
    r=ocr_pdf_preview(raster_pdf)
    assert verify_ocr_preview(r)
    if r['pages'][0]['words']:
        r['pages'][0]['words'][0]['text']='INVENTED-ATTRIBUTE'
        assert not verify_ocr_preview(r)
