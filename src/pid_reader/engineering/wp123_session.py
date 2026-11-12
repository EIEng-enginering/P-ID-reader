"""Qt-free glue between the open drawing / project and the WP-01..03 proposal modules (used by the Windows review tab and by tests).

Nothing here writes to the Worksheet R1 contract, the host database or the standalone project tables. Analyses and the named, reasoned,
hash-chained reviewer decisions go to the separate WP123 sidecar (``wp123_store``), by default
``%LOCALAPPDATA%/PIDReader/wp123/wp123_review.sqlite`` (``PID_WP123_STORE`` overrides it) - outside synced storage, like the other high-write stores.
Every record stays PROPOSED_UNVERIFIED; a reviewer decision here is "the printed text reads like this", never plant truth.
"""
from __future__ import annotations

import json
import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from .wp123_recovery import infer_regions, normalise_detections, recover_wp123

GROUPS = ("Readings (tags, line numbers)", "Incomplete line-number strings", "Document fields", "Circle evidence", "Detector triage")
REVIEW_ACTIONS = {"accept": "ACCEPTED_AS_READING", "correct": "CORRECTED_READING", "reject": "REJECTED", "unresolved": "UNRESOLVED"}
STATE_TEXT = {None: "Proposed (not reviewed)", "ACCEPTED_AS_READING": "Reading accepted (as printed)", "CORRECTED_READING": "Reading corrected",
              "REJECTED": "Rejected", "UNRESOLVED": "Left unresolved"}
NOTICE = ("Unverified proposals read from the drawing. Accepting a reading only records that the printed text reads like this; it does not "
          "verify a tag, a connection or the plant, and it is not a HAZOP, LOPA, SIL or IPL input.")


def default_store_path() -> Path:
    env = os.environ.get("PID_WP123_STORE")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "PIDReader" / "wp123" / "wp123_review.sqlite"


def words_from_project(db, extraction_id: str, page: int, result: dict | None = None) -> tuple[list[dict], str]:
    """Words on one page: the newest stored OCR analysis, else the native text layer. Returns (words, origin label)."""
    from .findings import latest_analysis_ids
    ids = latest_analysis_ids(db, extraction_id)
    words: list[dict] = []
    if "ocr" in ids:
        for native_id, text, bbox_json, word_json in db.db.execute(
                "SELECT native_word_id,text,bbox_json,word_json FROM ocr_word WHERE analysis_id=? AND page=? ORDER BY word_id", (ids["ocr"], page)):
            w = json.loads(word_json)
            text = str(text).strip()
            if not text or len(text) > 200:
                continue
            words.append({"id": str(native_id), "text": text, "bbox": json.loads(bbox_json), "page": page,
                          "raw_score": round(float(w.get("raw_ocr_score") or 0), 4), "review_state": "PROPOSED_UNVERIFIED"})
        if words:
            return words, "OCR words (unverified)"
    for o in (result or {}).get("objects", []):
        if o.get("page") == page and o.get("text") and o.get("bbox"):
            t = str(o["text"]).strip()
            if t and len(t) <= 200:
                words.append({"id": str(o["id"]), "text": t, "bbox": o["bbox"], "page": page, "raw_score": 1.0, "review_state": "PROPOSED_UNVERIFIED"})
    return words, ("native text layer (no OCR stored for this page)" if words else "no words stored for this page")


def detections_for_page(pdf_bytes: bytes, page: int) -> tuple[list[dict], str]:
    """Saved TR1 detector proposals for the page (mapped to the media frame), or none. Never runs the detector."""
    from ..formats.page_coordinates import frame_from_pdfplumber
    from ..tr1 import detector
    import pdfplumber
    sha = sha256(pdf_bytes).hexdigest()
    rec = detector.load_sidecar(sha, page)
    if not rec or not rec.get("detections"):
        return [], "no saved learned-detector run for this page"
    with pdfplumber.open(BytesIO(pdf_bytes)) as pl:
        frame = frame_from_pdfplumber(pl.pages[page - 1])
    dets = normalise_detections(rec["detections"], page_frame=frame, render_frame=True)
    for d in dets:
        d["page"] = page
    return dets, f"{len(dets)} saved detector proposals"


def analyse_page(pdf_bytes: bytes, page: int, words: list[dict], detections: list[dict], *, scan_bubbles: bool = False,
                 profile: str = "auto") -> dict:
    bubbles = []
    if scan_bubbles:
        from .wp123_bubbles import scan_pdf_bubbles
        bubbles = scan_pdf_bubbles(pdf_bytes, words, infer_regions(words, profile=profile), page=page)
    return recover_wp123(pdf_bytes, words, detections, profile=profile, bubbles=bubbles)


def latest_decisions(decisions: list[dict]) -> dict[str, dict]:
    """The newest appended decision per target (earlier ones stay in the chain; nothing is overwritten)."""
    out: dict[str, dict] = {}
    for d in decisions:
        out[d["target_id"]] = d
    return out


