"""PDF page provenance and the unverified-scale guard (R5 update, change 3).

For every page this records, as plain serialisable data, the raw ``MediaBox``, ``CropBox``, ``/Rotate`` and ``/UserUnit`` and says what they
mean for measurements:

* Nothing here rescales drawing geometry. Normalised coordinates, the existing ``PageFrame`` (CropBox/rotation mapping) and every stored
  reading stay exactly as they were; this module only *adds* provenance next to them.
* ``physical_measurements_allowed`` is **always False**. A PDF point is 1/72 inch only when ``/UserUnit`` is 1, and even then the
  drawing's own scale (1:50, "NOT TO SCALE") is not known. A non-1 ``UserUnit`` is flagged ``USERUNIT_SCALE_UNVERIFIED`` and is never
  multiplied in: R5 measured up to about 1.7 pt of inverse-mapping error at large UserUnit, so a corrected physical dimension is not offered.
* Invalid or non-finite values are flagged (``INVALID_USERUNIT``, ``INVALID_ROTATION``, ``INVALID_PAGE_BOX``) and the page becomes
  ``UNRESOLVED``; the value 1 is never silently substituted.

:func:`measurement_guard` is what any code that wants to turn page units into a length must call; it returns a refusal with a short,
user-facing explanation.
"""
from __future__ import annotations

import math
from pathlib import Path

VERSION = "page-provenance-v1"
MAX_PAGES = 5000
FLAG_USERUNIT = "USERUNIT_SCALE_UNVERIFIED"
FLAG_SCALE = "DRAWING_SCALE_UNVERIFIED"


def _finite_box(raw) -> list[float] | None:
    try:
        box = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if len(box) != 4 or not all(math.isfinite(v) for v in box):
        return None
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return None
    return box


def frame_provenance(page: int, metadata: dict) -> dict:
    """Provenance record for one page from explicit metadata (``MediaBox``, ``CropBox``, ``Rotate``, ``UserUnit``)."""
    flags: list[str] = []
    media = _finite_box(metadata.get("MediaBox"))
    crop_raw = metadata.get("CropBox", metadata.get("MediaBox"))
    crop = _finite_box(crop_raw)
    if media is None or crop is None:
        flags.append("INVALID_PAGE_BOX")
    elif crop[0] < media[0] - 0.001 or crop[1] < media[1] - 0.001 or crop[2] > media[2] + 0.001 or crop[3] > media[3] + 0.001:
        flags.append("CROPBOX_OUTSIDE_MEDIABOX")
    rot_raw = metadata.get("Rotate", 0)
    rotation = None
    if isinstance(rot_raw, bool) or not isinstance(rot_raw, (int, float)) or not math.isfinite(rot_raw) or rot_raw != int(rot_raw) or int(rot_raw) % 90:
        flags.append("INVALID_ROTATION")
    else:
        rotation = int(rot_raw) % 360
    uu_raw = metadata.get("UserUnit", 1)
    user_unit = None
    if isinstance(uu_raw, bool) or not isinstance(uu_raw, (int, float)) or not math.isfinite(uu_raw) or uu_raw <= 0:
        flags.append("INVALID_USERUNIT")
    else:
        user_unit = float(uu_raw)
        flags.append(FLAG_USERUNIT if user_unit != 1.0 else FLAG_SCALE)
    unresolved = any(f.startswith("INVALID_") or f == "CROPBOX_OUTSIDE_MEDIABOX" for f in flags)
    return {"page": int(page), "status": "UNRESOLVED" if unresolved else "PROPOSED_UNVERIFIED", "flags": flags,
            "media_box": media, "crop_box": crop, "rotation": rotation, "user_unit": user_unit,
            "raw": {k: _raw(metadata.get(k)) for k in ("MediaBox", "CropBox", "Rotate", "UserUnit") if k in metadata},
            "geometry_rescaled": False, "physical_measurements_allowed": False,
            "reason": ("page metadata is invalid; no measurement or overlay claim is made for this page" if unresolved else
                       "the PDF unit and the drawing scale are both unverified; positions stay normalised and nothing is converted to a length")}


