"""Standalone reader: native PDF text *plus* offline OCR for image-only pages.

The frozen Worksheet R1 reader (``pid_reader.api.read_pid``) deliberately refuses
image-only pages. The standalone application must also handle scanned drawings,
so this adapter reuses the same native extractor, and for pages the native
extractor could not read it adds tag/text observations from an offline OCR engine.

Output keeps the exact R1 schema-1 shape (validated by the R1 checker in tests),
but every OCR-derived object carries ``attributes.source == "OCR"``, the engine
and its raw score, and is capped at low confidence. The OCR model files are
listed under ``provenance.models`` with their SHA-256 and licence. This module is
not used by the Worksheet worker; R1 behaviour is unchanged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..api import CancelToken, ReadParams, RefusedInput, canonical_json, read_pid, result_sha256

SCHEMA_VERSION = 1
OCR_CONFIDENCE_CAP = 0.55


def _rapid_models() -> list[dict]:
    try:
        import rapidocr_onnxruntime
    except ImportError:
        return []
    root = Path(rapidocr_onnxruntime.__file__).parent / "models"
    out = []
    for path in sorted(root.glob("*.onnx")) if root.is_dir() else []:
        out.append({"id": f"rapidocr-onnxruntime/{path.name}", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "licence": "Apache-2.0"})
    return out


def read_pid_standalone(pdf_bytes: bytes, params: ReadParams, cancel: CancelToken | None = None, *,
                        document_revision_id: str = "", filename: str = "", expected_sha256: str = "",
                        ocr_engine: str | None = "auto") -> dict:
    """``read_pid`` plus OCR of image-only pages (``ocr_engine=None`` disables OCR)."""
    base = read_pid(pdf_bytes, params, cancel, document_revision_id=document_revision_id,
                    filename=filename, expected_sha256=expected_sha256)
    refused = [p["page"] for p in base["pages"] if p["classification"] == "RASTER_ONLY" and p["read_status"] == "REFUSED"]
    if not refused or ocr_engine is None:
        return base
    from ..formats.ocr_source import ocr_pdf_preview, available_engines
    from ..formats.pdf_source import _parse_tag, _make_obj
    if ocr_engine == "auto" and not available_engines():
        return base  # visible refusal stays; the UI explains that no OCR engine is installed
    ocr = ocr_pdf_preview(pdf_bytes, pages=tuple(refused), engine=ocr_engine)
    if cancel:
        cancel.check()
    result = dict(base)
    result["pages"] = [dict(p) for p in base["pages"]]
    result["objects"] = list(base["objects"])
    result["warnings"] = [w for w in base["warnings"] if not (w.get("code") == "NO_TEXT_LAYER" and w.get("page") in refused)]
    result["unreadable_regions"] = [r for r in base["unreadable_regions"]
                                    if not (r.get("code") == "PAGE_NOT_READ" and r.get("page") in refused)]
    seen = {o["id"] for o in result["objects"]}
    engine_name = "rapidocr" if ocr["algorithm"].startswith("rapidocr") else "tesseract"
    for page_entry in ocr["pages"]:
        number = page_entry["page"]
        for rec in result["pages"]:
            if rec["page"] == number:
                rec["read_status"] = "READ"
                rec.pop("refusal_code", None)
                rec["reason"] = (f"Image-only page read with offline OCR ({engine_name}); text positions and "
                                 "characters are unverified proposals.")
        count = 0
        for word in page_entry["words"]:
            cls, parsed, conf = _parse_tag(word["text"])
            if cls == "NOTE":
                continue
            bbox = dict(word["bbox"])
            if not (0 <= bbox["x0"] < bbox["x1"] <= 1 and 0 <= bbox["y0"] < bbox["y1"] <= 1):
                continue
            obj = _make_obj(cls, number, bbox, word["text"], parsed,
                            round(min(conf, OCR_CONFIDENCE_CAP, max(0.05, word["raw_ocr_score"])), 3),
                            {"source": "OCR", "ocr_engine": engine_name, "ocr_word_id": word["id"],
                             "raw_ocr_score": f"{word['raw_ocr_score']:.4f}"})
            if obj["id"] in seen:
                continue
            seen.add(obj["id"])
            result["objects"].append(obj)
            count += 1
        result["warnings"].append({"code": "OTHER", "page": number,
                                   "message": f"Page read by offline OCR ({count} tag-like items). OCR accuracy is not calibrated; "
                                              "symbols and linework of scanned pages are not interpreted."})
    result["objects"].sort(key=lambda x: (x["page"], x["bbox"]["y0"], x["bbox"]["x0"], x["class"], x["id"]))
    prov = dict(base["provenance"])
    prov["models"] = _rapid_models() if engine_name == "rapidocr" else []
    prov["limitations_text"] = (prov["limitations_text"].replace(
        "No packaged OCR for scanned pages; ", "Image-only pages are read by an offline OCR engine as unverified proposals; ")[:4000])
    prov["result_sha256"] = "0" * 64
    result["provenance"] = prov
    from collections import Counter
    counts = dict(sorted(Counter(x["class"] for x in result["objects"]).items()))
    result["summary"] = {**base["summary"], "counts_by_class": counts, "object_count": len(result["objects"])}
    prov["result_sha256"] = result_sha256(result)
    if len(canonical_json(result).encode("utf-8")) > 8 * 1024 * 1024:
        raise RefusedInput("PID_LIMIT_RESULT", "Output exceeds the host result size budget.")
    return result
