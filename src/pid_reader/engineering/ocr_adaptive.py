"""Adaptive OCR re-read (Rev X, WPU-03). Bounded, deterministic, local only.

The standard pass (``ocr_pdf_preview``) stays the source of truth. When a page that needs OCR yields nothing (or very little),
this module re-reads it with documented variants -- other page orientations, local contrast enhancement, a higher render scale --
and *adds* the new words beside the old ones. Nothing is overwritten or upgraded:

* every added word keeps its raw engine score and carries ``variant`` provenance;
* a word that overlaps an existing word but reads differently is kept as an alternative (``alternative_of``);
* character-confusion alternatives (0/O, 1/I/l, 5/S, 8/B) are listed on the word and never change its text or score.

Presets (CPU budget, development defaults):  ``quick`` no retry; ``standard`` one contrast retry plus the two sideways
orientations only for pages with *zero* words; ``deep`` adds 180 degrees, a 1.5x scale and low-yield pages.
"""
from __future__ import annotations

from hashlib import sha256
from math import ceil

from ..api import canonical_json, sha256_hex, stable_id

PRESETS = {
    "quick": {"zero_variants": (), "low_variants": (), "low_yield_words": 0},
    "standard": {"zero_variants": ("contrast", "rot90", "rot270"), "low_variants": (), "low_yield_words": 0},
    "deep": {"zero_variants": ("contrast", "rot90", "rot270", "rot180", "scale15"),
             "low_variants": ("contrast", "scale15"), "low_yield_words": 15},
}
VARIANTS = {
    "contrast": {"rotation": 0, "enhance": True, "scale": 1.0},
    "rot90": {"rotation": 90, "enhance": False, "scale": 1.0},
    "rot180": {"rotation": 180, "enhance": False, "scale": 1.0},
    "rot270": {"rotation": 270, "enhance": False, "scale": 1.0},
    "scale15": {"rotation": 0, "enhance": True, "scale": 1.5},
}
_CONFUSIONS = {"0": "O", "O": "0", "1": "I", "I": "1", "l": "1", "5": "S", "S": "5", "8": "B", "B": "8"}


def confusion_alternatives(text: str, limit: int = 4) -> list[str]:
    """Plausible re-readings of ambiguous characters. Provenance only: never replaces the raw text."""
    alts: list[str] = []
    to_digit = {"O": "0", "I": "1", "l": "1", "S": "5", "B": "8"}
    to_alpha = {"0": "O", "1": "I", "5": "S", "8": "B"}
    segments = []
    for seg in __import__("re").split(r"([^A-Za-z0-9]+)", text):
        letters = sum(c.isalpha() for c in seg)
        digits = sum(c.isdigit() for c in seg)
        if seg and letters and all(c.isdigit() or c in to_digit for c in seg) and (digits >= letters or all(
                c in to_digit or c in to_alpha for c in seg)):
            seg = "".join(to_digit.get(c, c) for c in seg)
        elif seg and letters > digits and digits and all(c.isalpha() or c in to_alpha for c in seg):
            seg = "".join(to_alpha.get(c, c) for c in seg)
        segments.append(seg)
    whole = "".join(segments)
    if whole != text:
        alts.append(whole)
    for i, ch in enumerate(text):
        sub = _CONFUSIONS.get(ch)
        if sub is None:
            continue
        # only swap a digit-like char among digits or a letter-like char among letters, i.e. where context disagrees
        left = text[i - 1] if i else ""
        right = text[i + 1] if i + 1 < len(text) else ""
        neighbours = [c for c in (left, right) if c.isalnum()]
        if not neighbours:
            continue
        digit_ctx = all(c.isdigit() for c in neighbours)
        alpha_ctx = all(c.isalpha() for c in neighbours)
        if (ch.isalpha() and digit_ctx and sub.isdigit()) or (ch.isdigit() and alpha_ctx and sub.isalpha()):
            alt = text[:i] + sub + text[i + 1:]
            if alt != text and alt not in alts:
                alts.append(alt)
        if len(alts) >= limit:
            break
    return alts


def map_rotated_box(box: dict, rotation: int) -> dict:
    """Map a normalised box found in an image rotated counter-clockwise by ``rotation`` back to the unrotated page."""
    def pt(u, v):
        if rotation == 0:
            return u, v
        if rotation == 90:      # new_u = v, new_v = 1-u
            return 1 - v, u
        if rotation == 180:
            return 1 - u, 1 - v
        if rotation == 270:     # new_u = 1-v, new_v = u
            return v, 1 - u
        raise ValueError("rotation must be 0, 90, 180 or 270")
    a, b = pt(box["x0"], box["y0"]), pt(box["x1"], box["y1"])
    return {"x0": round(max(0.0, min(a[0], b[0])), 7), "y0": round(max(0.0, min(a[1], b[1])), 7),
            "x1": round(min(1.0, max(a[0], b[0])), 7), "y1": round(min(1.0, max(a[1], b[1])), 7)}


def _iou(a: dict, b: dict) -> float:
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    union = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / union if union > 0 else 0.0


def _enhance(image):
    """Local contrast stretch with a light unsharp mask; keeps thin strokes, dots and minus signs."""
    from PIL import ImageFilter, ImageOps
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    return gray.filter(ImageFilter.UnsharpMask(radius=1.2, percent=80, threshold=2)).convert("RGB")