def _raw(v):
    if isinstance(v, (list, tuple)):
        return [_raw(x) for x in v]
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return repr(v)[:80]


def read_pdf_provenance(path_or_bytes) -> dict:
    """Provenance of every page of a PDF given as a path or as bytes (read-only; pypdf, already a locked dependency).
    Never raises for a bad file: it reports it."""
    out = {"schema": "pid-reader-page-provenance-v1", "version": VERSION, "pages": [], "status": "OK", "error": None}
    try:
        from pypdf import PdfReader
        if isinstance(path_or_bytes, (bytes, bytearray)):
            from io import BytesIO
            reader = PdfReader(BytesIO(bytes(path_or_bytes)), strict=False)
        else:
            reader = PdfReader(str(path_or_bytes), strict=False)
        n = len(reader.pages)
        if n > MAX_PAGES:
            out.update(status="REFUSED", error=f"PAGE_COUNT_OVER_LIMIT({n}>{MAX_PAGES})")
            return out
        for i, p in enumerate(reader.pages):
            try:
                md = {"MediaBox": [float(v) for v in p.mediabox], "CropBox": [float(v) for v in p.cropbox],
                      "Rotate": _num(p.get("/Rotate", 0)), "UserUnit": _num(p.get("/UserUnit", 1))}
            except Exception as ex:                       # one corrupt page does not hide the others
                out["pages"].append({"page": i + 1, "status": "UNRESOLVED", "flags": ["INVALID_PAGE_BOX"], "reason": f"unreadable page metadata ({type(ex).__name__})",
                                     "geometry_rescaled": False, "physical_measurements_allowed": False})
                continue
            out["pages"].append(frame_provenance(i + 1, md))
    except Exception as ex:
        out.update(status="UNREADABLE", error=type(ex).__name__ + ": " + str(ex)[:160], pages=[])
    return out


def _num(v):
    try:
        v = v.get_object() if hasattr(v, "get_object") else v
        return v if isinstance(v, bool) else (float(v) if not isinstance(v, int) else int(v))
    except Exception:
        return None if v is None else repr(v)[:40]


def measurement_guard(prov: dict | None) -> dict:
    """Decision for a request to turn page units into a physical length. Always a refusal today; says why in one sentence."""
    if not prov:
        return {"allowed": False, "code": "NO_PAGE_PROVENANCE", "message": "No page metadata is recorded, so no length can be given."}
    flags = prov.get("flags", [])
    if any(f.startswith("INVALID_") or f == "CROPBOX_OUTSIDE_MEDIABOX" for f in flags):
        return {"allowed": False, "code": "PAGE_METADATA_INVALID", "message": "The PDF page metadata is invalid, so no length can be given for this page."}
    if FLAG_USERUNIT in flags:
        return {"allowed": False, "code": FLAG_USERUNIT,
                "message": f"This page declares /UserUnit {prov.get('user_unit')}; its physical scale is not verified, so lengths are not shown."}
    return {"allowed": False, "code": FLAG_SCALE, "message": "The drawing scale is not verified, so lengths are not shown (positions are drawing-relative only)."}


def crosscheck_live_frame(path: str | Path) -> list[dict]:
    """Compare this module's CropBox/rotation reading with the live ``PageFrame`` (pdfplumber). Evidence that the two agree, per page."""
    import pdfplumber
    from .page_coordinates import frame_from_pdfplumber
    prov = read_pdf_provenance(path)["pages"]
    rows = []
    with pdfplumber.open(str(path)) as pdf:
        for p, pr in zip(pdf.pages, prov):
            try:
                f = frame_from_pdfplumber(p)
                ok = pr.get("rotation") == f.rotation
                crop = pr.get("crop_box")
                rows.append({"page": pr["page"], "live_rotation": f.rotation, "provenance_rotation": pr.get("rotation"),
                             "live_render_size": [round(f.crop_width, 3), round(f.crop_height, 3)],
                             "provenance_crop_size": [round(crop[2] - crop[0], 3), round(crop[3] - crop[1], 3)] if crop else None, "rotation_agrees": ok})
            except Exception as ex:
                rows.append({"page": pr["page"], "error": type(ex).__name__ + ": " + str(ex)[:120]})
    return rows
