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


_FUNCTION_FIRST = "PFTLAZHSWJX"
_FUNCTION_REST = set("ITCRYSHLAEDQZVKXMOGFPBWNUJ")
_NOT_FUNCTIONS = {"HOLD", "VENT", "NEW", "LINE", "NPS", "PLC", "SCADA", "CELL", "TITLE", "SIZE", "MAKE", "MODEL",
                  "FAIL", "NOTE", "REV", "DATE", "SET", "POINT", "TBD", "ABOVE", "BELOW", "GROUND", "EXISTING"}
SPARSE_WORDS = 120          # a vector sheet with fewer text words than this ...
SPARSE_GRAPHICS = 800       # ... but this many strokes/curves probably has its lettering drawn as outlines


def _sparse_vector_pages(pdf_bytes: bytes, pages: list[int]) -> list[int]:
    """Pages that read as text-poor but graphics-rich: CAD plots whose tags are outlined, not text."""
    import pdfplumber
    from io import BytesIO
    found = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for number in pages:
                page = pdf.pages[number - 1]
                graphics = len(page.lines) + len(page.curves) + len(page.rects)
                if graphics >= SPARSE_GRAPHICS and len(page.extract_words()) < SPARSE_WORDS:
                    found.append(number)
    except Exception:
        return []
    return found


def _stacked_instrument_tags(words: list[dict]) -> list[dict]:
    """Join instrument-bubble text written on two lines (``PIT`` above ``100``) into ``PIT-100``.

    Pure geometry on OCR word boxes: a function-letter word with a 2-4 digit number directly below
    it (centres aligned, gap under about one text height). Each number is used once. Proposals only.
    """
    import re
    funcs = [w for w in words if re.fullmatch(r"[A-Z]{2,5}", w["text"]) and w["text"] not in _NOT_FUNCTIONS
             and w["text"][0] in _FUNCTION_FIRST and set(w["text"][1:]) <= _FUNCTION_REST]
    nums = [w for w in words if re.fullmatch(r"\d{2,4}[A-Z]?", w["text"])]
    used: set[str] = set()
    out = []
    for f in sorted(funcs, key=lambda w: (w["bbox"]["y0"], w["bbox"]["x0"])):
        fb = f["bbox"]
        fh, fw = fb["y1"] - fb["y0"], fb["x1"] - fb["x0"]
        fcx = (fb["x0"] + fb["x1"]) / 2
        best = None
        for n in nums:
            if n["id"] in used:
                continue
            nb = n["bbox"]
            ncx = (nb["x0"] + nb["x1"]) / 2
            gap = nb["y0"] - fb["y1"]
            below = (nb["y0"] + nb["y1"]) / 2 > (fb["y0"] + fb["y1"]) / 2   # OCR line boxes of stacked text overlap
            if abs(ncx - fcx) <= 0.7 * max(fw, nb["x1"] - nb["x0"]) and below and -1.0 * fh <= gap <= 1.3 * fh:
                key = (-len(n["text"]), round(abs(gap), 4))   # longest text first: drops OCR fragments such as "00" of "100"
                if best is None or key < best[0]:
                    best = (key, n)
        if best:
            n = best[1]
            used.add(n["id"])
            nb = n["bbox"]
            out.append({"text": f"{f['text']}-{n['text']}", "func": f["text"], "num": n["text"],
                        "bbox": {"x0": min(fb["x0"], nb["x0"]), "y0": min(fb["y0"], nb["y0"]),
                                 "x1": max(fb["x1"], nb["x1"]), "y1": max(fb["y1"], nb["y1"])},
                        "score": min(f["raw_ocr_score"], n["raw_ocr_score"]), "ids": f"{f['id']}+{n['id']}"})
    return out


BUBBLE_AREA = (1.2e-4, 3.0e-3)     # normalised page area of a plausible instrument bubble


