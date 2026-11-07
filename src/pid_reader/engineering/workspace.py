"""Read-only, source-linked engineering workspace queries.

Never upgrades a drawing reading to a verified plant asset. Used by the GUI,
CLI and report exporter; no Qt or host Worksheet dependency.
"""
from __future__ import annotations

import json

VALID_STATES = frozenset({"PROPOSED", "ACCEPTED_AS_READING", "EDITED_AND_ACCEPTED",
                          "REJECTED", "IGNORED_REGION"})

_REGISTER_FROM = """FROM observation o
 JOIN extraction e ON e.extraction_id=o.extraction_id
 JOIN document_revision src ON src.sha256=e.document_sha256
 LEFT JOIN drawing_registration reg ON reg.rowid=(
   SELECT MAX(r2.rowid) FROM drawing_registration r2 WHERE r2.extraction_id=o.extraction_id)
 LEFT JOIN review_decision rd ON rd.rowid=(
   SELECT MAX(r3.rowid) FROM review_decision r3 WHERE r3.observation_id=o.observation_id)
 """


def _term(v: str, name: str) -> str:
    if not isinstance(v, str) or len(v) > 150:
        raise ValueError(f"Invalid {name}")
    return v


def _escaped_like(v: str) -> str:
    return "%" + v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def register_page(store, *, extraction_id: str = "", text: str = "",
                  object_class: str = "", state: str = "", drawing_no: str = "",
                  limit: int = 100, offset: int = 0,
                  object_classes: tuple = (), named_only: bool = False) -> dict:
    """Page through all source observations, retaining review *as a drawing reading*.

    A report/UI page is a current database view, not a frozen as-built snapshot.
    Original source text is never replaced by an edited review value.
    """
    if type(limit) is not int or not 1 <= limit <= 250:
        raise ValueError("Register page size must be between 1 and 250")
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError("Invalid register offset")
    terms = dict(extraction_id=extraction_id, text=text, object_class=object_class,
                 state=state, drawing_no=drawing_no)
    for k, v in terms.items():
        _term(v, k)
    if state and state not in VALID_STATES:
        raise ValueError("Unknown drawing review state")
    where = ["1=1"]
    params: list = []
    if extraction_id:
        where.append("o.extraction_id=?"); params.append(extraction_id)
    if text:
        where.append("o.tag_text LIKE ? ESCAPE '\\'"); params.append(_escaped_like(text))
    if object_class:
        where.append("o.class=?"); params.append(object_class)
    if object_classes:
        if (len(object_classes) > 20 or not all(isinstance(c, str) and 0 < len(c) <= 40 for c in object_classes)):
            raise ValueError("Invalid object class list")
        where.append("o.class IN (" + ",".join("?" * len(object_classes)) + ")"); params.extend(object_classes)
    if named_only:
        where.append("TRIM(o.tag_text)<>''")
    if drawing_no:
        where.append("reg.drawing_no=?"); params.append(drawing_no)
    if state == "PROPOSED":
        where.append("rd.decision IS NULL")
    elif state:
        where.append("rd.decision=?"); params.append(state)
    clause = _REGISTER_FROM + " WHERE " + " AND ".join(where)
    total = store.db.execute("SELECT count(*) " + clause, params).fetchone()[0]
    columns = """SELECT o.observation_id,o.native_object_id,o.extraction_id,o.page,
       o.class AS object_class,o.tag_text,o.bbox_json,e.document_sha256,
       src.source_name,reg.drawing_no,reg.revision_label,reg.facility,reg.area,
       rd.decision,rd.actor AS reviewed_by,rd.created_utc AS reviewed_utc,rd.edited_json """
    order = " ORDER BY COALESCE(reg.drawing_no,src.source_name),reg.revision_label,o.page,o.tag_text,o.observation_id LIMIT ? OFFSET ?"
    rows = []
    for r in store.db.execute(columns + clause + order, [*params, limit, offset]):
        row = dict(r)
        row["bbox"] = json.loads(row.pop("bbox_json"))
        row["state"] = row.pop("decision") or "PROPOSED"
        row["reviewed_edit"] = json.loads(row.pop("edited_json")) if row["edited_json"] else None
        rows.append(row)
    return {"schema": "pid-reader-standalone-register-v1", "total": total,
            "offset": offset, "limit": limit, "rows": rows,
            "notice": "Readings from drawing revisions only; no verification of the plant."}


