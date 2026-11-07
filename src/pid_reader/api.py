"""The in-process library API (PR-B10) and the deterministic helpers every implementation must share (PR-B09, PR-D09).

`canonical_json`, `sha256_hex`, `result_sha256`, `object_id` and friends are REFERENCE implementations: they define the rules. The reading itself (`read_pid`) is what you
develop; it is deliberately not implemented here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from . import SCHEMA_VERSION, __version__

# --- limits fixed by the host (PR-C02); a parameter may only lower them ---------------------------------------------------------------------------------
MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_PAGES = 500
MAX_RENDER_PIXELS = 12_000_000
# --- run fields excluded from the determinism hash (PR-B09) ---------------------------------------------------------------------------------------------
RUN_FIELDS = ("run_id", "started_utc", "finished_utc", "result_sha256")


class RefusedInput(Exception):
    """The input is refused; `code` is one of the manifest's error_codes (for example PID_ENCRYPTED, PID_NO_TEXT_LAYER, PID_SHA_MISMATCH)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class LimitExceeded(RefusedInput):
    pass


class Cancelled(Exception):
    pass


class CancelToken:
    """Checked by the reader at least every few hundred milliseconds; the worker sets it when the host terminates or asks to cancel."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def check(self) -> None:
        if self._cancelled:
            raise Cancelled()


@dataclass(frozen=True)
class ReadParams:
    """Unknown parameters are refused (PR-B10). Add fields here, never accept free-form dictionaries silently."""
    pages: tuple[int, ...] | None = None          # None = every page
    bulk_accept_min_confidence: float = 0.90      # items below this can never be bulk-accepted (PR-E04); the host enforces it
    max_pdf_bytes: int = MAX_PDF_BYTES
    max_pages: int = MAX_PAGES
    max_render_pixels: int = MAX_RENDER_PIXELS
    extras: dict = field(default_factory=dict)    # must stay empty; non-empty is refused by `validate_params`

    def validate(self) -> None:
        if self.extras:
            raise RefusedInput("PID_UNKNOWN_PARAMETER", "Unknown parameter(s): " + ", ".join(sorted(self.extras)))
        if self.max_pdf_bytes > MAX_PDF_BYTES or self.max_pages > MAX_PAGES or self.max_render_pixels > MAX_RENDER_PIXELS:
            raise RefusedInput("PID_LIMIT_RAISED", "A parameter may lower a host limit but never raise it.")
        if not 0 <= self.bulk_accept_min_confidence <= 1:
            raise RefusedInput("PID_BAD_PARAMETER", "bulk_accept_min_confidence must be between 0 and 1.")

    def as_dict(self) -> dict:
        return {"pages": list(self.pages) if self.pages is not None else None, "bulk_accept_min_confidence": self.bulk_accept_min_confidence,
                "max_pdf_bytes": self.max_pdf_bytes, "max_pages": self.max_pages, "max_render_pixels": self.max_render_pixels}


# --- reference rules ------------------------------------------------------------------------------------------------------------------------------------
def canonical_json(value: object) -> str:
    """The host's rule (core.canonical_json): sorted keys, compact separators, no ASCII escaping, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def params_sha256(params: ReadParams) -> str:
    return sha256_hex(canonical_json(params.as_dict()).encode("utf-8"))


def result_sha256(extraction: dict) -> str:
    """SHA-256 of the canonical JSON of the extraction with the run fields removed from `provenance`."""
    body = json.loads(canonical_json(extraction))
    for key in RUN_FIELDS:
        body["provenance"].pop(key, None)
    return sha256_hex(canonical_json(body).encode("utf-8"))


def _round_box(bbox: dict) -> list[int]:
    """Boxes are rounded to 1/1000 of the page before hashing so that float noise cannot change an id."""
    return [round(bbox[k] * 1000) for k in ("x0", "y0", "x1", "y1")]


def stable_id(prefix: str, *parts: object) -> str:
    digest = sha256_hex(canonical_json(list(parts)).encode("utf-8"))[:16]
    return f"{prefix}-{digest}"


def object_id(cls: str, page: int, bbox: dict, text: str) -> str:
    return stable_id("obj", cls, page, _round_box(bbox), text)