def _valid_function(text: str) -> bool:
    return (2 <= len(text) <= 5 and text.isalpha() and text.isupper() and text not in _NOT_FUNCTIONS
            and text[0] in _FUNCTION_FIRST and set(text[1:]) <= _FUNCTION_REST)


def _tag_from_bubble_lines(texts: list[str]) -> tuple[str, str, str] | None:
    """(function letters, number, tag) from the text lines read inside one bubble, or None."""
    import re
    lines = [t.strip().upper() for t in texts if t.strip()]
    for t in lines:
        m = re.fullmatch(r"([A-Z]{2,5})[\s-]?(\d{2,4}[A-Z]?)", t)
        if m and _valid_function(m.group(1)):
            return m.group(1), m.group(2), f"{m.group(1)}-{m.group(2)}"
    for i, t in enumerate(lines[:-1]):
        n = lines[i + 1]
        if _valid_function(t) and re.fullmatch(r"\d{2,4}[A-Z]?", n):
            return t, n, f"{t}-{n}"
    return None


def _bubble_pass(pdf_bytes: bytes, page_number: int, existing: list[dict]) -> list[dict]:
    """Re-read each instrument-bubble-sized circle on its own, cropped and magnified.

    Whole-sheet OCR loses small stacked lettering; a tight crop upscaled to a legible size recovers
    many tags. Needs vector geometry (circle outlines), so it applies to text-poor vector sheets only.
    Returns tag proposals ``{text, func, num, bbox, score}``; nothing is accepted automatically.
    """
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image
    from ..formats.ocr_source import _rapid_engine
    from .topology import analyze_pdf_topology
    try:
        geometry = analyze_pdf_topology(pdf_bytes, pages=(page_number,))
    except Exception:
        return []
    bubbles = []
    for shape in geometry["shape_candidates"]:
        b = shape["bbox"]
        area = (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])
        if shape["shape"] == "CLOSED_NEAR_CIRCULAR_OUTLINE" and BUBBLE_AREA[0] <= area <= BUBBLE_AREA[1]:
            bubbles.append(b)
    if not bubbles:
        return []
    page = pdfium.PdfDocument(pdf_bytes)[page_number - 1]
    w, h = page.get_size()
    page_img = page.render(scale=min(6.0, 6500.0 / max(w, h))).to_pil().convert("L")
    iw, ih = page_img.size
    engine = _rapid_engine()
    taken = {o["text"] for o in existing if o["page"] == page_number}
    found = []
    for b in bubbles:
        cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
        if any(o["page"] == page_number and o["class"] == "INSTRUMENT" and
               b["x0"] <= (o["bbox"]["x0"] + o["bbox"]["x1"]) / 2 <= b["x1"] and
               b["y0"] <= (o["bbox"]["y0"] + o["bbox"]["y1"]) / 2 <= b["y1"] for o in existing):
            continue                                       # this bubble is already tagged
        padx, pady = (b["x1"] - b["x0"]) * 0.2, (b["y1"] - b["y0"]) * 0.2
        box = (int((b["x0"] - padx) * iw), int((b["y0"] - pady) * ih), int((b["x1"] + padx) * iw), int((b["y1"] + pady) * ih))
        crop = page_img.crop(box)
        if crop.height < 8 or crop.width < 8:
            continue
        factor = max(1.0, 220.0 / crop.height)
        crop = crop.resize((int(crop.width * factor), int(crop.height * factor)), Image.LANCZOS)
        canvas = Image.new("L", (crop.width + 60, crop.height + 60), 255)
        canvas.paste(crop, (30, 30))
        res, _t = engine(np.asarray(canvas.convert("RGB")))
        lines = sorted(res or [], key=lambda r: min(p[1] for p in r[0]))
        hit = _tag_from_bubble_lines([r[1] for r in lines])
        if not hit or hit[2] in taken:
            continue
        taken.add(hit[2])
        score = min(float(r[2]) for r in lines) if lines else 0.0
        found.append({"text": hit[2], "func": hit[0], "num": hit[1], "bbox": dict(b), "score": score})
    return found


