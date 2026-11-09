"""Stage telemetry and zero-extraction health (Rev X, WPU-01). Standalone; R1 untouched.

Every pipeline stage produces a ``StageOutcome``. A stage that did not run, failed, or ran and found nothing are different
facts and are never merged into "success". The drawing as a whole gets a ``drawing_status`` from a closed vocabulary:

    COMPLETE_CANDIDATES  every stage the page encoding needs ran and produced candidates (still unreviewed proposals)
    PARTIAL              something ran but was truncated or only partly successful
    INCOMPLETE           a needed stage did not run, failed, or found nothing where ink exists
    FAILED               the drawing could not be analysed at all
    NOT_RUN              no analysis stage ran

None of these is an accuracy statement and none says anything about the plant. "Zero equipment found" is never reported as
complete: it is reported with the reason (``OCR_ENGINE_MISSING``, ``ZERO_WORDS_WITH_INK`` ...).
"""
from __future__ import annotations

import hashlib
import json
import time

STAGE_STATUSES = ("SUCCESS", "PARTIAL", "SKIPPED", "FAILED", "TIMEOUT", "CANCELLED", "NOT_RUN")
DRAWING_STATUSES = ("COMPLETE_CANDIDATES", "PARTIAL", "INCOMPLETE", "FAILED", "NOT_RUN")
TEXT_STATUSES = ("NATIVE_OK", "OCR_OK", "OCR_PARTIAL", "UNREADABLE_OR_FAILED", "NOT_ATTEMPTED", "NOT_REQUIRED")
DIAGNOSTIC_CODES = ("OCR_DISABLED", "OCR_ENGINE_MISSING", "OCR_NOT_RUN", "OCR_FAILED", "OCR_RUNTIME_EXCEPTION",
                    "ZERO_WORDS_WITH_INK", "PARTIAL_TILE_FAILURE", "OCR_WORDS_DROPPED_IN_EXPORT", "TEXT_NOT_FOUND",
                    "GEOMETRY_FAILED", "STAGE_TRUNCATED", "WORKER_LIMIT")
_LEGACY = {"DONE": "SUCCESS", "SKIPPED": "SKIPPED", "FAILED": "FAILED", "NOT_RUN": "NOT_RUN"}
_PARTIAL_WORDS = ("truncat", "cap hit", "partial", "capped")


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def engine_version() -> str:
    try:
        from .. import __version__
        return __version__
    except Exception:  # pragma: no cover - import guard
        return "unknown"


def make_outcome(stage_id: str, status: str, *, source_sha256: str = "", config_sha256: str = "", model_sha256: str = "",
                 stage_version: str = "1", runtime_ms: int = 0, tile_count: int = 0, candidates: int = 0,
                 cap_truncations: int = 0, error_class: str = "", error_summary: str = "", pages_processed: int = 0,
                 regions_processed: int = 0, evidence_count: int = 0, output_sha256: str = "",
                 diagnostics: dict | None = None) -> dict:
    if status not in STAGE_STATUSES:
        raise ValueError(f"Unknown stage status {status!r}")
    if status == "SUCCESS" and cap_truncations:
        status = "PARTIAL"           # a truncating stage can never claim SUCCESS
    return {"stage_id": stage_id, "status": status, "input_source_sha256": source_sha256, "input_model_sha256": model_sha256,
            "config_sha256": config_sha256, "stage_version": stage_version, "runtime_ms": int(runtime_ms),
            "tile_count": int(tile_count), "candidates": int(candidates), "cap_truncations": int(cap_truncations),
            "error_class": error_class, "error_summary": error_summary[:400], "pages_processed": int(pages_processed),
            "regions_processed": int(regions_processed), "observed_content_evidence_count": int(evidence_count),
            "output_sha256": output_sha256, "diagnostics": diagnostics or {}}


