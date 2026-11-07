"""Rev K: immutable, source-linked OCR and instrument/equipment-tag hypotheses.

This module is standalone-only. Its output NEVER amends Worksheet R1 extraction,
asserts an instrument's engineering function, or verifies the physical plant.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
import re

from ..api import canonical_json, result_sha256, sha256_hex, stable_id
from ..formats.ocr_source import verify_ocr_preview

ALGORITHM = "source-tag-association-0.1"
SCHEMA = "pid-reader-standalone-text-links-v1"
MAX_WORDS = 50000
MAX_LINKS = 12000
MAX_OPTIONS_PER_SYMBOL = 40
TAG_STYLE = re.compile(r"^[A-Z]{1,8}-?[0-9]{1,7}[A-Z]?$", re.ASCII)


def _centre(box: dict) -> tuple[float, float]:
    return ((box["x0"] + box["x1"]) / 2, (box["y0"] + box["y1"]) / 2)


def _contained(box: dict, outer: dict, padding: float = .0015) -> bool:
    x, y = _centre(box)
    return outer["x0"] - padding <= x <= outer["x1"] + padding and outer["y0"] - padding <= y <= outer["y1"] + padding


def _valid_box(b: object) -> bool:
    return (type(b) is dict and set(b) == {"x0", "y0", "x1", "y1"}
            and all(type(v) in (float, int) and isfinite(v) and 0 <= v <= 1 for v in b.values())
            and b["x0"] < b["x1"] and b["y0"] < b["y1"])


def validate_ocr_source(ocr: dict, extraction: dict) -> list[str]:
    """Validate standalone OCR evidence against the exact source and pages.

    OCR confidence remains a raw model score. Structural checks cannot certify
    text recognition correctness, but prevent mismatched or fabricated references.
    """
    if type(ocr) is not dict or type(extraction) is not dict:
        return ["OCR and extraction must be objects"]
    issues = []
    if not verify_ocr_preview(ocr):
        issues.append("OCR result is not a valid hashed standalone preview")
    if extraction.get("schema_version") != 1 or result_sha256(extraction) != extraction.get("provenance", {}).get("result_sha256"):
        issues.append("Original extraction hash is invalid")
    if ocr.get("source_sha256") != extraction.get("document", {}).get("sha256"):
        issues.append("OCR and extraction are from different source PDF bytes")
    allowed = {p["page"] for p in extraction.get("pages", [])}
    selected = ocr.get("selected_pages")
    pages = ocr.get("pages")
    if not isinstance(selected, list) or not selected or any(type(p) is not int for p in selected) or len(set(selected)) != len(selected) or any(p not in allowed for p in selected):
        issues.append("OCR selected pages do not match extracted source pages")
        return issues
    if not isinstance(pages, list) or [p.get("page") for p in pages if type(p) is dict] != selected or len(pages) != len(selected):
        issues.append("OCR page entries do not match the requested pages")
        return issues
    seen = set()
    nwords = 0
    for page in pages:
        words = page.get("words")
        if not isinstance(words, list):
            issues.append("OCR page is missing its word list")
            continue
        nwords += len(words)
        if nwords > MAX_WORDS:
            issues.append("OCR word-count cap exceeded")
            break
        for word in words:
            if not isinstance(word, dict):
                issues.append("Malformed OCR word")
                continue
            text = word.get("text")
            box = word.get("bbox")
            score = word.get("raw_ocr_score")
            if (not isinstance(text, str) or not text.strip() or len(text) > 1000
                or not _valid_box(box) or type(word.get("page")) is not int
                or word["page"] != page["page"] or word.get("review_state") != "PROPOSED"
                or word.get("engine") not in OCR_ENGINES
                or type(score) not in (float, int) or not isfinite(score) or not 0 <= score <= 1):
                issues.append("Invalid OCR word contents or geometry")
                continue
            expected = stable_id("ocr", ocr["source_sha256"], page["page"], box, text)
            if word.get("id") != expected or word["id"] in seen:
                issues.append("OCR word identity invalid or duplicated")
            seen.add(word["id"])
    return issues


OCR_ENGINES = ("local_tesseract", "local_rapidocr")


def _group_words(words: list[dict]) -> list[dict]:
    """Produce single words and at most three adjacent tokens for split tag text.

    A possible multi-token tag needs close horizontal adjacency, similar vertical
    baseline and no overlap of its two raw bounding boxes. No auto acceptance.
    """
    if len(words) > 80:
        raise ValueError("Excessively dense symbol OCR region requires manual review")
    parts = []
    sorted_words = sorted(words, key=lambda w: (w["bbox"]["y0"], w["bbox"]["x0"], w["id"]))
    for w in sorted_words:
        parts.append({"text": w["text"], "source_ids": [w["id"]], "bbox": w["bbox"]})
    for first in sorted_words:
        chain = [first]
        for _ in range(2):
            last = chain[-1]
            possibilities = []
            for other in sorted_words:
                if other["id"] in {t["id"] for t in chain}:
                    continue
                a, b = last["bbox"], other["bbox"]
                height = max(a["y1"] - a["y0"], b["y1"] - b["y0"])
                overlap = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
                gap = b["x0"] - a["x1"]
                if overlap >= .4 * height and -0.0005 <= gap <= min(.012, height * .95):
                    possibilities.append((round(gap, 7), b["x0"], other["id"], other))
            if not possibilities:
                break
            nxt = min(possibilities)[3]
            chain.append(nxt)
            txt = "".join(w["text"] for w in chain)
            if TAG_STYLE.fullmatch(txt.upper().replace(" ", "")):
                boxes = [w["bbox"] for w in chain]
                parts.append({"text": txt, "source_ids": [w["id"] for w in chain],
                              "bbox": {"x0": min(b["x0"] for b in boxes), "y0": min(b["y0"] for b in boxes),
                                       "x1": max(b["x1"] for b in boxes), "y1": max(b["y1"] for b in boxes)}})
    return parts


def build_text_links(extraction: dict, symbols: dict, ocr: dict) -> dict:
    """Produce reviewable evidence alternatives for each source symbol proposal."""
    issues = validate_ocr_source(ocr, extraction)
    if issues:
        raise ValueError("Invalid OCR/extraction evidence: " + "; ".join(issues[:4]))
    if (symbols.get("source_sha256") != ocr["source_sha256"] or
        symbols.get("extraction_sha256") != extraction["provenance"]["result_sha256"]):
        raise ValueError("Symbol analysis refers to different source observations")
    if sha256_hex(canonical_json({k:v for k,v in symbols.items() if k != "result_sha256"}).encode("utf-8")) != symbols.get("result_sha256"):
        raise ValueError("Invalid symbol content hash")
    native = {o["id"]: o for o in extraction["objects"]}
    by_page = defaultdict(list)
    for page in ocr["pages"]:
        by_page[page["page"]].extend(page["words"])
    proposals = []
    for shape in sorted(symbols["symbol_candidates"], key=lambda x: (x["page"], x["id"])):
        bbox = shape["bbox"]
        if not _valid_box(bbox) or shape.get("status") != "PROPOSED_UNVERIFIED":
            raise ValueError("Malformed or reviewed symbol proposal supplied")
        # OCR words may originate in a scan that has no native text at all.
        ocr_method = "OCR_RAPIDOCR" if str(ocr.get("algorithm", "")).startswith("rapidocr") else "OCR_TESSERACT"
        relevant = [w for w in by_page[shape["page"]] if _contained(w["bbox"], bbox)]
        variants = {}
        unparsed_ocr = []
        for id_ in shape["tag_object_ids"]:
            obj = native.get(id_)
            if obj is None or obj["page"] != shape["page"] or not _valid_box(obj["bbox"]):
                raise ValueError("Symbol references invalid native text")
            if not _contained(obj["bbox"], bbox):
                raise ValueError("Native text is not inside its proposed outline")
            text = obj["text"].strip()
            if text:
                key = text.upper().replace(" ", "")
                variants.setdefault(key, []).append({"method": "PDF_NATIVE", "object_id": id_, "bbox": obj["bbox"]})
        for part in _group_words(relevant):
            key = part["text"].upper().replace(" ", "")
            if TAG_STYLE.fullmatch(key):
                variants.setdefault(key, []).append({"method": ocr_method, "word_ids": part["source_ids"], "bbox": part["bbox"]})
            else:
                unparsed_ocr.append({"text": part["text"], "word_ids": part["source_ids"], "bbox": part["bbox"]})
        options = []
        for key, evidence in sorted(variants.items()):
            # A single OCR word also appears in a joined candidate. Prefer the
            # maximal tag-style token chain as one alternative only if it is
            # uniquely recoverable. Otherwise ambiguity is not hidden.
            options.append({"text_candidate": key, "tag_style": "TAG_PATTERN" if TAG_STYLE.fullmatch(key) else "OTHER_TEXT",
                            "sources": sorted(evidence, key=lambda e: canonical_json(e))})
        if len(options) > MAX_OPTIONS_PER_SYMBOL:
            raise ValueError("Text association candidate budget exceeded")
        state = "NO_TEXT" if not options else "ONE_TEXT" if len(options) == 1 else "MULTIPLE_TEXT_OPTIONS"
        proposals.append({"id": stable_id("text-link", ocr["source_sha256"], symbols["result_sha256"], ocr["result_sha256"], shape["id"]),
                          "symbol_id": shape["id"], "page": shape["page"], "bbox": bbox,
                          "association_state": state, "options": options,
                          "unparsed_ocr_evidence": sorted(unparsed_ocr,key=lambda e:canonical_json(e)),
                          "review_state": "PROPOSED_UNVERIFIED",
                          "limitations": "Tag text and symbol proximity are drawing proposals, not proven instrument identity or plant facts."})
        if len(proposals) > MAX_LINKS:
            raise ValueError("Text association count budget exceeded")
    body = {"schema": SCHEMA, "algorithm": ALGORITHM, "source_sha256": ocr["source_sha256"],
            "extraction_sha256": extraction["provenance"]["result_sha256"],
            "symbol_sha256": symbols["result_sha256"], "ocr_sha256": ocr["result_sha256"],
            "proposals": proposals,
            "limitations": "Not a Worksheet R1 schema or approved engineering object. Human review required."}
    body["result_sha256"] = sha256_hex(canonical_json(body).encode("utf-8"))
    return body


def validate_text_links(result: dict, extraction: dict, symbols: dict, ocr: dict) -> list[str]:
    if not isinstance(result, dict):
        return ["Text associations must be an object"]
    if result.get("schema") != SCHEMA:
        return ["Unsupported text association schema"]
    try:
        expected = build_text_links(extraction, symbols, ocr)
        return [] if expected == result else ["Text associations differ from source-derived reproducible result"]
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return ["Invalid text association evidence: " + str(exc)[:200]]
