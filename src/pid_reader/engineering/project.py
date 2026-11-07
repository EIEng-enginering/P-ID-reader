"""Local standalone engineering project store. Does not write into Worksheet .hzcase.

Immutable source/extraction rows and append-only decisions preserve the evidence
history. This is a DEV schema; it is not a host migration.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from ..api import canonical_json, result_sha256
from .migrations import upgrade, LATEST_SCHEMA
from .topology import validate_topology_result
from .symbols import validate_symbol_proposals

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS project_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_revision (
  sha256 TEXT PRIMARY KEY, document_id TEXT NOT NULL, source_name TEXT NOT NULL,
  page_count INTEGER NOT NULL, imported_utc TEXT NOT NULL, source_bytes BLOB
);
CREATE TABLE IF NOT EXISTS extraction (
  extraction_id TEXT PRIMARY KEY, document_sha256 TEXT NOT NULL,
  schema_version INTEGER NOT NULL, result_hash TEXT NOT NULL,
  result_json TEXT NOT NULL, imported_utc TEXT NOT NULL,
  FOREIGN KEY(document_sha256) REFERENCES document_revision(sha256),
  UNIQUE(document_sha256, result_hash)
);
CREATE TABLE IF NOT EXISTS observation (
  observation_id TEXT PRIMARY KEY, extraction_id TEXT NOT NULL,
  native_object_id TEXT NOT NULL, page INTEGER NOT NULL, class TEXT NOT NULL,
  tag_text TEXT NOT NULL, bbox_json TEXT NOT NULL, observation_json TEXT NOT NULL,
  FOREIGN KEY(extraction_id) REFERENCES extraction(extraction_id),
  UNIQUE(extraction_id, native_object_id)
);
CREATE TABLE IF NOT EXISTS graph_edge (
  edge_id TEXT PRIMARY KEY, extraction_id TEXT NOT NULL,
  native_connection_id TEXT NOT NULL, from_observation TEXT NOT NULL, to_observation TEXT NOT NULL,
  connection_type TEXT NOT NULL, edge_json TEXT NOT NULL,
  FOREIGN KEY(extraction_id) REFERENCES extraction(extraction_id),
  FOREIGN KEY(from_observation) REFERENCES observation(observation_id),
  FOREIGN KEY(to_observation) REFERENCES observation(observation_id)
);
CREATE TABLE IF NOT EXISTS review_decision (
  decision_id TEXT PRIMARY KEY, observation_id TEXT NOT NULL,
  actor TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
  edited_json TEXT, created_utc TEXT NOT NULL,
  FOREIGN KEY(observation_id) REFERENCES observation(observation_id),
  CHECK(decision IN ('ACCEPTED_AS_READING','EDITED_AND_ACCEPTED','REJECTED','IGNORED_REGION'))
);
CREATE TABLE IF NOT EXISTS audit_event (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
  entity_id TEXT NOT NULL, event_json TEXT NOT NULL, created_utc TEXT NOT NULL,
  prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_observation_tag ON observation(tag_text);
CREATE INDEX IF NOT EXISTS ix_observation_class ON observation(class);
CREATE INDEX IF NOT EXISTS ix_observation_extraction ON observation(extraction_id);
CREATE INDEX IF NOT EXISTS ix_graph_edge_from ON graph_edge(from_observation);
CREATE INDEX IF NOT EXISTS ix_graph_edge_to ON graph_edge(to_observation);
CREATE INDEX IF NOT EXISTS ix_review_observation ON review_decision(observation_id,created_utc);
"""
IMMUTABLE = ("document_revision", "extraction", "observation", "graph_edge", "review_decision", "audit_event")

def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def _global_id(namespace: str, *parts: str) -> str:
    return namespace + "-" + hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()[:24]


class ProjectStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        existed_before_open = self.path.exists() and self.path.stat().st_size > 0
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(DDL)
        from .examples import ensure_schema as _ensure_example_tables
        _ensure_example_tables(self.db)   # additive teach-by-example tables, no schema-version bump
        for name in IMMUTABLE:
            for action in ("UPDATE", "DELETE"):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS block_{action.lower()}_{name} "
                                f"BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'append-only record'); END")
        self.db.execute("INSERT OR IGNORE INTO project_meta(key,value) VALUES('standalone_schema','1')")
        self.db.commit()
        self.migration_backup = upgrade(self.db, self.path, existed_before_open=existed_before_open)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _append_event(self, kind: str, entity_id: str, payload: dict, now: str) -> None:
        last=self.db.execute("SELECT event_hash FROM audit_event ORDER BY event_id DESC LIMIT 1").fetchone()
        previous=last[0] if last else "0"*64
        body=canonical_json({"prev_hash":previous,"kind":kind,"entity_id":entity_id,"payload":payload,"utc":now})
        digest=hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.db.execute("INSERT INTO audit_event(event_type,entity_id,event_json,created_utc,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
                        (kind,entity_id,canonical_json(payload),now,previous,digest))

    def verify_audit_chain(self) -> bool:
        previous="0"*64
        for row in self.db.execute("SELECT event_type,entity_id,event_json,created_utc,prev_hash,event_hash FROM audit_event ORDER BY event_id"):
            body=canonical_json({"prev_hash":previous,"kind":row[0],"entity_id":row[1],"payload":json.loads(row[2]),"utc":row[3]})
            actual=hashlib.sha256(body.encode("utf-8")).hexdigest()
            if row[4]!=previous or row[5]!=actual:
                return False
            previous=actual
        return True

    def get_source_pdf(self, sha256: str) -> bytes | None:
        r=self.db.execute("SELECT source_bytes FROM document_revision WHERE sha256=?",(sha256,)).fetchone()
        return r[0] if r else None

    def add_extraction(self, result: dict, source_pdf_bytes: bytes | None = None) -> str:
        if result.get("schema_version") != 1 or result_sha256(result) != result.get("provenance",{}).get("result_sha256"):
            raise ValueError("Source extraction is missing or has an invalid content hash")
        source = result["document"]
        digest = source["sha256"]
        if source_pdf_bytes is not None and hashlib.sha256(source_pdf_bytes).hexdigest()!=digest:
            raise ValueError("Source bytes do not match the extraction source hash")
        eid = _global_id("ext", digest, result["provenance"]["result_sha256"])
        objmap = {o["id"]:_global_id("obs",eid,o["id"]) for o in result["objects"]}
        if len(objmap) != len(result["objects"]):
            raise ValueError("Duplicate source observation identifier")
        now = _utc()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO document_revision VALUES(?,?,?,?,?,?)",
                            (digest,source["document_revision_id"],source["filename"],source["page_count"],now,source_pdf_bytes))
            if self.db.execute("SELECT 1 FROM extraction WHERE extraction_id=?",(eid,)).fetchone():
                return eid
            self.db.execute("INSERT INTO extraction VALUES(?,?,?,?,?,?)",
                            (eid,digest,result["schema_version"],result["provenance"]["result_sha256"],canonical_json(result),now))
            for o in result["objects"]:
                self.db.execute("INSERT INTO observation VALUES(?,?,?,?,?,?,?,?)",
                                (objmap[o["id"]],eid,o["id"],o["page"],o["class"],o["text"],
                                 canonical_json(o["bbox"]),canonical_json(o)))
            for edge in result["connections"]:
                fid = objmap[edge["from"]["object_id"]]
                tid = objmap[edge["to"]["object_id"]]
                self.db.execute("INSERT INTO graph_edge VALUES(?,?,?,?,?,?,?)",
                                (_global_id("edge",eid,edge["id"]),eid,edge["id"],fid,tid,edge["type"],canonical_json(edge)))
            self._append_event("EXTRACTION_IMPORTED",eid,{"source_sha256":digest,"result_hash":result["provenance"]["result_sha256"]},now)
        return eid

    # --- Rev S/T: immutable raster strokes, filled and outlined glyph proposals ---

    def add_raster_analysis(self, extraction_id: str, result: dict) -> str:
        """Store unverified pixel observations, never modify accepted Worksheet records."""
        from .raster_geometry import validate_raster_result
        row=self.db.execute("SELECT document_sha256,result_json FROM extraction WHERE extraction_id=?",
                            (extraction_id,)).fetchone()
        if row is None:
            raise KeyError("Raster source extraction not found")
        source=self.get_source_pdf(row[0])
        if source is None:
            raise ValueError("Immutable PDF source bytes are required for raster coordinate verification")
        problems=validate_raster_result(result, source)
        if problems:
            raise ValueError("Invalid raster evidence: " + "; ".join(problems[:5]))
        imported=json.loads(row[1])
        page_set={x["page"] for x in imported["pages"]}
        if not set(result["selected_pages"]).issubset(page_set):
            raise ValueError("Raster analysis pages exceed extraction selection")
        aid=_global_id("raster-analysis",extraction_id,result["result_sha256"])
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM raster_analysis WHERE analysis_id=?",(aid,)).fetchone():
                return aid
            self.db.execute("INSERT INTO raster_analysis VALUES(?,?,?,?,?,?)",
                (aid,extraction_id,result["algorithm"],result["result_sha256"],canonical_json(result),now))
            for candidate in (result["filled_valve_candidates"] + result.get("outline_valve_candidates", [])):
                cid=_global_id("raster-valve",aid,candidate["id"])
                self.db.execute("INSERT INTO raster_valve_candidate VALUES(?,?,?,?,?)",
                    (cid,aid,candidate["id"],candidate["page"],canonical_json(candidate)))
            self._append_event("RASTER_ANALYSIS_IMPORTED",aid,
                {"extraction_id":extraction_id,"result_hash":result["result_sha256"],
                 "stroke_count":len(result["stroke_candidates"]),
                 "filled_valve_count":len(result["filled_valve_candidates"]),
                 "outlined_valve_count":len(result.get("outline_valve_candidates", []))},now)
        return aid

    def get_raster_analysis(self, analysis_id: str) -> dict:
        r=self.db.execute("SELECT result_json FROM raster_analysis WHERE analysis_id=?",(analysis_id,)).fetchone()
        if r is None:
            raise KeyError("Raster analysis not found")
        return json.loads(r[0])

    def list_raster_valves(self, analysis_id: str, *, limit: int=200) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError("Raster candidate limit must be 1-1000")
        rows=self.db.execute("SELECT candidate_id,analysis_id,page,candidate_json FROM raster_valve_candidate "
                             "WHERE analysis_id=? ORDER BY page,candidate_id LIMIT ?",(analysis_id,limit))
        return [{"candidate_id":r[0],"analysis_id":r[1],"page":r[2],
                 "candidate":json.loads(r[3])} for r in rows]

    def review_raster_valve(self, candidate_id: str, *, actor: str, decision: str, reason: str) -> str:
        if decision not in {"ACCEPTED_AS_READING","REJECTED","UNRESOLVED"}:
            raise ValueError("Invalid raster review decision")
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError("Named raster reviewer required")
        if not isinstance(reason,str) or len(reason.strip())<5 or len(reason)>2000:
            raise ValueError("Detailed raster review reason required")
        if self.db.execute("SELECT 1 FROM raster_valve_candidate WHERE candidate_id=?",
                           (candidate_id,)).fetchone() is None:
            raise KeyError("Unknown raster valve proposal")
        rid="rdec-"+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute("INSERT INTO raster_valve_decision VALUES(?,?,?,?,?,?)",
                            (rid,candidate_id,actor,decision,reason.strip(),now))
            self._append_event("RASTER_VALVE_REVIEW",candidate_id,
                               {"decision_id":rid,"actor":actor.strip(),"decision":decision,
                                "reason":reason.strip()},now)
        return rid

    def latest_raster_review(self, candidate_id: str) -> dict | None:
        row=self.db.execute("SELECT * FROM raster_valve_decision WHERE candidate_id=? "
                            "ORDER BY rowid DESC LIMIT 1",(candidate_id,)).fetchone()
        return dict(row) if row else None

    # --- Rev U: derived raster role and possible contact proposals (standalone) ---

    def add_raster_network_analysis(self, extraction_id: str, raster_analysis_id: str,
                                    result: dict, ocr_analysis_id: str | None = None) -> str:
        from .raster_network import validate_raster_network
        row=self.db.execute("SELECT extraction_id FROM raster_analysis WHERE analysis_id=?",
                            (raster_analysis_id,)).fetchone()
        if row is None or row[0]!=extraction_id:
            raise ValueError('Raster analysis/extraction mismatch')
        raster=self.get_raster_analysis(raster_analysis_id)
        ocr=None
        if ocr_analysis_id is not None:
            check=self.db.execute("SELECT extraction_id FROM ocr_analysis WHERE analysis_id=?",
                                  (ocr_analysis_id,)).fetchone()
            if check is None or check[0]!=extraction_id:
                raise ValueError('OCR analysis/extraction mismatch')
            ocr=self.get_ocr_analysis(ocr_analysis_id)
        problems=validate_raster_network(result,raster,ocr)
        if problems:
            raise ValueError('Invalid derived raster evidence: '+'; '.join(problems[:3]))
        aid=_global_id('raster-network',extraction_id,raster_analysis_id,
                       ocr_analysis_id or '',result['result_sha256'])
        now=_utc()
        with self.db:
            if self.db.execute('SELECT 1 FROM raster_network_analysis WHERE analysis_id=?',(aid,)).fetchone():
                return aid
            self.db.execute('INSERT INTO raster_network_analysis VALUES(?,?,?,?,?,?,?)',
                            (aid,extraction_id,raster_analysis_id,ocr_analysis_id,
                             result['result_sha256'],canonical_json(result),now))
            for cand in result['contact_candidates']:
                cid=_global_id('raster-net-contact',aid,cand['id'])
                self.db.execute('INSERT INTO raster_network_candidate VALUES(?,?,?,?,?,?)',
                                (cid,aid,cand['id'],cand['page'],cand['kind'],canonical_json(cand)))
            self._append_event('RASTER_NETWORK_IMPORTED',aid,
                               {'extraction_id':extraction_id,'raster_analysis_id':raster_analysis_id,
                                'ocr_analysis_id':ocr_analysis_id,'result_hash':result['result_sha256'],
                                'contacts':len(result['contact_candidates'])},now)
        return aid

    def get_raster_network_analysis(self, analysis_id: str) -> dict:
        row=self.db.execute('SELECT result_json FROM raster_network_analysis WHERE analysis_id=?',(analysis_id,)).fetchone()
        if row is None:raise KeyError('Unknown raster network analysis')
        return json.loads(row[0])

    def list_raster_network_contacts(self, analysis_id: str, *, limit: int = 200) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError('Raster contact limit must be 1-1000')
        rows=self.db.execute('SELECT candidate_id,page,kind,candidate_json FROM raster_network_candidate '
                             'WHERE analysis_id=? ORDER BY page,candidate_id LIMIT ?', (analysis_id,limit))
        return [{'candidate_id':r[0],'analysis_id':analysis_id,'page':r[1],'kind':r[2],
                 'candidate':json.loads(r[3])} for r in rows]

    def review_raster_network_contact(self, candidate_id: str, *, actor: str, decision: str,
                                      reason: str) -> str:
        if decision not in {'CONTACT_AS_DRAWN','NOT_CONTACT_AS_DRAWN','UNRESOLVED','REJECTED'}:
            raise ValueError('Unknown raster contact review decision')
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError('Named raster contact reviewer required')
        if not isinstance(reason,str) or not 5<=len(reason.strip())<=2000:
            raise ValueError('Raster contact review requires an explanation')
        if self.db.execute('SELECT 1 FROM raster_network_candidate WHERE candidate_id=?',
                           (candidate_id,)).fetchone() is None:
            raise KeyError('Raster contact proposal not found')
        rid='rndec-'+uuid4().hex;now=_utc()
        with self.db:
            self.db.execute('INSERT INTO raster_network_decision VALUES(?,?,?,?,?,?)',
                            (rid,candidate_id,actor.strip(),decision,reason.strip(),now))
            self._append_event('RASTER_NETWORK_CONTACT_REVIEW',candidate_id,
                               {'decision_id':rid,'actor':actor.strip(),'decision':decision,
                                'reason':reason.strip()},now)
        return rid

    def latest_raster_network_review(self, candidate_id: str) -> dict | None:
        row=self.db.execute('SELECT * FROM raster_network_decision WHERE candidate_id=? '
                            'ORDER BY rowid DESC LIMIT 1',(candidate_id,)).fetchone()
        return dict(row) if row else None

    # --- Rev V: duplicate-supported raster centrelines and review-only gaps ---

    def add_raster_centreline_analysis(self, extraction_id: str, raster_analysis_id: str,
                                       network_analysis_id: str, result: dict) -> str:
        from .raster_centrelines import validate_raster_centrelines
        row=self.db.execute('SELECT extraction_id,raster_analysis_id FROM raster_network_analysis WHERE analysis_id=?',
                            (network_analysis_id,)).fetchone()
        if row is None or row[0]!=extraction_id or row[1]!=raster_analysis_id:
            raise ValueError('Raster network/extraction/source mismatch')
        raster=self.get_raster_analysis(raster_analysis_id)
        network=self.get_raster_network_analysis(network_analysis_id)
        # Trust no derived network merely because it has a rehashed JSON object.
        source_network=self.db.execute('SELECT ocr_analysis_id FROM raster_network_analysis WHERE analysis_id=?',
                                       (network_analysis_id,)).fetchone()
        from .raster_network import validate_raster_network
        ocr=self.get_ocr_analysis(source_network[0]) if source_network[0] else None
        if validate_raster_network(network,raster,ocr):
            raise ValueError('Raster network evidence validation failed')
        problems=validate_raster_centrelines(result,raster,network)
        if problems:raise ValueError('Invalid derived centreline evidence: '+'; '.join(problems[:2]))
        aid=_global_id('raster-centrelines',extraction_id,raster_analysis_id,network_analysis_id,result['result_sha256'])
        now=_utc()
        with self.db:
            if self.db.execute('SELECT 1 FROM raster_centreline_analysis WHERE analysis_id=?',(aid,)).fetchone():return aid
            self.db.execute('INSERT INTO raster_centreline_analysis VALUES(?,?,?,?,?,?,?)',
                            (aid,extraction_id,raster_analysis_id,network_analysis_id,
                             result['result_sha256'],canonical_json(result),now))
            for cand in result['gap_candidates']:
                cid=_global_id('raster-centreline-gap',aid,cand['id'])
                self.db.execute('INSERT INTO raster_centreline_gap VALUES(?,?,?,?,?)',
                                (cid,aid,cand['id'],cand['page'],canonical_json(cand)))
            self._append_event('RASTER_CENTRELINES_IMPORTED',aid,
                               {'extraction_id':extraction_id,'raster_analysis_id':raster_analysis_id,
                                'network_analysis_id':network_analysis_id,
                                'result_hash':result['result_sha256'],
                                'centrelines':len(result['centrelines']),
                                'gaps':len(result['gap_candidates'])},now)
        return aid

    def get_raster_centreline_analysis(self, analysis_id: str) -> dict:
        row=self.db.execute('SELECT result_json FROM raster_centreline_analysis WHERE analysis_id=?',(analysis_id,)).fetchone()
        if row is None:raise KeyError('Unknown raster centreline analysis')
        return json.loads(row[0])

    def list_raster_centreline_gaps(self, analysis_id: str, *, limit: int = 200) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=3500:raise ValueError('Gap list limit must be 1-3500')
        rows=self.db.execute('SELECT candidate_id,page,candidate_json FROM raster_centreline_gap '
                             'WHERE analysis_id=? ORDER BY page,candidate_id LIMIT ?',(analysis_id,limit))
        return [{'candidate_id':r[0],'analysis_id':analysis_id,'page':r[1],
                 'candidate':json.loads(r[2])} for r in rows]

    def review_raster_centreline_gap(self, candidate_id: str, *, actor: str,
                                     decision: str, reason: str) -> str:
        if decision not in {'CONTINUOUS_AS_DRAWN','SEPARATE_AS_DRAWN','UNRESOLVED','REJECTED'}:
            raise ValueError('Unknown centreline gap review decision')
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError('Named centreline gap reviewer required')
        if not isinstance(reason,str) or not 5<=len(reason.strip())<=2000:
            raise ValueError('Centreline gap review requires an explanation')
        if self.db.execute('SELECT 1 FROM raster_centreline_gap WHERE candidate_id=?',(candidate_id,)).fetchone() is None:
            raise KeyError('Unknown centreline gap candidate')
        rid='rcdec-'+uuid4().hex;now=_utc()
        with self.db:
            self.db.execute('INSERT INTO raster_centreline_decision VALUES(?,?,?,?,?,?)',
                            (rid,candidate_id,actor.strip(),decision,reason.strip(),now))
            self._append_event('RASTER_CENTRELINE_GAP_REVIEW',candidate_id,
                               {'decision_id':rid,'actor':actor.strip(),'decision':decision,
                                'reason':reason.strip()},now)
        return rid

    def latest_raster_centreline_review(self, candidate_id: str) -> dict | None:
        row=self.db.execute('SELECT * FROM raster_centreline_decision WHERE candidate_id=? '
                            'ORDER BY rowid DESC LIMIT 1',(candidate_id,)).fetchone()
        return dict(row) if row else None

    def list_objects(self, *, extraction_id: str | None = None, text: str = "", object_class: str = "", limit: int = 200) -> list[dict]:
        if limit < 1 or limit > 1000:
            raise ValueError("Limit out of permitted range")
        query = "SELECT observation_id,extraction_id,native_object_id,page,class,tag_text,bbox_json FROM observation WHERE 1=1"
        args: list = []
        if extraction_id:
            query += " AND extraction_id=?";args.append(extraction_id)
        if object_class:
            query += " AND class=?"; args.append(object_class)
        if text:
            query += " AND tag_text LIKE ? ESCAPE '\\'"; args.append("%"+text.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%")
        query += " ORDER BY page,tag_text,observation_id LIMIT ?";args.append(limit)
        return [dict(x) for x in self.db.execute(query,args).fetchall()]

    def get_object(self, observation_id: str) -> dict | None:
        r=self.db.execute("SELECT observation_json FROM observation WHERE observation_id=?",(observation_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def review(self, observation_id: str, *, actor: str, decision: str, reason: str, edited: dict | None = None) -> str:
        valid = {"ACCEPTED_AS_READING","EDITED_AND_ACCEPTED","REJECTED","IGNORED_REGION"}
        if decision not in valid:
            raise ValueError("Unsupported decision")
        if not actor.strip() or len(actor) > 150:
            raise ValueError("Named reviewer is required")
        if decision != "ACCEPTED_AS_READING" and len(reason.strip()) < 5:
            raise ValueError("Reason is required")
        if decision == "EDITED_AND_ACCEPTED" and not edited:
            raise ValueError("Edited values are required")
        if edited is not None and decision != "EDITED_AND_ACCEPTED":
            raise ValueError("Edits require EDITED_AND_ACCEPTED")
        if not self.get_object(observation_id):
            raise KeyError("Observation ID does not exist")
        decision_id = "dec-" + uuid4().hex
        now = _utc()
        with self.db:
            self.db.execute("INSERT INTO review_decision VALUES(?,?,?,?,?,?,?)",
                            (decision_id,observation_id,actor,decision,reason,canonical_json(edited) if edited else None,now))
            self._append_event("REVIEW_DECISION",observation_id,{"decision_id":decision_id,"actor":actor,"decision":decision,"reason":reason,"edited":edited},now)
        return decision_id

    def effective_review(self, observation_id: str) -> dict | None:
        row=self.db.execute("SELECT * FROM review_decision WHERE observation_id=? ORDER BY rowid DESC LIMIT 1",(observation_id,)).fetchone()
        return dict(row) if row else None

    def connected_to(self, observation_id: str) -> list[dict]:
        q = "SELECT edge_id,from_observation,to_observation,connection_type FROM graph_edge WHERE from_observation=? OR to_observation=? ORDER BY edge_id"
        return [dict(x) for x in self.db.execute(q,(observation_id,observation_id)).fetchall()]

    def export_extraction(self, extraction_id: str) -> dict:
        r=self.db.execute("SELECT result_json FROM extraction WHERE extraction_id=?",(extraction_id,)).fetchone()
        if not r:
            raise KeyError("Extraction not found")
        return json.loads(r[0])

    def add_geometry_analysis(self, extraction_id: str, result: dict) -> str:
        """Persist standalone drawing-geometry proposals only, not plant connectivity."""
        problems=validate_topology_result(result)
        if problems:
            raise ValueError("Invalid geometry result: " + "; ".join(problems[:5]))
        row=self.db.execute("SELECT document_sha256,result_json FROM extraction WHERE extraction_id=?",(extraction_id,)).fetchone()
        if row is None:raise KeyError("Unknown extraction ID")
        if row[0]!=result.get("source_sha256"):
            raise ValueError("Geometry source differs from extraction source")
        original=json.loads(row[1])
        included={x["page"] for x in original["pages"]}
        if not set(result.get("selected_pages",[])).issubset(included):
            raise ValueError("Geometry pages lie outside imported extraction selection")
        if result.get("schema")!="pid-reader-standalone-topology-v1":
            raise ValueError("Unsupported geometry result format")
        candidates=result.get("contact_candidates",[])
        if len({x["id"] for x in candidates})!=len(candidates):
            raise ValueError("Duplicate geometry candidate identifiers")
        aid=_global_id("geometry",extraction_id,result["result_sha256"])
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM geometry_analysis WHERE analysis_id=?",(aid,)).fetchone():
                return aid
            self.db.execute("INSERT INTO geometry_analysis VALUES(?,?,?,?,?,?)",
                (aid,extraction_id,result["algorithm"],result["result_sha256"],canonical_json(result),now))
            for c in candidates:
                cid=_global_id("contact",aid,c["id"])
                self.db.execute("INSERT INTO geometry_candidate VALUES(?,?,?,?,?,?)",
                    (cid,aid,c["id"],c["page"],c["kind"],canonical_json(c)))
            self._append_event("GEOMETRY_ANALYSIS_IMPORTED",aid,
                {"extraction_id":extraction_id,"result_hash":result["result_sha256"],"candidate_count":len(candidates)},now)
        return aid

    def list_geometry_candidates(self, analysis_id: str, *, kind: str="", limit: int=500) -> list[dict]:
        if not 1<=limit<=2000:raise ValueError("Geometry result limit must be 1–2000")
        query="SELECT candidate_id,analysis_id,page,kind,geometry_json FROM geometry_candidate WHERE analysis_id=?"
        args=[analysis_id]
        if kind:
            query+=" AND kind=?";args.append(kind)
        query+=" ORDER BY page,candidate_id LIMIT ?";args.append(limit)
        result=[]
        for row in self.db.execute(query,args):
            data=dict(row);data["geometry"]=json.loads(data.pop("geometry_json"));result.append(data)
        return result

    def review_geometry(self, candidate_id: str, *, actor: str, decision: str, reason: str) -> str:
        """Review what ink depicts, not whether the physical plant is connected."""
        valid={"CONNECTED_AS_DRAWN","NOT_CONNECTED_AS_DRAWN","UNRESOLVED","REJECTED"}
        if decision not in valid:raise ValueError("Unrecognised drawing geometry decision")
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError("Named reviewer is required")
        if not isinstance(reason,str) or len(reason.strip())<5:
            raise ValueError("Review reason must contain at least five characters")
        if not self.db.execute("SELECT 1 FROM geometry_candidate WHERE candidate_id=?",(candidate_id,)).fetchone():
            raise KeyError("Unknown geometry candidate ID")
        rid="gdec-"+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute("INSERT INTO geometry_decision VALUES(?,?,?,?,?,?)",
                (rid,candidate_id,actor,decision,reason,now))
            self._append_event("GEOMETRY_REVIEW",candidate_id,
                {"decision_id":rid,"actor":actor,"decision":decision,"reason":reason},now)
        return rid

    def latest_geometry_decision(self, candidate_id: str) -> dict | None:
        row=self.db.execute("SELECT * FROM geometry_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1",(candidate_id,)).fetchone()
        return dict(row) if row else None

    def get_geometry_analysis(self, analysis_id: str) -> dict:
        row=self.db.execute("SELECT result_json FROM geometry_analysis WHERE analysis_id=?",(analysis_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown geometry analysis")
        return json.loads(row[0])

    def add_symbol_analysis(self, extraction_id: str, geometry_analysis_id: str, result: dict) -> str:
        """Append standalone graphical hypotheses; never modify host extraction."""
        e=self.db.execute("SELECT result_json FROM extraction WHERE extraction_id=?",(extraction_id,)).fetchone()
        g=self.db.execute("SELECT extraction_id,result_json FROM geometry_analysis WHERE analysis_id=?",
                          (geometry_analysis_id,)).fetchone()
        if e is None or g is None or g[0]!=extraction_id:
            raise KeyError("Symbol sources are missing or unrelated")
        problems=validate_symbol_proposals(result,json.loads(e[0]),json.loads(g[1]))
        if problems:
            raise ValueError("Invalid symbol evidence: " + "; ".join(problems[:5]))
        aid=_global_id("symbol-analysis",extraction_id,geometry_analysis_id,result["result_sha256"])
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM symbol_analysis WHERE analysis_id=?",(aid,)).fetchone():
                return aid
            self.db.execute("INSERT INTO symbol_analysis VALUES(?,?,?,?,?,?,?)",
                (aid,extraction_id,geometry_analysis_id,result["algorithm"],result["result_sha256"],canonical_json(result),now))
            for candidate in result["symbol_candidates"]:
                cid=_global_id("symbol",aid,candidate["id"])
                self.db.execute("INSERT INTO symbol_candidate VALUES(?,?,?,?,?,?)",
                    (cid,aid,candidate["id"],candidate["page"],candidate["candidate_class"],canonical_json(candidate)))
            self._append_event("SYMBOL_ANALYSIS_IMPORTED",aid,
                {"extraction_id":extraction_id,"geometry_analysis_id":geometry_analysis_id,
                 "result_hash":result["result_sha256"],"symbol_count":len(result["symbol_candidates"]),
                 "port_count":len(result["port_candidates"])},now)
        return aid

    def list_symbol_candidates(self, analysis_id: str, *, limit: int=200, candidate_class: str="") -> list[dict]:
        if not 1<=limit<=2000:
            raise ValueError("Symbol result limit must be 1 to 2000")
        query="SELECT candidate_id,analysis_id,page,candidate_class,candidate_json FROM symbol_candidate WHERE analysis_id=?"
        values=[analysis_id]
        if candidate_class:
            query+=" AND candidate_class=?";values.append(candidate_class)
        query+=" ORDER BY page,candidate_id LIMIT ?";values.append(limit)
        return [{**dict(r),"candidate":json.loads(r["candidate_json"])} for r in self.db.execute(query,values)]

    def get_symbol_analysis(self, analysis_id: str) -> dict:
        r=self.db.execute("SELECT result_json FROM symbol_analysis WHERE analysis_id=?",(analysis_id,)).fetchone()
        if r is None:raise KeyError("Unknown symbol analysis")
        return json.loads(r[0])

    def review_symbol(self, candidate_id: str, *, actor: str, decision: str,
                      reason: str, edited: dict | None = None) -> str:
        decisions={"ACCEPTED_AS_READING","EDITED_AND_ACCEPTED","REJECTED","UNRESOLVED"}
        if decision not in decisions:
            raise ValueError("Unsupported symbol review decision")
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError("Named reviewer is required")
        if not isinstance(reason,str) or len(reason.strip())<5:
            raise ValueError("An evidence/review reason of five characters is required")
        if decision=="EDITED_AND_ACCEPTED" and (not isinstance(edited,dict) or not edited):
            raise ValueError("An explicit edited value is required")
        if edited is not None and decision!="EDITED_AND_ACCEPTED":
            raise ValueError("Edits require EDITED_AND_ACCEPTED")
        if not self.db.execute("SELECT 1 FROM symbol_candidate WHERE candidate_id=?",(candidate_id,)).fetchone():
            raise KeyError("Unknown symbol candidate")
        rid="sdec-"+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute("INSERT INTO symbol_decision VALUES(?,?,?,?,?,?,?)",
                (rid,candidate_id,actor,decision,reason,canonical_json(edited) if edited else None,now))
            self._append_event("SYMBOL_REVIEW",candidate_id,
                {"decision_id":rid,"actor":actor,"decision":decision,"reason":reason,"edited":edited},now)
        return rid

    def latest_symbol_review(self, candidate_id: str) -> dict | None:
        r=self.db.execute("SELECT * FROM symbol_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1",(candidate_id,)).fetchone()
        return dict(r) if r else None

    def backup(self, destination: str | Path) -> Path:
        """Create a consistent, independently openable project backup."""
        target=Path(destination)
        if target.resolve()==self.path.resolve():raise ValueError("Backup cannot overwrite source project")
        if target.exists():raise FileExistsError("Backup destination exists")
        target.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(target) as copy:
            self.db.backup(copy)
        return target

    def add_linework_analysis(self, extraction_id: str, geometry_analysis_id: str,
                              symbol_analysis_id: str, result: dict) -> str:
        """Append immutable standalone vector-linework hypotheses. Host R1 is untouched."""
        from .linework import validate_linework_proposals
        e=self.db.execute("SELECT result_json FROM extraction WHERE extraction_id=?",(extraction_id,)).fetchone()
        g=self.db.execute("SELECT extraction_id,result_json FROM geometry_analysis WHERE analysis_id=?",
                          (geometry_analysis_id,)).fetchone()
        s=self.db.execute("SELECT extraction_id,geometry_analysis_id,result_json FROM symbol_analysis WHERE analysis_id=?",
                          (symbol_analysis_id,)).fetchone()
        if e is None or g is None or s is None or g[0]!=extraction_id or s[0]!=extraction_id or s[1]!=geometry_analysis_id:
            raise KeyError("Linework input analyses are missing or refer to different sources")
        problems=validate_linework_proposals(result,json.loads(e[0]),json.loads(g[1]),json.loads(s[2]))
        if problems:
            raise ValueError("Invalid linework evidence: " + "; ".join(problems[:5]))
        aid=_global_id("linework-analysis",extraction_id,geometry_analysis_id,symbol_analysis_id,result["result_sha256"])
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM linework_analysis WHERE analysis_id=?",(aid,)).fetchone():
                return aid
            self.db.execute("INSERT INTO linework_analysis VALUES(?,?,?,?,?,?,?,?)",
                (aid,extraction_id,geometry_analysis_id,symbol_analysis_id,result["algorithm"],
                 result["result_sha256"],canonical_json(result),now))
            for valve in result["valve_candidates"]:
                cid=_global_id("valve",aid,valve["id"])
                self.db.execute("INSERT INTO linework_candidate VALUES(?,?,?,?,?,?)",
                                (cid,aid,valve["id"],valve["page"],valve["kind"],canonical_json(valve)))
            for contact in result["mixed_style_contacts"]:
                cid=_global_id("linecontact",aid,contact["id"])
                self.db.execute("INSERT INTO linework_candidate VALUES(?,?,?,?,?,?)",
                                (cid,aid,contact["id"],contact["page"],"MIXED_STYLE_CONTACT",canonical_json(contact)))
            self._append_event("LINEWORK_ANALYSIS_IMPORTED",aid,
                {"extraction_id":extraction_id,"geometry_analysis_id":geometry_analysis_id,
                 "symbol_analysis_id":symbol_analysis_id,"result_hash":result["result_sha256"],
                 "valve_count":len(result["valve_candidates"]),
                 "port_count":len(result["valve_port_candidates"])},now)
        return aid

    def get_linework_analysis(self, analysis_id: str) -> dict:
        r=self.db.execute("SELECT result_json FROM linework_analysis WHERE analysis_id=?",(analysis_id,)).fetchone()
        if r is None:raise KeyError("Unknown linework analysis")
        return json.loads(r[0])

    def list_linework_candidates(self, analysis_id: str, *, kind: str="", limit: int=200) -> list[dict]:
        if not 1<=limit<=2000:raise ValueError("Linework result limit must be 1-2000")
        sql="SELECT candidate_id,analysis_id,page,kind,candidate_json FROM linework_candidate WHERE analysis_id=?"
        values=[analysis_id]
        if kind:
            sql+=" AND kind=?";values.append(kind)
        sql+=" ORDER BY page,candidate_id LIMIT ?";values.append(limit)
        return [{**dict(r),"candidate":json.loads(r["candidate_json"])} for r in self.db.execute(sql,values)]

    def review_linework(self, candidate_id: str, *, actor: str, decision: str, reason: str) -> str:
        if decision not in {"ACCEPTED_AS_READING","REJECTED","UNRESOLVED"}:
            raise ValueError("Unsupported linework review decision")
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError("Named reviewer is required")
        if not isinstance(reason,str) or len(reason.strip())<5:
            raise ValueError("Review reason must be at least five characters")
        if not self.db.execute("SELECT 1 FROM linework_candidate WHERE candidate_id=?",(candidate_id,)).fetchone():
            raise KeyError("Unknown linework candidate")
        rid="ldec-"+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute("INSERT INTO linework_decision VALUES(?,?,?,?,?,?)",
                (rid,candidate_id,actor,decision,reason,now))
            self._append_event("LINEWORK_REVIEW",candidate_id,
                {"decision_id":rid,"actor":actor,"decision":decision,"reason":reason},now)
        return rid

    def latest_linework_review(self, candidate_id: str) -> dict | None:
        r=self.db.execute("SELECT * FROM linework_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1",
                          (candidate_id,)).fetchone()
        return dict(r) if r else None

    def trace_drawing(self, linework_analysis_id: str, start_segment_id: str, *,
                      include_unreviewed: bool=False, max_hops: int=15) -> dict:
        """Graph query using only the current geometry review history; no host writes."""
        from .drawing_graph import trace_drawing_segments
        row=self.db.execute("SELECT geometry_analysis_id,result_json FROM linework_analysis WHERE analysis_id=?",
                            (linework_analysis_id,)).fetchone()
        if row is None:raise KeyError("Unknown linework analysis")
        geometry_id=row[0]
        geometry=self.get_geometry_analysis(geometry_id)
        reviews={}
        # Each geometry candidate's foreign-key ID is local. Map to its native
        # immutable contact identifier before looking up the latest decision.
        for cid,native in self.db.execute("SELECT candidate_id,native_candidate_id FROM geometry_candidate WHERE analysis_id=?",
                                          (geometry_id,)):
            rowdec=self.db.execute("SELECT decision FROM geometry_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1",
                                   (cid,)).fetchone()
            if rowdec:
                reviews[native]=rowdec[0]
        return trace_drawing_segments(geometry,json.loads(row[1]),reviews,start_segment_id,
                                     include_unreviewed=include_unreviewed,max_hops=max_hops)

    # --- Rev K: standalone-only OCR evidence and symbol-tag alternatives ---

    def add_ocr_analysis(self, extraction_id: str, result: dict) -> str:
        """Store verified OCR proposal words; does not alter R1 extraction objects."""
        from .text_links import validate_ocr_source
        row=self.db.execute("SELECT result_json,document_sha256 FROM extraction WHERE extraction_id=?",(extraction_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown OCR source extraction")
        extraction=json.loads(row[0])
        source=self.get_source_pdf(row[1])
        if source is None or hashlib.sha256(source).hexdigest()!=row[1]:
            raise ValueError("Immutable source bytes are required for OCR evidence")
        problems=validate_ocr_source(result,extraction)
        if not problems:
            from ..formats.ocr_source import validate_ocr_frame_for_pdf
            problems=validate_ocr_frame_for_pdf(result,source)
        if problems:
            raise ValueError("Invalid OCR evidence: " + "; ".join(problems[:5]))
        aid=_global_id("ocr-analysis",extraction_id,result["result_sha256"])
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM ocr_analysis WHERE analysis_id=?",(aid,)).fetchone():
                return aid
            self.db.execute("INSERT INTO ocr_analysis VALUES(?,?,?,?,?,?)",
                            (aid,extraction_id,result["engine_version"],result["result_sha256"],canonical_json(result),now))
            n=0
            for page in result["pages"]:
                for word in page["words"]:
                    wid=_global_id("ocr-word",aid,word["id"])
                    self.db.execute("INSERT INTO ocr_word VALUES(?,?,?,?,?,?,?)",
                                    (wid,aid,word["id"],page["page"],word["text"],canonical_json(word["bbox"]),canonical_json(word)))
                    n+=1
            self._append_event("OCR_ANALYSIS_IMPORTED",aid,
                {"extraction_id":extraction_id,"ocr_result_hash":result["result_sha256"],"word_count":n},now)
        return aid

    def get_ocr_analysis(self, analysis_id: str) -> dict:
        r=self.db.execute("SELECT result_json FROM ocr_analysis WHERE analysis_id=?",(analysis_id,)).fetchone()
        if r is None:
            raise KeyError("Unknown OCR analysis")
        return json.loads(r[0])

    def list_ocr_words(self, analysis_id: str, *, text: str="", limit: int=200) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=2000:
            raise ValueError("OCR word limit must be 1 to 2000")
        sql="SELECT word_id,native_word_id,page,text,bbox_json FROM ocr_word WHERE analysis_id=?"
        args=[analysis_id]
        if text:
            sql+=" AND text LIKE ? ESCAPE '\\'"
            args.append("%"+text.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%")
        sql+=" ORDER BY page,word_id LIMIT ?";args.append(limit)
        rows=[]
        for row in self.db.execute(sql,args):
            o=dict(row);o["bbox"]=json.loads(o.pop("bbox_json"));rows.append(o)
        return rows

    def add_text_link_analysis(self, extraction_id: str, symbol_analysis_id: str, ocr_analysis_id: str,
                               result: dict) -> str:
        from .text_links import validate_text_links
        e=self.db.execute("SELECT result_json FROM extraction WHERE extraction_id=?",(extraction_id,)).fetchone()
        s=self.db.execute("SELECT extraction_id,result_json FROM symbol_analysis WHERE analysis_id=?",(symbol_analysis_id,)).fetchone()
        o=self.db.execute("SELECT extraction_id,result_json FROM ocr_analysis WHERE analysis_id=?",(ocr_analysis_id,)).fetchone()
        if e is None or s is None or o is None or s[0]!=extraction_id or o[0]!=extraction_id:
            raise KeyError("Text association requires related, persisted source evidence")
        problems=validate_text_links(result,json.loads(e[0]),json.loads(s[1]),json.loads(o[1]))
        if problems:
            raise ValueError("Invalid source-derived text associations: " + "; ".join(problems[:4]))
        aid=_global_id("text-links",extraction_id,symbol_analysis_id,ocr_analysis_id,result["result_sha256"])
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM text_link_analysis WHERE analysis_id=?",(aid,)).fetchone():
                return aid
            self.db.execute("INSERT INTO text_link_analysis VALUES(?,?,?,?,?,?,?)",
                (aid,extraction_id,symbol_analysis_id,ocr_analysis_id,result["result_sha256"],canonical_json(result),now))
            # Map original source-derived symbol IDs to local immutable records.
            sym_index={r["native_candidate_id"]:r["candidate_id"] for r in self.db.execute(
                "SELECT candidate_id,native_candidate_id FROM symbol_candidate WHERE analysis_id=?",(symbol_analysis_id,))}
            for proposal in result["proposals"]:
                symid=sym_index.get(proposal["symbol_id"])
                if symid is None:
                    raise ValueError("Proposed text link references a missing symbol")
                pid=_global_id("text-proposal",aid,proposal["id"])
                self.db.execute("INSERT INTO text_link_proposal VALUES(?,?,?,?,?,?)",
                                (pid,aid,proposal["id"],symid,proposal["page"],canonical_json(proposal)))
            self._append_event("TEXT_LINKS_IMPORTED",aid,
                {"extraction_id":extraction_id,"symbol_analysis_id":symbol_analysis_id,
                 "ocr_analysis_id":ocr_analysis_id,"result_hash":result["result_sha256"],
                 "proposals":len(result["proposals"])},now)
        return aid

    def get_text_link_analysis(self, analysis_id: str) -> dict:
        r=self.db.execute("SELECT result_json FROM text_link_analysis WHERE analysis_id=?",(analysis_id,)).fetchone()
        if r is None:raise KeyError("Unknown text link analysis")
        return json.loads(r[0])

    def list_text_link_proposals(self, analysis_id: str, *, limit: int=200, state: str="") -> list[dict]:
        if type(limit) is not int or not 1<=limit<=2000:
            raise ValueError("Text-link result limit must be 1 to 2000")
        rows=self.db.execute("SELECT proposal_id,symbol_candidate_id,page,proposal_json FROM text_link_proposal "
                             "WHERE analysis_id=? ORDER BY page,proposal_id LIMIT ?",(analysis_id,limit)).fetchall()
        out=[]
        for r in rows:
            prop=json.loads(r["proposal_json"])
            if not state or prop["association_state"]==state:
                out.append({"proposal_id":r["proposal_id"],"symbol_candidate_id":r["symbol_candidate_id"],
                            "page":r["page"],"proposal":prop})
        return out

    def review_text_link(self, proposal_id: str, *, actor: str, decision: str, reason: str,
                         selected_text: str | None=None) -> str:
        allowed={"ACCEPTED_AS_READING","EDITED_AND_ACCEPTED","REJECTED","UNRESOLVED"}
        if decision not in allowed:
            raise ValueError("Unsupported text association review decision")
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError("Named reviewer required")
        if not isinstance(reason,str) or len(reason.strip())<5:
            raise ValueError("Reason of at least five characters required")
        row=self.db.execute("SELECT proposal_json FROM text_link_proposal WHERE proposal_id=?",(proposal_id,)).fetchone()
        if row is None:raise KeyError("Unknown text association proposal")
        options={x["text_candidate"] for x in json.loads(row[0])["options"]}
        if decision=="ACCEPTED_AS_READING":
            if not isinstance(selected_text,str) or selected_text not in options:
                raise ValueError("Acceptance requires an exact existing source-linked text option")
        elif decision=="EDITED_AND_ACCEPTED":
            if not isinstance(selected_text,str) or not selected_text.strip() or len(selected_text)>200:
                raise ValueError("Edited acceptance requires explicit replacement text")
        elif selected_text is not None:
            raise ValueError("Rejected/unresolved proposals cannot also set a selected text")
        rid="tdec-"+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute("INSERT INTO text_link_decision VALUES(?,?,?,?,?,?,?)",
                (rid,proposal_id,actor,decision,selected_text,reason,now))
            self._append_event("TEXT_LINK_REVIEW",proposal_id,
                {"decision_id":rid,"actor":actor,"decision":decision,
                 "selected_text":selected_text,"reason":reason},now)
        return rid

    def latest_text_link_review(self, proposal_id: str) -> dict | None:
        row=self.db.execute("SELECT * FROM text_link_decision WHERE proposal_id=? ORDER BY rowid DESC LIMIT 1",(proposal_id,)).fetchone()
        return dict(row) if row else None

    def symbol_evidence(self, text_link_analysis_id: str, symbol_candidate_id: str) -> dict:
        """Join source observations, possible ports and reviewed text *as drawn*.

        Not a physical connectivity graph: ports and text remain independent
        proposals, with no inferred instrument loop, line continuity or IPL role.
        """
        row=self.db.execute("SELECT t.extraction_id,t.symbol_analysis_id,t.ocr_analysis_id,"
                            " p.proposal_id,p.proposal_json,s.candidate_json "
                            "FROM text_link_analysis t JOIN text_link_proposal p ON p.analysis_id=t.analysis_id "
                            "JOIN symbol_candidate s ON s.candidate_id=p.symbol_candidate_id "
                            "WHERE t.analysis_id=? AND p.symbol_candidate_id=?",
                            (text_link_analysis_id,symbol_candidate_id)).fetchone()
        if row is None:raise KeyError("Symbol is not part of the selected text link analysis")
        extraction=self.export_extraction(row["extraction_id"])
        sym=json.loads(row["candidate_json"])
        proposal=json.loads(row["proposal_json"])
        sres=self.get_symbol_analysis(row["symbol_analysis_id"])
        return {"kind":"SOURCE_LINKED_SYMBOL_EVIDENCE", "source_sha256":extraction["document"]["sha256"],
                "extraction_id":row["extraction_id"],"text_link_analysis_id":text_link_analysis_id,
                "page":proposal["page"],"symbol_candidate_id":symbol_candidate_id,
                "symbol":sym,"symbol_review":self.latest_symbol_review(symbol_candidate_id),
                "text_options":proposal["options"],"text_review":self.latest_text_link_review(row["proposal_id"]),
                "possible_port_contacts":[p for p in sres["port_candidates"] if p["symbol_id"]==sym["id"]][:200],
                "limitations":("All coordinates refer to the cited source PDF. Neither matching tags nor outline contacts "
                               "establish engineering function, independent protection or installed plant connectivity.")}


    # Rev L: standalone signal-style and project-tag hypotheses.
    def add_signal_analysis(self, extraction_id: str, geometry_analysis_id: str,
                            symbol_analysis_id: str, linework_analysis_id: str, result: dict) -> str:
        from .signal_links import validate_signal_links
        for table, aid in (("geometry_analysis", geometry_analysis_id),
                           ("symbol_analysis", symbol_analysis_id),
                           ("linework_analysis", linework_analysis_id)):
            found=self.db.execute(f"SELECT extraction_id FROM {table} WHERE analysis_id=?",(aid,)).fetchone()
            if found is None or found[0] != extraction_id:
                raise KeyError("Signal relationships require source-related persisted analyses")
        extraction=self.export_extraction(extraction_id)
        topology=self.get_geometry_analysis(geometry_analysis_id)
        symbols=self.get_symbol_analysis(symbol_analysis_id)
        linework=self.get_linework_analysis(linework_analysis_id)
        errors=validate_signal_links(result,extraction,topology,symbols,linework)
        if errors: raise ValueError("Invalid signal evidence: "+"; ".join(errors[:3]))
        aid=_global_id("sig-analysis",extraction_id,geometry_analysis_id,symbol_analysis_id,
                       linework_analysis_id,result["result_sha256"])
        native_symbols={x["native_candidate_id"]:x["candidate_id"] for x in self.db.execute(
            "SELECT candidate_id,native_candidate_id FROM symbol_candidate WHERE analysis_id=?",(symbol_analysis_id,))}
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM signal_analysis WHERE analysis_id=?",(aid,)).fetchone():
                return aid
            self.db.execute("INSERT INTO signal_analysis VALUES(?,?,?,?,?,?,?,?)",
                (aid,extraction_id,geometry_analysis_id,symbol_analysis_id,linework_analysis_id,
                 result["result_sha256"],canonical_json(result),now))
            for item in result["candidates"]:
                cid=_global_id("sig-candidate",aid,item["id"])
                symid=native_symbols[item["symbol_id"]]
                self.db.execute("INSERT INTO signal_candidate VALUES(?,?,?,?,?,?)",
                    (cid,aid,item["id"],symid,item["page"],canonical_json(item)))
            self._append_event("SIGNAL_PROPOSALS_IMPORTED",aid,
                 {"extraction_id":extraction_id,"result_hash":result["result_sha256"],
                  "candidate_count":len(result["candidates"])},now)
        return aid

    def get_signal_analysis(self, analysis_id: str) -> dict:
        row=self.db.execute("SELECT result_json FROM signal_analysis WHERE analysis_id=?",(analysis_id,)).fetchone()
        if row is None: raise KeyError("Unknown signal analysis")
        return json.loads(row[0])

    def list_signal_candidates(self, analysis_id: str, *, limit: int=200) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=2000:
            raise ValueError("Invalid signal candidate limit")
        rows=self.db.execute("SELECT candidate_id,symbol_candidate_id,page,candidate_json FROM signal_candidate "
                             "WHERE analysis_id=? ORDER BY page,candidate_id LIMIT ?",(analysis_id,limit))
        return [{"candidate_id":r[0],"symbol_candidate_id":r[1],"page":r[2],
                 "candidate":json.loads(r[3]),"latest_review":self.latest_signal_review(r[0])} for r in rows]

    def review_signal(self, candidate_id: str, *, actor: str, decision: str, reason: str) -> str:
        valid={"SUPPORTED_AS_DRAWN","NOT_CONNECTED_AS_DRAWN","UNRESOLVED","REJECTED"}
        if decision not in valid: raise ValueError("Unknown signal review decision")
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError("Named reviewer required")
        if not isinstance(reason,str) or len(reason.strip())<5:
            raise ValueError("Specific review reason required")
        if not self.db.execute("SELECT 1 FROM signal_candidate WHERE candidate_id=?",(candidate_id,)).fetchone():
            raise KeyError("Unknown signal proposal")
        rid="sigdec-"+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute("INSERT INTO signal_decision VALUES(?,?,?,?,?,?)",
                (rid,candidate_id,actor,decision,reason,now))
            self._append_event("SIGNAL_DRAWING_REVIEW",candidate_id,
                {"decision_id":rid,"actor":actor,"decision":decision,"reason":reason},now)
        return rid

    def latest_signal_review(self, candidate_id: str) -> dict | None:
        row=self.db.execute("SELECT * FROM signal_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1",(candidate_id,)).fetchone()
        return dict(row) if row else None

    def register_tag_profile(self, profile: dict) -> str:
        from .tag_profiles import profile_hash
        h=profile_hash(profile)
        pid=_global_id("tag-profile",h)
        now=_utc()
        with self.db:
            if self.db.execute("SELECT 1 FROM tag_profile WHERE profile_id=?",(pid,)).fetchone():return pid
            self.db.execute("INSERT INTO tag_profile VALUES(?,?,?,?)",(pid,h,canonical_json(profile),now))
            self._append_event("TAG_PROFILE_REGISTERED",pid,{"hash":h,"name":profile["name"],"version":profile["version"]},now)
        return pid

    def get_tag_profile(self, profile_id: str) -> dict:
        row=self.db.execute("SELECT profile_json FROM tag_profile WHERE profile_id=?",(profile_id,)).fetchone()
        if row is None:raise KeyError("Unknown tag profile")
        return json.loads(row[0])

    def evaluate_tag_profile(self, text_link_analysis_id: str, profile_id: str) -> tuple[str,dict]:
        from .tag_profiles import evaluate_text_links,validate_profiled_tags
        links=self.get_text_link_analysis(text_link_analysis_id)
        profile=self.get_tag_profile(profile_id)
        result=evaluate_text_links(links,profile)
        errors=validate_profiled_tags(result,links)
        if errors: raise ValueError("Invalid tag profile evaluation: "+"; ".join(errors))
        eid=_global_id("tag-evaluation",text_link_analysis_id,profile_id,result["result_sha256"])
        now=_utc()
        with self.db:
            if not self.db.execute("SELECT 1 FROM tag_profile_evaluation WHERE evaluation_id=?",(eid,)).fetchone():
                self.db.execute("INSERT INTO tag_profile_evaluation VALUES(?,?,?,?,?,?)",
                    (eid,text_link_analysis_id,profile_id,result["result_sha256"],canonical_json(result),now))
                self._append_event("TAG_PROFILE_EVALUATED",eid,
                  {"profile_id":profile_id,"text_link_analysis_id":text_link_analysis_id,
                   "result_hash":result["result_sha256"]},now)
        return eid,result

    # --- Rev M: explicit signal-path tracing and multi-P&ID drawing-set catalogue ---
    def trace_signal(self, signal_analysis_id: str, start_segment_id: str, *,
                     include_unreviewed: bool=False, max_hops: int=15,
                     persist: bool=False) -> dict:
        """Return drawn-dash graph, never a control-loop or installed wiring claim."""
        from .signal_paths import trace_signal_path
        row=self.db.execute('SELECT extraction_id,geometry_analysis_id,symbol_analysis_id,linework_analysis_id '
                            'FROM signal_analysis WHERE analysis_id=?',(signal_analysis_id,)).fetchone()
        if row is None:
            raise KeyError('Unknown signal analysis')
        extraction=self.export_extraction(row['extraction_id'])
        geometry=self.get_geometry_analysis(row['geometry_analysis_id'])
        symbols=self.get_symbol_analysis(row['symbol_analysis_id'])
        linework=self.get_linework_analysis(row['linework_analysis_id'])
        signals=self.get_signal_analysis(signal_analysis_id)
        greviews={}
        for r in self.db.execute('SELECT candidate_id,native_candidate_id FROM geometry_candidate WHERE analysis_id=?',
                                 (row['geometry_analysis_id'],)):
            last=self.latest_geometry_decision(r['candidate_id'])
            if last:greviews[r['native_candidate_id']]=last['decision']
        sreviews={}
        for r in self.db.execute('SELECT candidate_id,native_candidate_id FROM signal_candidate WHERE analysis_id=?',
                                 (signal_analysis_id,)):
            last=self.latest_signal_review(r['candidate_id'])
            if last:sreviews[r['native_candidate_id']]=last['decision']
        result=trace_signal_path(extraction,geometry,symbols,linework,signals,greviews,sreviews,
                                 start_segment_id,include_unreviewed=include_unreviewed,max_hops=max_hops)
        if persist:
            rid=_global_id('sig-trace',signal_analysis_id,result['result_sha256'])
            now=_utc()
            with self.db:
                if not self.db.execute('SELECT 1 FROM signal_trace_snapshot WHERE trace_id=?',(rid,)).fetchone():
                    self.db.execute('INSERT INTO signal_trace_snapshot VALUES(?,?,?,?,?)',
                                    (rid,signal_analysis_id,result['result_sha256'],canonical_json(result),now))
                    self._append_event('SIGNAL_TRACE_SNAPSHOT',rid,
                                       {'signal_analysis_id':signal_analysis_id,'result_sha256':result['result_sha256']},now)
            result['persisted_trace_id']=rid
        return result

    def get_signal_trace_snapshot(self, trace_id: str) -> dict:
        r=self.db.execute('SELECT result_json FROM signal_trace_snapshot WHERE trace_id=?',(trace_id,)).fetchone()
        if r is None:raise KeyError('Unknown signal trace snapshot')
        return json.loads(r[0])

    @staticmethod
    def _checked_text(value: str, field: str, max_length: int=140) -> str:
        if not isinstance(value,str) or not 1<=len(value.strip())<=max_length:
            raise ValueError(f'{field} must be non-empty and <= {max_length} characters')
        if any(ord(c)<32 for c in value):
            raise ValueError(f'{field} contains invalid control characters')
        return value.strip()

    def register_drawing(self, extraction_id: str, *, drawing_no: str, revision_label: str,
                         facility: str, area: str, actor: str, reason: str) -> str:
        """Append a document catalogue interpretation; do not infer latest revision."""
        if not self.db.execute('SELECT 1 FROM extraction WHERE extraction_id=?',(extraction_id,)).fetchone():
            raise KeyError('Unknown extraction revision')
        values=[self._checked_text(v,n) for n,v in (
            ('drawing number',drawing_no),('revision',revision_label),('facility',facility),
            ('area',area),('reviewer',actor),('reason',reason))]
        rid='drawing-reg-'+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute('INSERT INTO drawing_registration VALUES(?,?,?,?,?,?,?,?,?)',
                            (rid,extraction_id,*values,now))
            self._append_event('DRAWING_REGISTERED',rid,
                               {'extraction_id':extraction_id,'drawing_no':values[0],
                                'revision_label':values[1],'actor':values[4]},now)
        return rid

    def list_drawings(self, *, search: str='', limit: int=200) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid catalogue limit')
        if not isinstance(search,str) or len(search)>200:raise ValueError('Invalid search')
        # Last appended metadata record per extraction; preserves earlier revisions.
        sql='''SELECT r.*,e.document_sha256,d.source_name,d.page_count FROM drawing_registration r
          JOIN extraction e ON e.extraction_id=r.extraction_id
          JOIN document_revision d ON d.sha256=e.document_sha256
          WHERE r.rowid=(SELECT MAX(r2.rowid) FROM drawing_registration r2 WHERE r2.extraction_id=r.extraction_id)'''
        args=[]
        if search:
            escaped=search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            sql+=" AND (r.drawing_no LIKE ? ESCAPE '\\' OR r.facility LIKE ? ESCAPE '\\' OR r.area LIKE ? ESCAPE '\\')"
            args.extend(['%'+escaped+'%']*3)
        sql+=' ORDER BY r.facility,r.area,r.drawing_no,r.revision_label,r.extraction_id LIMIT ?'
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql,args)]

    def annotate_offpage(self, extraction_id: str, *, page: int, bbox: dict,
                         label: str, actor: str, reason: str) -> str:
        row=self.db.execute('SELECT document_sha256,result_json FROM extraction WHERE extraction_id=?',(extraction_id,)).fetchone()
        if row is None:raise KeyError('Unknown extraction')
        extraction=json.loads(row['result_json'])
        if type(page) is not int or page not in [p['page'] for p in extraction['pages']]:
            raise ValueError('Page is not within the source extraction')
        from math import isfinite
        if not isinstance(bbox,dict) or set(bbox)!={'x0','y0','x1','y1'}:
            raise ValueError('Source bounding box must have four normalized coordinates')
        if any(type(bbox[k]) not in (int,float) or not isfinite(bbox[k]) or not 0<=bbox[k]<=1
               for k in bbox):
            raise ValueError('Source bounding box must be finite and normalized')
        if bbox['x0']>=bbox['x1'] or bbox['y0']>=bbox['y1']:
            raise ValueError('Source bounding box must enclose a region')
        label=self._checked_text(label,'connector label',120)
        actor=self._checked_text(actor,'annotator')
        reason=self._checked_text(reason,'annotation reason',300)
        aid='offpage-'+uuid4().hex
        now=_utc()
        with self.db:
            self.db.execute('INSERT INTO offpage_annotation VALUES(?,?,?,?,?,?,?,?,?)',
                            (aid,extraction_id,page,canonical_json(bbox),label,row['document_sha256'],actor,reason,now))
            self._append_event('OFFPAGE_ANNOTATED',aid,
                               {'extraction_id':extraction_id,'source_sha256':row['document_sha256'],
                                'label':label,'page':page,'bbox':bbox,'actor':actor},now)
        return aid

    def list_offpage_annotations(self, *, extraction_id: str|None=None, limit: int=500) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=5000:
            raise ValueError('Invalid connector listing limit')
        sql='SELECT * FROM offpage_annotation WHERE 1=1'
        args=[]
        if extraction_id:
            sql+=' AND extraction_id=?';args.append(extraction_id)
        sql+=' ORDER BY created_utc,annotation_id LIMIT ?';args.append(limit)
        return [{**dict(r),'bbox':json.loads(r['bbox_json'])} for r in self.db.execute(sql,args)]

    def analyze_crosssheet(self, extraction_ids: list[str]) -> tuple[str,dict]:
        """Snapshot proposed cross-drawing matches from explicitly annotated regions."""
        from .project_links import build_crosssheet_matches
        if not isinstance(extraction_ids,list) or len(extraction_ids)<2 or len(extraction_ids)>500 or len(set(extraction_ids))!=len(extraction_ids):
            raise ValueError('Select two to 500 unique registered extractions')
        catalog={r['extraction_id']:r for r in self.list_drawings(limit=1000)}
        if not set(extraction_ids).issubset(catalog):
            raise ValueError('All selected drawing revisions must be registered')
        sources={eid:catalog[eid]['document_sha256'] for eid in extraction_ids}
        # Only the explicit drawing set supplied to the analysis participates.
        marks=[]
        for eid in sorted(extraction_ids):
            for r in self.list_offpage_annotations(extraction_id=eid,limit=5000):
                marks.append({k:r[k] for k in ('annotation_id','extraction_id','source_sha256','label')})
        drawing_snapshot={eid:{k:catalog[eid][k] for k in
                          ('registration_id','drawing_no','revision_label','facility','area','document_sha256')}
                          for eid in sorted(extraction_ids)}
        result=build_crosssheet_matches(marks,extraction_ids,sources,drawing_snapshot)
        aid=_global_id('crosssheet-analysis',result['result_sha256'])
        now=_utc()
        with self.db:
            if self.db.execute('SELECT 1 FROM crosssheet_analysis WHERE analysis_id=?',(aid,)).fetchone():
                return aid,result
            self.db.execute('INSERT INTO crosssheet_analysis VALUES(?,?,?,?)',
                            (aid,result['result_sha256'],canonical_json(result),now))
            for item in result['candidates']:
                cid=_global_id('crosssheet-candidate',aid,item['id'])
                self.db.execute('INSERT INTO crosssheet_candidate VALUES(?,?,?,?,?,?)',
                                (cid,aid,item['from_annotation_id'],item['to_annotation_id'],
                                 item['id'],canonical_json(item)))
            self._append_event('CROSSSHEET_PROPOSALS_IMPORTED',aid,
                               {'source_hashes':sources,'count':len(result['candidates'])},now)
        return aid,result

    def list_crosssheet_candidates(self, analysis_id: str, *, limit: int=500) -> list[dict]:
        if type(limit) is not int or not 1<=limit<=2000:
            raise ValueError('Invalid match listing limit')
        rows=self.db.execute('SELECT candidate_id,candidate_json FROM crosssheet_candidate WHERE analysis_id=? ORDER BY candidate_id LIMIT ?',
                             (analysis_id,limit))
        return [{'candidate_id':r['candidate_id'],'proposal':json.loads(r['candidate_json']),
                 'latest_review':self.latest_crosssheet_review(r['candidate_id'])} for r in rows]

    def latest_crosssheet_review(self, candidate_id: str) -> dict|None:
        r=self.db.execute('SELECT * FROM crosssheet_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1',
                          (candidate_id,)).fetchone()
        return dict(r) if r else None

    def review_crosssheet(self, candidate_id: str, *, actor: str, decision: str, reason: str) -> str:
        allowed={'LINKED_AS_DRAWN','NOT_LINKED_AS_DRAWN','UNRESOLVED','REJECTED'}
        if decision not in allowed:
            raise ValueError('Invalid crosssheet decision')
        actor=self._checked_text(actor,'reviewer');reason=self._checked_text(reason,'reason',300)
        if not self.db.execute('SELECT 1 FROM crosssheet_candidate WHERE candidate_id=?',(candidate_id,)).fetchone():
            raise KeyError('Unknown crosssheet candidate')
        now=_utc();did='crosssheet-decision-'+uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO crosssheet_decision VALUES(?,?,?,?,?,?)',
                            (did,candidate_id,actor,decision,reason,now))
            self._append_event('CROSSSHEET_DECISION',did,
                               {'candidate_id':candidate_id,'actor':actor,'decision':decision,'reason':reason},now)
        return did

    def trace_drawings(self, analysis_id: str, start_extraction_id: str, *,
                       include_unreviewed: bool=False, max_hops: int=12) -> dict:
        """Traverse *document reference hypotheses*, not plant piping."""
        from collections import defaultdict,deque
        if type(max_hops) is not int or not 0<=max_hops<=40:
            raise ValueError('Invalid document graph depth')
        if type(include_unreviewed) is not bool:
            raise ValueError('Invalid proposal mode')
        row=self.db.execute('SELECT result_json FROM crosssheet_analysis WHERE analysis_id=?',(analysis_id,)).fetchone()
        if row is None:raise KeyError('Unknown crosssheet analysis')
        snapshot=json.loads(row['result_json'])
        selected=set(snapshot['selected_extractions'])
        if start_extraction_id not in selected:
            raise ValueError('Starting drawing was not selected for analysis')
        adjacency=defaultdict(list)
        for r in self.db.execute('SELECT candidate_id,candidate_json FROM crosssheet_candidate WHERE analysis_id=?',(analysis_id,)):
            item=json.loads(r['candidate_json'])
            last=self.latest_crosssheet_review(r['candidate_id'])
            state=last['decision'] if last else 'PROPOSED_UNVERIFIED'
            if state in ('REJECTED','NOT_LINKED_AS_DRAWN'):
                continue
            if state!='LINKED_AS_DRAWN' and not include_unreviewed:
                continue
            a,b=item['from_extraction_id'],item['to_extraction_id']
            edge={'candidate_id':r['candidate_id'],'label':item['label'],'from_extraction_id':a,
                  'to_extraction_id':b, 'state':('REVIEWED_MATCH_AS_DRAWN' if state=='LINKED_AS_DRAWN'
                                              else 'UNREVIEWED_MATCH_PROPOSAL'),
                  'from_source_sha256':item['from_source_sha256'],
                  'to_source_sha256':item['to_source_sha256']}
            adjacency[a].append((b,edge));adjacency[b].append((a,edge))
        visited={start_extraction_id:0};edges={};queue=deque([start_extraction_id])
        while queue:
            here=queue.popleft()
            if visited[here]>=max_hops:continue
            for dest,edge in sorted(adjacency[here],key=lambda x:(x[0],x[1]['candidate_id'])):
                edges[edge['candidate_id']]=edge
                if dest not in visited:
                    visited[dest]=visited[here]+1;queue.append(dest)
            if len(visited)>500 or len(edges)>10000:raise ValueError('Document graph budget exceeded')
        catalog=snapshot.get('drawing_catalogue_snapshot') or {r['extraction_id']:r for r in self.list_drawings(limit=1000)}
        return {'kind':'DRAWING_REFERENCE_GRAPH','analysis_id':analysis_id,
                'start_extraction_id':start_extraction_id,'include_unreviewed':include_unreviewed,
                'documents':[{'extraction_id':eid,'hops':hops,
                              'drawing_no':catalog[eid]['drawing_no'],'revision_label':catalog[eid]['revision_label'],
                              'source_sha256':catalog[eid]['document_sha256']} for eid,hops in sorted(visited.items())],
                'links':sorted(edges.values(),key=lambda x:x['candidate_id']),
                'limitations':'Explicitly reviewed drawing reference matches only; not plant connectivity or verified installed assets.'}

    # Rev N: Training-free, versioned standalone symbol template catalogues.
    def register_symbol_catalogue(self, catalogue:dict)->str:
        from .symbol_catalog import validate_catalog
        problems=validate_catalog(catalogue)
        if problems:raise ValueError('Invalid symbol catalogue: '+'; '.join(problems[:3]))
        content=canonical_json(catalogue)
        digest=hashlib.sha256(content.encode('utf-8')).hexdigest()
        cid=_global_id('symbol-catalogue',digest)
        now=_utc()
        with self.db:
            if self.db.execute('SELECT 1 FROM symbol_catalogue WHERE catalogue_id=?',(cid,)).fetchone():
                return cid
            self.db.execute('INSERT INTO symbol_catalogue VALUES(?,?,?,?)',(cid,digest,content,now))
            self._append_event('SYMBOL_CATALOGUE_REGISTERED',cid,
                               {'sha256':digest,'name':catalogue['catalogue_name'],'revision':catalogue['revision']},now)
        return cid

    def get_symbol_catalogue(self,catalogue_id:str)->dict:
        row=self.db.execute('SELECT catalog_json FROM symbol_catalogue WHERE catalogue_id=?',(catalogue_id,)).fetchone()
        if row is None:raise KeyError('Unknown symbol catalogue')
        return json.loads(row[0])

    def analyze_symbol_catalogue(self, extraction_id:str, geometry_analysis_id:str,
                                symbol_analysis_id:str, linework_analysis_id:str,
                                catalogue_id:str)->tuple[str,dict]:
        from .symbol_catalog import build_catalog_analysis, validate_catalog_analysis
        e_row=self.db.execute('SELECT result_json FROM extraction WHERE extraction_id=?',(extraction_id,)).fetchone()
        g_row=self.db.execute('SELECT extraction_id,result_json FROM geometry_analysis WHERE analysis_id=?',(geometry_analysis_id,)).fetchone()
        s_row=self.db.execute('SELECT extraction_id,geometry_analysis_id,result_json FROM symbol_analysis WHERE analysis_id=?',(symbol_analysis_id,)).fetchone()
        l_row=self.db.execute('SELECT extraction_id,geometry_analysis_id,symbol_analysis_id,result_json FROM linework_analysis WHERE analysis_id=?',(linework_analysis_id,)).fetchone()
        if (e_row is None or g_row is None or s_row is None or l_row is None
            or g_row[0]!=extraction_id or s_row[0]!=extraction_id or s_row[1]!=geometry_analysis_id
            or l_row[0]!=extraction_id or l_row[1]!=geometry_analysis_id or l_row[2]!=symbol_analysis_id):
            raise ValueError('Missing or inconsistent upstream extraction layers')
        e,g,sy,lw=(json.loads(e_row[0]),json.loads(g_row[1]),json.loads(s_row[2]),json.loads(l_row[3]))
        catalog=self.get_symbol_catalogue(catalogue_id)
        result=build_catalog_analysis(e,g,sy,lw,catalog)
        if validate_catalog_analysis(result,e,g,sy,lw,catalog):
            raise ValueError('Symbol catalogue analysis failed source validation')
        analysis_id=_global_id('catalog-analysis',extraction_id,geometry_analysis_id,symbol_analysis_id,
                               linework_analysis_id,catalogue_id,result['result_sha256'])
        now=_utc()
        with self.db:
            if self.db.execute('SELECT 1 FROM catalog_analysis WHERE analysis_id=?',(analysis_id,)).fetchone():
                return analysis_id,result
            self.db.execute('INSERT INTO catalog_analysis VALUES(?,?,?,?,?,?,?,?,?)',
                            (analysis_id,extraction_id,geometry_analysis_id,symbol_analysis_id,
                             linework_analysis_id,catalogue_id,result['result_sha256'],canonical_json(result),now))
            for candidate in result['candidates']:
                item_id=_global_id('catalog-candidate',analysis_id,candidate['id'])
                self.db.execute('INSERT INTO catalog_candidate VALUES(?,?,?,?,?,?)',
                                (item_id,analysis_id,candidate['id'],candidate['page'],
                                 candidate['candidate_class'],canonical_json(candidate)))
            self._append_event('SYMBOL_CATALOGUE_ANALYSIS',analysis_id,
                               {'catalogue_id':catalogue_id,'extraction_id':extraction_id,
                                'result_sha256':result['result_sha256'],'count':len(result['candidates'])},now)
        return analysis_id,result

    def get_symbol_catalogue_analysis(self,analysis_id:str)->dict:
        row=self.db.execute('SELECT result_json FROM catalog_analysis WHERE analysis_id=?',(analysis_id,)).fetchone()
        if row is None:raise KeyError('Unknown catalogue analysis')
        return json.loads(row[0])

    def list_catalogue_candidates(self,analysis_id:str,*,candidate_class:str='',limit:int=200)->list[dict]:
        if not 1<=limit<=2000:raise ValueError('Result limit must be 1-2000')
        sql='SELECT * FROM catalog_candidate WHERE analysis_id=?';params=[analysis_id]
        if candidate_class:
            sql+=' AND candidate_class=?';params.append(candidate_class)
        sql+=' ORDER BY page,candidate_id LIMIT ?';params.append(limit)
        return [{**dict(row),'candidate':json.loads(row['candidate_json'])} for row in self.db.execute(sql,params)]

    def review_catalogue_candidate(self,candidate_id:str,*,actor:str,decision:str,
                                   reason:str,edited:dict|None=None)->str:
        if decision not in {'ACCEPTED_AS_READING','EDITED_AND_ACCEPTED','REJECTED','UNRESOLVED'}:
            raise ValueError('Unsupported catalogue review decision')
        if not isinstance(actor,str) or not actor.strip() or len(actor)>150:
            raise ValueError('Named reviewer required')
        if not isinstance(reason,str) or len(reason.strip())<5 or len(reason)>1000:
            raise ValueError('Review reason must be 5-1000 characters')
        if decision=='EDITED_AND_ACCEPTED' and (not isinstance(edited,dict) or not edited):
            raise ValueError('Edited payload is required')
        if edited is not None and decision!='EDITED_AND_ACCEPTED':
            raise ValueError('Edits require EDITED_AND_ACCEPTED')
        if not self.db.execute('SELECT 1 FROM catalog_candidate WHERE candidate_id=?',(candidate_id,)).fetchone():
            raise KeyError('Unknown catalogue candidate')
        rid='cdec-'+uuid4().hex;now=_utc()
        with self.db:
            self.db.execute('INSERT INTO catalog_decision VALUES(?,?,?,?,?,?,?)',
                            (rid,candidate_id,actor,decision,reason,canonical_json(edited) if edited else None,now))
            self._append_event('SYMBOL_CATALOGUE_REVIEW',candidate_id,
                               {'decision_id':rid,'actor':actor,'decision':decision,
                                'reason':reason,'edited':edited},now)
        return rid

    def latest_catalogue_review(self,candidate_id:str)->dict|None:
        row=self.db.execute('SELECT * FROM catalog_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1',(candidate_id,)).fetchone()
        return dict(row) if row else None

    # Rev O: batch jobs and source-revision comparisons are STANDALONE ONLY.
    def create_batch(self, manifest: list[dict], *, actor: str, params: dict) -> str:
        from .batch import MAX_FILES
        if not isinstance(manifest,list) or not 1<=len(manifest)<=MAX_FILES:
            raise ValueError('Invalid batch manifest size')
        actor=self._checked_text(actor,'batch initiator')
        from ..api import ReadParams
        ReadParams(**params).validate()
        checked=[]
        seen=set()
        for index, entry in enumerate(manifest):
            if not isinstance(entry,dict) or set(entry) != {'path','name','sha256','size_bytes','preflight_error'}:
                raise ValueError('Invalid batch entry')
            if (not isinstance(entry['path'],str) or not isinstance(entry['name'],str) or
                not entry['path'] or not entry['name'] or entry['path'] in seen or
                type(entry['size_bytes']) is not int or entry['size_bytes']<0 or
                entry['preflight_error'] not in (None, 'PID_LIMIT_BYTES')):
                raise ValueError('Invalid batch entry values')
            if (entry['preflight_error'] is None and (not isinstance(entry['sha256'],str) or
                len(entry['sha256'])!=64 or any(c not in '0123456789abcdef' for c in entry['sha256']))) or (entry['preflight_error'] and entry['sha256'] is not None):
                raise ValueError('Invalid batch source digest')
            checked.append({'ordinal':index,**entry})
            seen.add(entry['path'])
        now=_utc();bid='batch-'+uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO batch_import_run VALUES(?,?,?,?,?)',
                            (bid,actor,canonical_json(checked),canonical_json(params),now))
            self._append_event('BATCH_CREATED',bid,
                               {'actor':actor,'manifest_hash':hashlib.sha256(canonical_json(checked).encode()).hexdigest(),
                                'count':len(checked)},now)
        return bid

    def record_batch_outcome(self, batch_id: str, *, ordinal: int, status: str,
                             extraction_id: str|None, detail: str) -> str:
        if status not in ('IMPORTED','FAILED') or type(ordinal) is not int:
            raise ValueError('Invalid batch outcome')
        if not isinstance(detail,str) or len(detail)>500:
            raise ValueError('Invalid batch detail')
        row=self.db.execute('SELECT manifest_json FROM batch_import_run WHERE batch_id=?',(batch_id,)).fetchone()
        if row is None:raise KeyError('Unknown batch')
        if not 0<=ordinal<len(json.loads(row[0])):
            raise ValueError('Batch ordinal outside original manifest')
        if status=='IMPORTED' and not extraction_id or status=='FAILED' and extraction_id is not None:
            raise ValueError('Invalid status/extraction pairing')
        if extraction_id and not self.db.execute('SELECT 1 FROM extraction WHERE extraction_id=?',(extraction_id,)).fetchone():
            raise ValueError('Unknown imported extraction')
        now=_utc();oid='batch-outcome-'+uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO batch_import_outcome VALUES(?,?,?,?,?,?,?)',
                            (oid,batch_id,ordinal,status,extraction_id,detail,now))
            self._append_event('BATCH_ITEM_RECORDED',oid,
                               {'batch_id':batch_id,'ordinal':ordinal,'status':status,
                                'extraction_id':extraction_id,'detail':detail},now)
        return oid

    def get_batch(self,batch_id:str) -> dict:
        row=self.db.execute('SELECT * FROM batch_import_run WHERE batch_id=?',(batch_id,)).fetchone()
        if row is None:raise KeyError('Unknown batch')
        outcome=[dict(r) for r in self.db.execute('SELECT * FROM batch_import_outcome WHERE batch_id=? ORDER BY ordinal',(batch_id,))]
        entries=json.loads(row['manifest_json'])
        completed={r['ordinal'] for r in outcome}
        state=('INCOMPLETE' if len(completed)<len(entries) else
               ('COMPLETE_WITH_FAILURES' if any(r['status']=='FAILED' for r in outcome) else 'COMPLETE'))
        return {'batch_id':batch_id,'actor':row['actor'],'created_utc':row['created_utc'],
                'params':json.loads(row['params_json']),'manifest':entries,'outcomes':outcome,
                'completed_ordinals':sorted(completed),'state':state,
                'counts':{'total':len(entries),'completed':len(outcome),
                          'imported':sum(r['status']=='IMPORTED' for r in outcome),
                          'failed':sum(r['status']=='FAILED' for r in outcome)}}

    def compare_revisions(self, before_extraction_id: str, after_extraction_id: str) -> tuple[str,dict]:
        from .revisions import compare_extractions
        old=self.export_extraction(before_extraction_id)
        new=self.export_extraction(after_extraction_id)
        def selected_registration(extraction_id):
            row=self.db.execute('SELECT registration_id,drawing_no,revision_label,facility,area '
                                'FROM drawing_registration WHERE extraction_id=? ORDER BY rowid DESC LIMIT 1',
                                (extraction_id,)).fetchone()
            return dict(row) if row else None
        result=compare_extractions(old,new,selected_registration(before_extraction_id),
                                   selected_registration(after_extraction_id))
        digest=result['result_sha256']
        cid=_global_id('revision-diff',before_extraction_id,after_extraction_id,digest)
        now=_utc()
        with self.db:
            if not self.db.execute('SELECT 1 FROM revision_comparison WHERE comparison_id=?',(cid,)).fetchone():
                self.db.execute('INSERT INTO revision_comparison VALUES(?,?,?,?,?,?)',
                                (cid,before_extraction_id,after_extraction_id,digest,canonical_json(result),now))
                self._append_event('REVISION_COMPARISON_RECORDED',cid,
                                   {'before':before_extraction_id,'after':after_extraction_id,'result_sha256':digest},now)
        return cid,result

    def get_revision_comparison(self, comparison_id:str)->dict:
        row=self.db.execute('SELECT result_json FROM revision_comparison WHERE comparison_id=?',(comparison_id,)).fetchone()
        if row is None:raise KeyError('Unknown comparison')
        result=json.loads(row[0])
        digest=result.pop('result_sha256')
        if hashlib.sha256(canonical_json(result).encode()).hexdigest()!=digest:
            raise ValueError('Stored comparison result failed hash verification')
        result['result_sha256']=digest
        return result

    def search_project(self, *, tag: str='', object_class: str='', drawing_no: str='',
                       facility: str='', limit: int=200) -> list[dict]:
        """Read-only source-backed index; never asserts accepted physical assets."""
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError('Invalid search limit')
        for name,val in [('tag',tag),('object_class',object_class),('drawing_no',drawing_no),('facility',facility)]:
            if not isinstance(val,str) or len(val)>140:
                raise ValueError('Invalid '+name)
        # Latest *catalogue metadata* is selected separately; original extraction is immutable.
        sql='''SELECT o.observation_id,o.extraction_id,o.page,o.class,o.tag_text,o.bbox_json,
             e.document_sha256,json_extract(e.result_json,'$.document.filename') AS source_name,r.drawing_no,r.revision_label,r.facility,r.area,
             (SELECT rd.decision FROM review_decision rd WHERE rd.observation_id=o.observation_id ORDER BY rd.rowid DESC LIMIT 1) AS latest_reading_review
             FROM observation o JOIN extraction e ON e.extraction_id=o.extraction_id
             JOIN document_revision d ON d.sha256=e.document_sha256
             LEFT JOIN drawing_registration r ON r.registration_id=(SELECT r2.registration_id FROM drawing_registration r2 WHERE r2.extraction_id=o.extraction_id ORDER BY r2.rowid DESC LIMIT 1)
             WHERE 1=1'''
        args=[]
        if tag:
            sql+=" AND o.tag_text LIKE ? ESCAPE '\\'";args.append('%'+tag.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        if object_class:
            sql+=' AND o.class=?';args.append(object_class)
        if drawing_no:
            sql+=' AND r.drawing_no=?';args.append(drawing_no)
        if facility:
            sql+=' AND r.facility=?';args.append(facility)
        sql+=' ORDER BY r.facility,r.area,r.drawing_no,o.page,o.tag_text,o.observation_id LIMIT ?';args.append(limit)
        return [dict(row) for row in self.db.execute(sql,args)]