def drawing_graph_view(store, *, extraction_id: str = "", limit: int = 150, offset: int = 0,
                       accepted_endpoints_only: bool = False) -> dict:
    """Source graph edges are *proposals*, even when both endpoint readings reviewed.

    This is never an assertion that the physical connections exist; in particular,
    accepted object readings do not confer acceptance on graph edges.
    """
    _term(extraction_id, "extraction ID")
    if type(limit) is not int or not 1 <= limit <= 250:
        raise ValueError("Invalid graph page size")
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError("Invalid graph offset")
    parts = ["1=1"]
    args = []
    if extraction_id:
        parts.append("g.extraction_id=?"); args.append(extraction_id)
    if accepted_endpoints_only:
        for alias in ("a", "b"):
            parts.append("(SELECT d.decision FROM review_decision d WHERE d.observation_id=" + alias + ".observation_id ORDER BY d.rowid DESC LIMIT 1) IN ('ACCEPTED_AS_READING','EDITED_AND_ACCEPTED')")
    sql = """FROM graph_edge g
        JOIN observation a ON a.observation_id=g.from_observation
        JOIN observation b ON b.observation_id=g.to_observation
        JOIN extraction e ON e.extraction_id=g.extraction_id
        WHERE """ + " AND ".join(parts)
    count = store.db.execute("SELECT count(*) " + sql, args).fetchone()[0]
    rows = [dict(r) for r in store.db.execute(
        """SELECT g.edge_id,g.extraction_id,g.native_connection_id,g.connection_type,
        g.from_observation,g.to_observation,a.tag_text AS from_text,b.tag_text AS to_text,
        a.page AS from_page,b.page AS to_page,e.document_sha256 """ + sql +
        " ORDER BY g.extraction_id,g.edge_id LIMIT ? OFFSET ?", [*args, limit, offset])]
    return {"schema": "pid-reader-standalone-graph-view-v1", "total": count,
            "offset": offset, "limit": limit, "rows": rows,
            "edge_status": "SOURCE_PROPOSAL_UNVERIFIED",
            "notice": "Graph edges are proposed drawing relationships, not verified physical connections."}


def crosssheet_graph_view(store, *, analysis_id: str = "", limit: int = 150) -> dict:
    """Cross-sheet proposals with latest human *as-drawn* decisions, never plant status."""
    _term(analysis_id, "analysis ID")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Invalid graph limit")
    query = """SELECT c.candidate_id,c.analysis_id,c.candidate_json,
        src.extraction_id AS from_extraction_id,dst.extraction_id AS to_extraction_id,
        src.label AS from_label,dst.label AS to_label,
        (SELECT rd.decision FROM crosssheet_decision rd WHERE rd.candidate_id=c.candidate_id
         ORDER BY rd.rowid DESC LIMIT 1) AS decision
        FROM crosssheet_candidate c
        JOIN offpage_annotation src ON src.annotation_id=c.from_annotation_id
        JOIN offpage_annotation dst ON dst.annotation_id=c.to_annotation_id
        WHERE 1=1"""
    args = []
    if analysis_id:
        query += " AND c.analysis_id=?"; args.append(analysis_id)
    query += " ORDER BY c.analysis_id,c.candidate_id LIMIT ?"; args.append(limit)
    rows = []
    for record in store.db.execute(query, args):
        row = dict(record)
        row["proposal"] = json.loads(row.pop("candidate_json"))
        row["state"] = row.pop("decision") or "UNRESOLVED"
        rows.append(row)
    return {"schema": "pid-reader-standalone-crosssheet-view-v1", "rows": rows,
            "notice": "Matching drawing references do not prove same plant assets or current revisions."}