def connection_id(kind: str, from_id: str, to_id: str, polyline: list[list[float]]) -> str:
    return stable_id("con", kind, from_id, to_id, [[round(x * 1000), round(y * 1000)] for x, y in polyline])


def loop_id(member_ids: list[str]) -> str:
    return stable_id("loop", sorted(member_ids))


def shared_id(kind: str, object_ids: list[str]) -> str:
    return stable_id("shr", kind, sorted(object_ids))


# --- what you develop -----------------------------------------------------------------------------------------------------------------------------------
def read_pid(pdf_bytes: bytes, params: ReadParams, cancel: CancelToken | None = None, *, document_revision_id: str = "", filename: str = "", expected_sha256: str = "") -> dict:
    """Extract native PDF text and straight vector strokes as UNVERIFIED proposals.

    This development slice does not offer OCR, symbol classification from graphics,
    proven equipment connections, SIL, IPL, or an assessment of the facility.
    """
    import platform
    from collections import Counter
    from datetime import datetime, timezone
    from uuid import uuid4
    from .formats.pdf_source import extract_pdf

    if not isinstance(params, ReadParams):
        raise RefusedInput("PID_BAD_PARAMETER", "Parameters must use the ReadParams contract.")
    params.validate()
    if cancel:
        cancel.check()
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise RefusedInput("PID_MALFORMED", "Input is not a PDF document.")
    digest = sha256_hex(pdf_bytes)
    if expected_sha256 and digest != expected_sha256:
        raise RefusedInput("PID_SHA_MISMATCH", "Document SHA-256 differs from the supplied source reference.")
    if len(pdf_bytes) > params.max_pdf_bytes:
        raise LimitExceeded("PID_LIMIT_BYTES", "PDF exceeds the configured input size budget.")
    if not document_revision_id:
        document_revision_id = "source-" + digest[:16]
    if not filename:
        filename = "source.pdf"
    if len(filename) > 240:
        raise RefusedInput("PID_BAD_PARAMETER", "Filename exceeds the supported length.")
    parsed = extract_pdf(pdf_bytes, pages=params.pages, max_pages=params.max_pages, cancel=cancel)
    if cancel:
        cancel.check()
    now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    counts = dict(sorted(Counter(x["class"] for x in parsed["objects"]).items()))
    result = {
        "schema_version": SCHEMA_VERSION,
        "provenance": {
            "module_name": "pid_reader", "module_version": __version__, "schema_version": SCHEMA_VERSION,
            "params": params.as_dict(), "params_sha256": params_sha256(params), "input_sha256": digest,
            "models": [], "run_id": str(uuid4()), "started_utc": now(), "finished_utc": now(),
            "host": {"os": platform.system(), "python": platform.python_version()},
            "limitations_text": (
                "Development reading of native PDF text and straight vector strokes only. "
                "No packaged OCR for scanned pages; geometric symbols, instruments without printed tags, "
                "curves, crossings, plant state, off-page continuity and functional safety are not determined. "
                "Line-to-line endpoint proposals are not confirmation of process connectivity."
            ),
            "reader_confidence_note": "Reader confidence is an uncalibrated heuristic, not extraction accuracy or plant certainty.",
            "result_sha256": "0" * 64,
        },
        "document": {"document_revision_id": document_revision_id, "sha256": digest,
                     "filename": filename, "page_count": parsed["page_count"]},
        "pages": parsed["pages"], "objects": parsed["objects"], "connections": parsed["connections"],
        "loop_proposals": parsed["loop_proposals"], "shared_component_evidence": parsed["shared_component_evidence"],
        "unreadable_regions": parsed["unreadable_regions"], "warnings": parsed["warnings"],
        "summary": {"counts_by_class": counts, "object_count": len(parsed["objects"]),
                    "connection_count": len(parsed["connections"]), "duplicate_tags": [],
                    "tags_without_object": 0, "objects_without_tag": 0, "dangling_connections": 0},
    }
    result["provenance"]["result_sha256"] = result_sha256(result)
    if len(canonical_json(result).encode("utf-8")) > 8 * 1024 * 1024:
        raise LimitExceeded("PID_LIMIT_RESULT", "Output exceeds the host result size budget.")
    return result


def schema_version() -> int:
    return SCHEMA_VERSION


def module_version() -> str:
    return __version__
