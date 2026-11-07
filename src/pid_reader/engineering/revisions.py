"""Rev O: conservative comparison of two existing, source-hashed R1 extractions.

A source comparison is NOT an as-built change assessment, nor an automatic
asset identity mapping. Only uniquely represented *parsed* (class, tag) pairs
can be matched. Other records and duplicate keys remain explicit exclusions.
"""
from __future__ import annotations

from collections import defaultdict
from ..api import canonical_json, sha256_hex

SCHEMA = "pid-reader-standalone-revision-diff-v1"
MAX_OBJECTS = 20000


def _tag(o: dict) -> str | None:
    if not isinstance(o, dict):
        raise ValueError("Invalid source observation")
    cls, parsed = o.get("class"), o.get("parsed")
    if cls in ("NOTE", "OTHER", "UNKNOWN", None) or not isinstance(parsed, dict):
        return None
    if parsed.get("parse_status") not in ("PARSED", "PARTIAL"):
        return None
    tag = parsed.get("normalised_tag")
    if not isinstance(cls, str) or not isinstance(tag, str) or not tag.strip():
        return None
    return tag.strip().upper()


def _group(extraction: dict) -> tuple[dict, list[dict]]:
    if not isinstance(extraction, dict):
        raise ValueError("Invalid extraction object")
    doc = extraction.get("document", {})
    objects = extraction.get("objects", [])
    if not isinstance(doc, dict) or not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ValueError("Invalid extraction or oversized object collection")
    groups = defaultdict(list)
    skipped = []
    seen = set()
    for o in objects:
        if not isinstance(o, dict) or not isinstance(o.get("id"), str) or o["id"] in seen:
            raise ValueError("Invalid or duplicated observation identifier")
        seen.add(o["id"])
        tag = _tag(o)
        if not tag:
            skipped.append({"id": o["id"], "reason": "NO_UNIQUE_ENGINEERING_TAG_EVIDENCE"})
            continue
        groups[(o["class"], tag)].append(o)
    return groups, skipped


def compare_extractions(before: dict, after: dict,
                        before_registration: dict | None = None,
                        after_registration: dict | None = None) -> dict:
    """Produce a deterministic *proposal*, never transfer prior acceptance."""
    from ..api import result_sha256
    for label, e in (("before", before), ("after", after)):
        if (e.get("schema_version") != 1 or
            e.get("provenance", {}).get("result_sha256") != result_sha256(e)):
            raise ValueError(f"Invalid {label} extraction hash")
        if not isinstance(e["document"].get("sha256"), str) or len(e["document"]["sha256"]) != 64:
            raise ValueError("Invalid source hash")
    if not isinstance(before_registration, (dict, type(None))) or not isinstance(after_registration, (dict, type(None))):
        raise ValueError("Invalid registration snapshot")
    b, bskip = _group(before)
    a, askip = _group(after)
    events = []
    for key in sorted(set(b) | set(a)):
        older, newer = b.get(key, []), a.get(key, [])
        base = {"class": key[0], "tag": key[1],
                "before_object_ids": sorted(o["id"] for o in older),
                "after_object_ids": sorted(o["id"] for o in newer)}
        if len(older) > 1 or len(newer) > 1:
            kind = "AMBIGUOUS_DUPLICATE_TAG"
            changed = []
        elif not older:
            kind = "ADDED_ON_DRAWING"; changed = []
        elif not newer:
            kind = "REMOVED_FROM_DRAWING"; changed = []
        else:
            old, new = older[0], newer[0]
            changed = [field for field in ("text", "parsed", "attributes") if old.get(field) != new.get(field)]
            if changed:
                kind = "INTERPRETATION_CHANGED"
            elif (old.get("page"), old.get("bbox")) != (new.get("page"), new.get("bbox")):
                kind = "POSITION_CHANGED"
                changed = [k for k in ("page", "bbox") if old.get(k) != new.get(k)]
            else:
                kind = "SAME_READING"
        events.append({**base, "kind": kind, "changed_fields": changed})
    bsha = before["document"]["sha256"]
    asha = after["document"]["sha256"]
    if bsha == asha:
        source_state = ("IDENTICAL_EXTRACTION" if before["provenance"]["result_sha256"] ==
                        after["provenance"]["result_sha256"] else "SAME_SOURCE_DIFFERENT_EXTRACTION")
    else:
        source_state = "DIFFERENT_SOURCE_BYTES"
    result = {
        "schema": SCHEMA,
        "status": "PROPOSAL_ONLY_NOT_AS_BUILT_VERIFICATION",
        "before": {"source_sha256": bsha, "result_sha256": before["provenance"]["result_sha256"],
                   "document": before["document"], "registration": before_registration},
        "after": {"source_sha256": asha, "result_sha256": after["provenance"]["result_sha256"],
                  "document": after["document"], "registration": after_registration},
        "source_state": source_state,
        "events": events,
        "unmatched_before": sorted(bskip, key=lambda r:r["id"]),
        "unmatched_after": sorted(askip, key=lambda r:r["id"]),
        "limitations": [
            "Only unique class+parsed-tag pairs are matched; changed classes/tags appear as removals/additions, not proven replacements.",
            "Untaggable observations and repeated tags remain unmatched; no physical asset identities are established.",
            "An extraction difference on identical source bytes is not a drawing revision.",
            "This document comparison does not establish the current approved or as-built facility state.",
        ],
    }
    result["result_sha256"] = sha256_hex(canonical_json(result).encode("utf-8"))
    return result
