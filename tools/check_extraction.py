"""Check a P&ID reader output against the rules of 01_REQUIREMENTS.md. Standard library only (uses `jsonschema` too if it happens to be installed).

    python tools/check_extraction.py RESULT.json [--schema schemas/pid_extraction.schema.json]

Exit code 0 = no violation found, 1 = violations (listed), 2 = the file could not be read.
This is a MECHANICAL check of structure and wording rules. Passing it says nothing about whether the reading is right; accuracy is shown only by the benchmark (section L).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

CLASSES = {"VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER", "VALVE_MANUAL", "VALVE_CONTROL", "VALVE_ONOFF", "VALVE_CHECK", "PSV", "RUPTURE_DISC",
           "INSTRUMENT", "LOGIC_SOLVER_NODE", "LINE", "SIGNAL_LINE", "NOZZLE", "OFF_PAGE_CONNECTOR", "SPEC_BREAK", "NOTE", "OTHER", "UNKNOWN"}
RUN_FIELDS = ("run_id", "started_utc", "finished_utc", "result_sha256")
INDEPENDENCE = "Not an assessment of independence."
ABSENCE = "The absence of shared-component evidence is not evidence of independence."
FORBIDDEN = re.compile(r"\b(verified|validated|approved|as[- ]built|certified|complete|completeness|independent)\b", re.I)
NEGATION = re.compile(r"\b(not|no|never|cannot|can't|nothing|without|neither|nor|un)\b", re.I)
SHA = re.compile(r"^[0-9a-f]{64}$")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def recompute_result_hash(doc: dict) -> str:
    body = json.loads(canonical(doc))
    for key in RUN_FIELDS:
        body["provenance"].pop(key, None)
    return sha(canonical(body))


def box_ok(b) -> bool:
    try:
        return 0 <= b["x0"] < b["x1"] <= 1 and 0 <= b["y0"] < b["y1"] <= 1
    except (KeyError, TypeError):
        return False


def forbidden_in(text: str) -> list[str]:
    """Words module-authored text must not use (PR-A03). A word within 30 characters after a negation ('not complete') is accepted: it denies the claim."""
    hits = []
    for m in FORBIDDEN.finditer(text or ""):
        if not NEGATION.search(text[max(0, m.start() - 30):m.start()]):
            hits.append(m.group(0))
    return hits


def check(doc: dict) -> list[str]:
    errors: list[str] = []
    err = errors.append
    for key in ("schema_version", "provenance", "document", "pages", "objects", "connections", "loop_proposals", "shared_component_evidence", "unreadable_regions", "warnings", "summary"):
        if key not in doc:
            err(f"missing top-level key: {key}")
    if errors:
        return errors
    if doc["schema_version"] != 1:
        err("schema_version must be 1")
    prov = doc["provenance"]
    for key in ("module_name", "module_version", "params", "params_sha256", "input_sha256", "models", "run_id", "started_utc", "finished_utc", "host", "limitations_text", "reader_confidence_note", "result_sha256"):
        if key not in prov:
            err(f"provenance.{key} missing")
    if errors:
        return errors
    for key in ("params_sha256", "input_sha256", "result_sha256"):
        if not SHA.match(str(prov[key])):
            err(f"provenance.{key} is not a SHA-256")
    if sha(canonical(prov["params"])) != prov["params_sha256"]:
        err("provenance.params_sha256 does not match the canonical JSON of provenance.params")
    if recompute_result_hash(doc) != prov["result_sha256"]:
        err("provenance.result_sha256 does not match the canonical JSON of the result (PR-B09)")
    if len(str(prov["limitations_text"]).strip()) < 20:
        err("limitations_text is missing or too short (PR-A04)")
    if not SHA.match(str(doc["document"].get("sha256", ""))):
        err("document.sha256 is not a SHA-256")
    elif doc["document"]["sha256"] != prov["input_sha256"]:
        err("document.sha256 differs from provenance.input_sha256")
    page_count = doc["document"].get("page_count", 0)
    pages = {}
    for p in doc["pages"]:
        pages[p.get("page")] = p
        if p.get("classification") not in ("VECTOR_TEXT", "RASTER_ONLY", "MIXED", "NOT_PID"):
            err(f"page {p.get('page')}: bad classification")
        if p.get("read_status") == "REFUSED" and not p.get("refusal_code"):
            err(f"page {p.get('page')}: refused without a refusal_code (PR-C05)")
        if not isinstance(p.get("page"), int) or not 1 <= p["page"] <= max(page_count, 1):
            err(f"page number out of range: {p.get('page')}")

    ids: set[str] = set()
    obj_ids: set[str] = set()

    def unique(item_id: str, label: str) -> None:
        if item_id in ids:
            err(f"duplicate id: {item_id}")
        ids.add(item_id)

    def evidence_ok(where: str, evidence) -> None:
        if not evidence:
            err(f"{where}: no evidence (PR-D03)")
            return
        for e in evidence:
            if e.get("page") not in pages:
                err(f"{where}: evidence on a page that is not listed")
            if not box_ok(e.get("bbox")):
                err(f"{where}: evidence box outside 0..1 or inverted (PR-C04)")

    for o in doc["objects"]:
        oid = o.get("id", "")
        unique(oid, "object")
        obj_ids.add(oid)
        if not str(oid).startswith("obj-"):
            err(f"{oid}: object id must start with obj-")
        if o.get("class") not in CLASSES:
            err(f"{oid}: class {o.get('class')!r} is not in the controlled list (PR-D02)")
        if o.get("status") != "UNVERIFIED":
            err(f"{oid}: status must be UNVERIFIED (PR-A02)")
        if not box_ok(o.get("bbox")):
            err(f"{oid}: box outside 0..1 or inverted (PR-C04)")
        if not isinstance(o.get("confidence"), (int, float)) or not 0 <= o["confidence"] <= 1:
            err(f"{oid}: confidence outside 0..1")
        if o.get("page") not in pages:
            err(f"{oid}: on a page that is not listed")
        elif pages[o["page"]].get("read_status") == "REFUSED":
            err(f"{oid}: an object on a REFUSED page")
        if not isinstance(o.get("text"), str):
            err(f"{oid}: text must be the verbatim printed string")
        if o.get("class") == "UNKNOWN" and o.get("parsed", {}).get("parse_status") == "PARSED":
            err(f"{oid}: an UNKNOWN symbol must not carry a parsed tag as if recognised")
        for k, v in (o.get("attributes") or {}).items():
            if not isinstance(v, str):
                err(f"{oid}: attribute {k!r} must be a verbatim string (PR-D04)")
        evidence_ok(oid, o.get("evidence"))

    for c in doc["connections"]:
        cid = c.get("id", "")
        unique(cid, "connection")
        if not str(cid).startswith("con-"):
            err(f"{cid}: connection id must start with con-")
        for end in ("from", "to"):
            if c.get(end, {}).get("object_id") not in obj_ids:
                err(f"{cid}: {end} refers to an object that does not exist")
        if c.get("status") != "UNVERIFIED":
            err(f"{cid}: status must be UNVERIFIED")
        if c.get("direction") not in ("FORWARD", "BACKWARD", "UNKNOWN"):
            err(f"{cid}: bad direction")
        poly = c.get("polyline") or []
        if len(poly) < 2 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in poly):
            err(f"{cid}: polyline needs two points inside 0..1")
        evidence_ok(cid, c.get("evidence"))

    for lp in doc["loop_proposals"]:
        lid = lp.get("id", "")
        unique(lid, "loop")
        if lp.get("independence_statement") != INDEPENDENCE:
            err(f"{lid}: independence_statement must be exactly {INDEPENDENCE!r} (PR-D06)")
        if lp.get("status") != "UNVERIFIED":
            err(f"{lid}: status must be UNVERIFIED")
        for m in lp.get("members", []):
            if m.get("object_id") not in obj_ids:
                err(f"{lid}: member refers to an object that does not exist")
        for bad in forbidden_in(lp.get("basis", "")):
            err(f"{lid}: basis uses the word {bad!r} (PR-A03)")
    for sc in doc["shared_component_evidence"]:
        sid = sc.get("id", "")
        unique(sid, "shared")
        if sc.get("absence_statement") != ABSENCE:
            err(f"{sid}: absence_statement must be exactly {ABSENCE!r} (PR-G03)")
        if sc.get("status") != "UNVERIFIED":
            err(f"{sid}: status must be UNVERIFIED")
        for oid in sc.get("object_ids", []):
            if oid not in obj_ids:
                err(f"{sid}: refers to an object that does not exist")
        for bad in forbidden_in(sc.get("basis", "")):
            err(f"{sid}: basis uses the word {bad!r} (PR-A03)")
    for u in doc["unreadable_regions"]:
        if not box_ok(u.get("bbox")):
            err(f"unreadable region {u.get('id')}: box outside 0..1 or inverted")
        for bad in forbidden_in(u.get("message", "")):
            err(f"unreadable region {u.get('id')}: message uses {bad!r}")
    for w in doc["warnings"]:
        for bad in forbidden_in(w.get("message", "")):
            err(f"warning {w.get('code')}: message uses {bad!r} (PR-A03)")

    # module-authored free text (verbatim drawing text in `text`, evidence and attributes is exempt)
    for label, text in (("limitations_text", prov["limitations_text"]), ("reader_confidence_note", prov["reader_confidence_note"])) + tuple((f"page {k} reason", v.get("reason", "")) for k, v in pages.items()):
        for bad in forbidden_in(text):
            err(f"{label} uses the word {bad!r} (PR-A03)")
    note = str(prov["reader_confidence_note"]).lower()
    if "accuracy" in note and "not" not in note:
        err("reader_confidence_note speaks of accuracy without denying it (PR-A05)")

    s = doc["summary"]
    counts: dict[str, int] = {}
    for o in doc["objects"]:
        counts[o.get("class")] = counts.get(o.get("class"), 0) + 1
    if s.get("counts_by_class") != counts:
        err("summary.counts_by_class does not match the objects")
    if s.get("object_count") != len(doc["objects"]) or s.get("connection_count") != len(doc["connections"]):
        err("summary counts do not match the lists")
    return errors


def schema_check(doc: dict, schema_path: Path) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return ["(jsonschema is not installed: the full schema check was skipped; the structural checks above still ran)"]
    validator = jsonschema.Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    return [f"schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in sorted(validator.iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result")
    parser.add_argument("--schema", default=str(Path(__file__).resolve().parents[1] / "schemas" / "pid_extraction.schema.json"))
    args = parser.parse_args(argv)
    try:
        doc = json.loads(Path(args.result).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.result}: {exc}")
        return 2
    problems = check(doc)
    extra = schema_check(doc, Path(args.schema))
    hard = problems + [e for e in extra if not e.startswith("(")]
    for line in problems + extra:
        print(line)
    print(f"{len(hard)} violation(s)")
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