class StageRecorder:
    """Collects one StageOutcome per stage, deriving timings and the legacy-to-new status mapping."""

    def __init__(self, source_sha256: str, config: dict):
        self.source_sha256 = source_sha256
        self.config = config
        self.config_sha256 = sha256_json(config)
        self.outcomes: dict[str, dict] = {}
        self._started: dict[str, float] = {}

    def begin(self, stage: str) -> None:
        self._started[stage] = time.perf_counter()

    def end(self, stage: str, legacy_status: str, detail: str = "", **fields) -> dict:
        ms = int((time.perf_counter() - self._started.pop(stage, time.perf_counter())) * 1000)
        status = fields.pop("status", None) or _LEGACY.get(legacy_status, "NOT_RUN")
        if status == "SUCCESS" and any(w in detail.lower() for w in _PARTIAL_WORDS):
            status = "PARTIAL"
        err_class = fields.pop("error_class", "")
        summary = fields.pop("error_summary", "")
        if status == "FAILED" and not summary:
            err_class, _, summary = detail.partition(": ")
        if status in ("SKIPPED", "NOT_RUN") and not summary:
            summary = detail
        outcome = make_outcome(stage, status, source_sha256=self.source_sha256, config_sha256=self.config_sha256,
                               runtime_ms=ms, error_class=err_class, error_summary=summary,
                               diagnostics={"detail": detail, **fields.pop("diagnostics", {})}, **fields)
        self.outcomes[stage] = outcome
        return outcome

    def add(self, outcome: dict) -> None:
        self.outcomes[outcome["stage_id"]] = outcome

    def ordered(self) -> list[dict]:
        return list(self.outcomes.values())


def ocr_diagnostics(*, requested: bool, engine_choice: str, engines_available: list[str], stage_status: str,
                    pages_selected: list[int], counters: dict | None = None, native_words: dict | None = None,
                    ocr_words: dict | None = None, recognized_tags: int = 0, exception: str = "",
                    retry_count: int = 0, truncated: bool = False) -> dict:
    """The OCR health record from the spec (B): what was asked, available, attempted, and what came back."""
    counters = counters or {}
    attempted = stage_status in ("SUCCESS", "PARTIAL", "FAILED")
    engine_ok = bool(engines_available) if engine_choice == "auto" else engine_choice in engines_available
    return {"ocr_requested": bool(requested), "engine_choice": engine_choice, "engine_available": engine_ok,
            "engines_available": list(engines_available), "ocr_attempted": attempted,
            "cropping": bool(counters.get("tiles_attempted", 0) > 1),
            "tiles_attempted": int(counters.get("tiles_attempted", 0)), "tiles_successful": int(counters.get("tiles_successful", 0)),
            "tile_failures": int(counters.get("tile_failures", 0)), "tile_error_classes": list(counters.get("tile_error_classes", [])),
            "exception": exception[:300], "word_count_native": sum((native_words or {}).values()),
            "word_count_ocr": sum((ocr_words or {}).values()), "words_ocr_by_page": dict(ocr_words or {}),
            "recognized_tags": int(recognized_tags), "pages_selected": list(pages_selected), "retry_count": int(retry_count),
            "truncated": bool(truncated)}


def export_consistency(internal_ocr_words: int, exported_ocr_words: int) -> str | None:
    """``OCR_WORDS_DROPPED_IN_EXPORT`` when the pipeline saw OCR words that the exported record does not carry."""
    if internal_ocr_words > 0 and exported_ocr_words < internal_ocr_words:
        return "OCR_WORDS_DROPPED_IN_EXPORT"
    return None


def _center_in(bbox: dict, region: dict) -> bool:
    cx, cy = (bbox["x0"] + bbox["x1"]) / 2, (bbox["y0"] + bbox["y1"]) / 2
    return region["x0"] <= cx <= region["x1"] and region["y0"] <= cy <= region["y1"]


def page_text_status(page: dict, *, ocr_diag: dict, ocr_stage: str, ink: bool, ocr_page_words: int, ocr_error: str = "") -> tuple[str, list[str]]:
    """Text status and diagnostic codes for one page (see module docstring)."""
    policy = page["ocr_policy"]
    native = page["counts"]["word_count"]
    codes: list[str] = []
    if not policy["ocr_required"]:
        return ("NATIVE_OK" if native else "NOT_REQUIRED"), codes
    if page["page"] not in ocr_diag.get("pages_selected", []) or ocr_stage in ("SKIPPED", "NOT_RUN"):
        if not ocr_diag.get("ocr_requested", True):
            codes.append("OCR_DISABLED")
        elif not ocr_diag.get("engine_available", False):
            codes.append("OCR_ENGINE_MISSING")
        else:
            codes.append("OCR_NOT_RUN")
        return "NOT_ATTEMPTED", codes
    if ocr_stage == "FAILED":
        codes.append("OCR_RUNTIME_EXCEPTION" if ocr_diag.get("exception", "").startswith("OCR_RUNTIME_EXCEPTION") else "OCR_FAILED")
        return "UNREADABLE_OR_FAILED", codes
    if ocr_page_words == 0:
        codes.append("ZERO_WORDS_WITH_INK" if ink else "TEXT_NOT_FOUND")
        return ("UNREADABLE_OR_FAILED" if ink else "NOT_REQUIRED"), codes
    if ocr_diag.get("tile_failures", 0):
        codes.append("PARTIAL_TILE_FAILURE")
        return "OCR_PARTIAL", codes
    return "OCR_OK", codes