def read_variant(pdf_bytes: bytes, page_number: int, engine: str, variant: str, *, max_pixels: int = 12_000_000,
                 timeout_seconds: int = 30) -> list[dict]:
    """Re-read one page with one variant. Returns word dicts in the frozen media frame, never persisted here."""
    import pdfplumber
    import pypdfium2 as pdfium
    from io import BytesIO
    from ..formats import ocr_source
    from ..formats.page_coordinates import frame_from_pdfplumber
    spec = VARIANTS[variant]
    document_sha = sha256(pdf_bytes).hexdigest()
    page = pdfium.PdfDocument(pdf_bytes)[page_number - 1]
    width, height = page.get_size()
    with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
        frame = frame_from_pdfplumber(doc.pages[page_number - 1])
    base = 200.0 / 72.0
    scale = base * spec["scale"]
    if ceil(width * scale) * ceil(height * scale) > max_pixels:
        scale *= (max_pixels / (ceil(width * scale) * ceil(height * scale))) ** 0.5 * 0.97
    image = page.render(scale=scale).to_pil().convert("RGB")
    if spec["enhance"]:
        image = _enhance(image)
    if spec["rotation"]:
        image = image.rotate(spec["rotation"], expand=True)
    raw = ocr_source._rapid_words(image) if engine == "rapidocr" else ocr_source._tesseract_words(image, timeout_seconds)
    words = []
    for text, conf, left, top, wid, hei, split in raw:
        if wid < 1 or hei < 1:
            continue
        box = {"x0": max(0, left / image.width), "y0": max(0, top / image.height),
               "x1": min(1, (left + wid) / image.width), "y1": min(1, (top + hei) / image.height)}
        if box["x0"] >= box["x1"] or box["y0"] >= box["y1"]:
            continue
        box = map_rotated_box(box, spec["rotation"])
        if box["x0"] >= box["x1"] or box["y0"] >= box["y1"]:
            continue
        box = frame.bbox_to_media({k: round(v, 7) for k, v in box.items()})
        w = {"id": stable_id("ocr", document_sha, page_number, box, text), "text": text, "page": page_number, "bbox": box,
             "raw_ocr_score": round(max(0.0, min(1.0, conf)), 4), "review_state": "PROPOSED",
             "engine": "local_rapidocr" if engine == "rapidocr" else "local_tesseract", "variant": variant}
        if split:
            w["split"] = "PROPORTIONAL_FROM_LINE"
        words.append(w)
    return words


def augment_ocr(pdf_bytes: bytes, ocr: dict, page_analysis: list[dict], *, preset: str = "standard", ink_pages: set[int] | None = None,
                cancel=None) -> tuple[dict, list[dict]]:
    """Return ``(ocr_result_with_added_words, trace)``. The input result is not modified."""
    if preset not in PRESETS:
        raise ValueError(f"Unknown OCR preset {preset!r}")
    policy = PRESETS[preset]
    engine = "rapidocr" if str(ocr.get("algorithm", "")).startswith("rapidocr") else "tesseract"
    ink_pages = ink_pages or set()
    by_page = {p["page"]: p for p in page_analysis}
    new = {"pages": [dict(p, words=list(p["words"])) for p in ocr["pages"]]}
    trace: list[dict] = []
    for entry in new["pages"]:
        pg = by_page.get(entry["page"])
        if pg is None or not pg["ocr_policy"]["ocr_required"]:
            continue
        n_words = len(entry["words"])
        ink = entry["page"] in ink_pages or pg["counts"]["graphics_count"] > 0 or pg["counts"]["image_count"] > 0
        if n_words == 0 and ink:
            trigger, variants = "ZERO_WORDS_WITH_INK", policy["zero_variants"]
        elif n_words < policy["low_yield_words"] and ink:
            trigger, variants = "LOW_YIELD", policy["low_variants"]
        else:
            continue
        for name in variants:
            if cancel is not None:
                cancel.check()
            record = {"page": entry["page"], "variant": name, "trigger": trigger, "words_found": 0, "words_added": 0,
                      "alternatives": 0, "error": ""}
            try:
                found = read_variant(pdf_bytes, entry["page"], engine, name)
            except Exception as exc:  # noqa: BLE001 - one failed variant must not end the drawing
                record["error"] = f"{type(exc).__name__}: {exc}"[:200]
                trace.append(record)
                continue
            record["words_found"] = len(found)
            known = {w["id"] for w in entry["words"]}
            for w in found:
                if w["id"] in known:
                    continue
                for old in entry["words"]:
                    if old["text"] != w["text"] and _iou(old["bbox"], w["bbox"]) > 0.5:
                        w["alternative_of"] = old["id"]
                        record["alternatives"] += 1
                        break
                alts = confusion_alternatives(w["text"])
                if alts:
                    w["confusion_alternatives"] = alts
                entry["words"].append(w)
                known.add(w["id"])
                record["words_added"] += 1
            trace.append(record)
            if len(entry["words"]) > 0 and trigger == "ZERO_WORDS_WITH_INK" and record["words_added"] > 0 and name == "contrast":
                continue  # contrast already recovered text; remaining orientations still tried, they are cheap and bounded
    if not any(t["words_added"] for t in trace):
        return ocr, trace                      # nothing recovered: keep the original result (and its hash) untouched
    result = dict(ocr)
    result.pop("result_sha256", None)
    result["pages"] = [dict(p, words=sorted(p["words"], key=lambda w: (w["bbox"]["y0"], w["bbox"]["x0"], w["id"]))) for p in new["pages"]]
    result["adaptive"] = {"preset": preset, "attempts": len(trace), "words_added": sum(t["words_added"] for t in trace),
                          "version": "ocr-adaptive-v1"}
    result["result_sha256"] = sha256_hex(canonical_json(result).encode("utf-8"))
    return result, trace