def _bbox_union(a: dict | None, b: dict | None) -> dict | None:
    if not a or not b:
        return a or b
    return {"x0": min(a["x0"], b["x0"]), "y0": min(a["y0"], b["y0"]), "x1": max(a["x1"], b["x1"]), "y1": max(a["y1"], b["y1"])}


def register_rows(result: dict, decisions: list[dict] | None = None) -> list[dict]:
    """Flat, display-ready rows for every reviewable proposal, with the reviewer's newest decision folded in."""
    latest = latest_decisions(decisions or [])
    assoc_by_tag = {a["tag_id"]: a for a in result.get("associations", [])}
    det_box = {d["id"]: d["bbox"] for d in result.get("detector_decisions", [])}
    rows: list[dict] = []

    def add(group, rid, kind, text, page, bbox, evidence, detail):
        dec = latest.get(rid)
        rows.append({"id": rid, "group": group, "kind": kind, "text": text, "page": page, "bbox": bbox, "evidence": evidence, "detail": detail,
                     "decision": dec["action"] if dec else None, "decided_by": dec["actor"] if dec else "",
                     "corrected_text": dec.get("corrected_text") if dec else None, "reason": dec["reason"] if dec else "",
                     "state_text": STATE_TEXT.get(dec["action"] if dec else None)})

    for r in result.get("readings", []):
        a = assoc_by_tag.get(r["id"])
        ev = f"OCR {', '.join(r['ocr_ids'])[:60]}; score {r.get('raw_ocr_score')}"
        if a:
            ev += f"; symbol link: {a['association_state'].replace('_', ' ').lower()}"
        add(GROUPS[0], r["id"], r["kind"].replace("_", " ").title(), r["text_candidate"], r["page"], r["bbox"], ev, {"reading": r, "association": a})
    for f in result.get("line_number_fragments", []):
        add(GROUPS[1], f["id"], "Incomplete line string", f["text_observed"], f["page"], f["bbox"], f["reason"].replace("_", " ").lower(), f)
    for f in result.get("document_fields", []):
        add(GROUPS[2], f["id"], f["field"].replace("_", " ").title(), f["value_candidate"], f["page"], f["bbox"], f"OCR {', '.join(f['ocr_ids'])[:60]}", f)
    links = {}
    for l in result.get("bubble_text_links", []):
        links.setdefault(l["bubble_id"], []).append(l)
    for b in result.get("bubble_candidates", []):
        codes, nums = b.get("code_candidates", []), b.get("number_candidates", [])
        ev = f"ring support {b.get('raster_ring_support')}; " + b["state"].replace("_", " ").lower()
        add(GROUPS[3], b["id"], "Circle (not a symbol class)", " ".join(codes + nums) or "(no text)", b["page"], b["bbox"], ev,
            {"circle": b, "text_links": links.get(b["id"], [])})
    for d in result.get("detector_decisions", []):
        eligible = d["eligibility"] == "REVIEWABLE_CLASS_CANDIDATE"
        add(GROUPS[4], d["id"], f"Detector box ({d['coarse_class']})", f"score {d['raw_score']}", d["page"], d["bbox"],
            "reviewable class candidate" if eligible else "withheld: " + str(d.get("filter_reason", "")).replace("_", " ").lower(), d)
    rows.sort(key=lambda r: (GROUPS.index(r["group"]), r["page"], r["bbox"]["y0"], r["bbox"]["x0"], r["id"]))
    return rows


def triage_summary(result: dict) -> dict:
    """Counts the reviewer sees first: what was proposed, what was withheld and why."""
    from collections import Counter
    why = Counter(d.get("filter_reason") or "REVIEWABLE" for d in result.get("detector_decisions", []))
    s = dict(result.get("summary", {}))
    s["detector_withheld_reasons"] = dict(why)
    return s


class Wp123Sidecar:
    """Thin helper over WP123Store so the GUI and tests share one code path."""

    def __init__(self, path: str | Path | None = None):
        from .wp123_store import WP123Store
        self.path = Path(path) if path else default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store = WP123Store(self.path)

    def close(self) -> None:
        self.store.close()

    def add(self, result: dict) -> str:
        return self.store.add(result)

    def rows(self, analysis_id: str) -> tuple[dict, list[dict]]:
        doc = self.store.get(analysis_id)
        return doc, register_rows(doc, self.store.decisions(analysis_id))

    def decide(self, analysis_id: str, target_id: str, action: str, *, actor: str, reason: str, corrected_text: str | None = None) -> str:
        if action not in REVIEW_ACTIONS:
            raise ValueError("Unknown review action")
        return self.store.review(analysis_id, target_id, actor=actor, decision=REVIEW_ACTIONS[action], reason=reason, corrected_text=corrected_text)

    def verify(self) -> list[str]:
        return self.store.verify_audit()

    def latest_analysis_for(self, source_sha256: str) -> str | None:
        r = self.store.con.execute("SELECT analysis_id FROM wp123_analyses WHERE source_sha256=? ORDER BY rowid DESC LIMIT 1", (source_sha256,)).fetchone()
        return r[0] if r else None