def evaluate_health(*, page_analysis: list[dict], outcomes: dict[str, dict], ocr_diag: dict,
                    ink_pages: set[int], ocr_words_by_page: dict[int, list[dict]] | None = None,
                    exported_ocr_words: int | None = None, symbol_stage_status: str = "NOT_RUN",
                    graph_nodes: int = 0) -> dict:
    """Drawing status, per-page text status and per-region coverage. Coverage is not accuracy."""
    ocr_words_by_page = ocr_words_by_page or {}
    ocr_outcome = outcomes.get("ocr", {"status": "NOT_RUN"})
    pages, codes_all, coverage = [], [], []
    for pg in page_analysis:
        number = pg["page"]
        ink = number in ink_pages or pg["counts"]["graphics_count"] > 0 or pg["counts"]["image_count"] > 0
        words = ocr_words_by_page.get(number, [])
        status, codes = page_text_status(pg, ocr_diag=ocr_diag, ocr_stage=ocr_outcome["status"], ink=ink,
                                         ocr_page_words=len(words), ocr_error=ocr_outcome.get("error_summary", ""))
        pages.append({"page": number, "classification": pg["classification"], "ink_evidence": ink,
                      "words_native": pg["counts"]["word_count"], "words_ocr": len(words), "text_status": status,
                      "codes": codes, "primary_blocker": codes[0] if codes else ""})
        codes_all += codes
        for reg in pg["regions"]:
            inside = [w for w in words if _center_in(w["bbox"], reg["bbox"])]
            coverage.append({"page": number, "region_id": reg["region_id"], "region": reg["kind"],
                             "texts_attempted": status not in ("NOT_ATTEMPTED", "NOT_REQUIRED") or bool(pg["counts"]["word_count"]),
                             "words": len(inside) if reg["kind"] != "DRAWING_AREA" else len(words),
                             "text_status": status,
                             "symbol_classes_attempted": ["VALVE", "EQUIPMENT", "INSTRUMENT"] if symbol_stage_status in ("SUCCESS", "PARTIAL") else [],
                             "graph_join_status": "CANDIDATES" if graph_nodes else "UNRESOLVED",
                             "primary_blocker": pages[-1]["primary_blocker"]})
    if exported_ocr_words is not None:
        drop = export_consistency(sum(len(v) for v in ocr_words_by_page.values()), exported_ocr_words)
        if drop:
            codes_all.append(drop)
    for sid in ("geometry",):
        if outcomes.get(sid, {}).get("status") == "FAILED":
            codes_all.append("GEOMETRY_FAILED")
    if any(o.get("cap_truncations") for o in outcomes.values()):
        codes_all.append("STAGE_TRUNCATED")
    ran = [o for o in outcomes.values() if o["status"] in ("SUCCESS", "PARTIAL")]
    failed = [o for o in outcomes.values() if o["status"] in ("FAILED", "TIMEOUT")]
    if not outcomes or all(o["status"] in ("NOT_RUN", "SKIPPED") for o in outcomes.values()):
        drawing = "NOT_RUN"
    elif not ran and failed:
        drawing = "FAILED"
    elif any(p["text_status"] in ("UNREADABLE_OR_FAILED", "NOT_ATTEMPTED") and p["ink_evidence"] for p in pages) \
            or "OCR_WORDS_DROPPED_IN_EXPORT" in codes_all or "GEOMETRY_FAILED" in codes_all and not ocr_words_by_page:
        drawing = "INCOMPLETE"
    elif failed or any(o["status"] == "PARTIAL" for o in outcomes.values()) or any(p["text_status"] == "OCR_PARTIAL" for p in pages):
        drawing = "PARTIAL"
    else:
        drawing = "COMPLETE_CANDIDATES"
    codes_all = list(dict.fromkeys(codes_all))
    primary = codes_all[0] if codes_all else ""
    return {"drawing_status": drawing, "codes": codes_all, "primary_blocker": primary, "pages": pages, "coverage": coverage,
            "notice": "Status describes whether analysis stages ran and produced candidates. It is not accuracy, not review, "
                      "and not a statement about the plant. Zero results are never reported as complete."}