def read_pid_standalone(pdf_bytes: bytes, params: ReadParams, cancel: CancelToken | None = None, *,
                        document_revision_id: str = "", filename: str = "", expected_sha256: str = "",
                        ocr_engine: str | None = "auto") -> dict:
    """``read_pid`` plus OCR of image-only pages (``ocr_engine=None`` disables OCR)."""
    base = read_pid(pdf_bytes, params, cancel, document_revision_id=document_revision_id,
                    filename=filename, expected_sha256=expected_sha256)
    refused = [p["page"] for p in base["pages"] if p["classification"] == "RASTER_ONLY" and p["read_status"] == "REFUSED"]
    if ocr_engine is None:
        return base
    readable = [p["page"] for p in base["pages"] if p["read_status"] == "READ"]
    sparse = _sparse_vector_pages(pdf_bytes, readable) if readable else []
    if not refused and not sparse:
        return base
    from ..formats.ocr_source import ocr_pdf_preview, available_engines
    from ..formats.pdf_source import _parse_tag, _make_obj
    if ocr_engine == "auto" and not available_engines():
        return base  # visible refusal stays; the UI explains that no OCR engine is installed
    ocr = ocr_pdf_preview(pdf_bytes, pages=tuple(sorted(set(refused) | set(sparse))), engine=ocr_engine)
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
            if rec["page"] == number and number in refused:
                rec["read_status"] = "READ"
                rec.pop("refusal_code", None)
                rec["reason"] = (f"Image-only page read with offline OCR ({engine_name}); text positions and "
                                 "characters are unverified proposals.")
        count = 0
        native_texts = {o["text"] for o in base["objects"] if o["page"] == number and o["text"]}
        for st in _stacked_instrument_tags(page_entry["words"]):
            if st["text"] in native_texts:
                continue
            letters = st["func"]
            parsed = {"parse_status": "PARTIAL", "normalised_tag": st["text"], "measured_variable": letters[0],
                      "function_letters": letters[1:], "loop_number": st["num"], "suffix": ""}
            obj = _make_obj("INSTRUMENT", number, dict(st["bbox"]), st["text"], parsed,
                            round(min(0.45, max(0.05, st["score"])), 3),
                            {"source": "OCR", "ocr_engine": engine_name, "stacked_tag": "true", "ocr_word_ids": st["ids"],
                             "raw_ocr_score": f"{st['score']:.4f}"})
            if obj["id"] not in seen:
                seen.add(obj["id"])
                result["objects"].append(obj)
                count += 1
        if engine_name == "rapidocr" and number in sparse and number not in refused:
            for bt in _bubble_pass(pdf_bytes, number, result["objects"]):
                letters = bt["func"]
                parsed = {"parse_status": "PARTIAL", "normalised_tag": bt["text"], "measured_variable": letters[0],
                          "function_letters": letters[1:], "loop_number": bt["num"], "suffix": ""}
                obj = _make_obj("INSTRUMENT", number, dict(bt["bbox"]), bt["text"], parsed,
                                round(min(0.45, max(0.05, bt["score"])), 3),
                                {"source": "OCR", "ocr_engine": engine_name, "bubble_crop": "true",
                                 "raw_ocr_score": f"{bt['score']:.4f}"})
                if obj["id"] not in seen:
                    seen.add(obj["id"])
                    result["objects"].append(obj)
                    count += 1
        for word in page_entry["words"]:
            cls, parsed, conf = _parse_tag(word["text"])
            if cls == "NOTE" or word["text"] in native_texts:
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
                                   "message": (f"Page read by offline OCR ({count} tag-like items). OCR accuracy is not calibrated; "
                                               "symbols and linework of scanned pages are not interpreted.") if number in refused else
                                              (f"Text layer is sparse but the sheet has many vector shapes (lettering is probably outlined), "
                                               f"so the page was also read with offline OCR ({count} added tag-like items, unverified).")})
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
