"""Standalone additive database changes. Never used on the Worksheet host DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

LATEST_SCHEMA = 13

MIGRATION_2 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS geometry_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  algorithm TEXT NOT NULL,
  result_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  imported_utc TEXT NOT NULL,
  UNIQUE(extraction_id, algorithm, result_hash)
);
CREATE TABLE IF NOT EXISTS geometry_candidate (
  candidate_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES geometry_analysis(analysis_id),
  native_candidate_id TEXT NOT NULL,
  page INTEGER NOT NULL,
  kind TEXT NOT NULL,
  geometry_json TEXT NOT NULL,
  UNIQUE(analysis_id,native_candidate_id)
);
CREATE INDEX IF NOT EXISTS ix_geometry_analysis_extraction ON geometry_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_geometry_candidate_analysis ON geometry_candidate(analysis_id);
CREATE INDEX IF NOT EXISTS ix_geometry_candidate_kind ON geometry_candidate(kind);
CREATE TABLE IF NOT EXISTS geometry_decision (
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES geometry_candidate(candidate_id),
  actor TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('CONNECTED_AS_DRAWN','NOT_CONNECTED_AS_DRAWN','UNRESOLVED','REJECTED')),
  reason TEXT NOT NULL,
  created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_geometry_review_candidate ON geometry_decision(candidate_id);
-- Append-only triggers, mirroring standalone v1 immutability.
CREATE TRIGGER IF NOT EXISTS block_update_geometry_analysis BEFORE UPDATE ON geometry_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_geometry_analysis BEFORE DELETE ON geometry_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_geometry_candidate BEFORE UPDATE ON geometry_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_geometry_candidate BEFORE DELETE ON geometry_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_geometry_decision BEFORE UPDATE ON geometry_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_geometry_decision BEFORE DELETE ON geometry_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='2' WHERE key='standalone_schema' AND value='1';
COMMIT;
"""



MIGRATION_3 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS symbol_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  geometry_analysis_id TEXT NOT NULL REFERENCES geometry_analysis(analysis_id),
  algorithm TEXT NOT NULL, result_hash TEXT NOT NULL,
  result_json TEXT NOT NULL, imported_utc TEXT NOT NULL,
  UNIQUE(extraction_id, geometry_analysis_id, result_hash)
);
CREATE TABLE IF NOT EXISTS symbol_candidate (
  candidate_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES symbol_analysis(analysis_id),
  native_candidate_id TEXT NOT NULL, page INTEGER NOT NULL, candidate_class TEXT NOT NULL,
  candidate_json TEXT NOT NULL, UNIQUE(analysis_id,native_candidate_id)
);
CREATE TABLE IF NOT EXISTS symbol_decision (
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES symbol_candidate(candidate_id),
  actor TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('ACCEPTED_AS_READING','EDITED_AND_ACCEPTED','REJECTED','UNRESOLVED')),
  reason TEXT NOT NULL, edited_json TEXT, created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_symbol_analysis_extraction ON symbol_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_symbol_candidate_analysis ON symbol_candidate(analysis_id);
CREATE INDEX IF NOT EXISTS ix_symbol_candidate_class ON symbol_candidate(candidate_class);
CREATE INDEX IF NOT EXISTS ix_symbol_decision_candidate ON symbol_decision(candidate_id);
CREATE TRIGGER IF NOT EXISTS block_update_symbol_analysis BEFORE UPDATE ON symbol_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_symbol_analysis BEFORE DELETE ON symbol_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_symbol_candidate BEFORE UPDATE ON symbol_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_symbol_candidate BEFORE DELETE ON symbol_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_symbol_decision BEFORE UPDATE ON symbol_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_symbol_decision BEFORE DELETE ON symbol_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='3' WHERE key='standalone_schema' AND value='2';
COMMIT;
"""

def upgrade(db: sqlite3.Connection, path: Path, *, existed_before_open: bool) -> Path | None:
    row=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
    if not row:
        raise ValueError("Missing standalone schema metadata; refusing to guess")
    version=int(row[0])
    if version> LATEST_SCHEMA:
        raise ValueError(f"Database schema {version} is newer than this reader supports")
    if version<1:
        raise ValueError("Invalid project schema version")
    backup_path=None
    if version < LATEST_SCHEMA and existed_before_open:
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path=path.with_name(path.name+f".pre-v{LATEST_SCHEMA}-{stamp}.sqlite")
        with sqlite3.connect(backup_path) as target:
            db.backup(target)
    if version==1:
        try:
            db.executescript(MIGRATION_2)
        except Exception:
            if db.in_transaction:db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='2':
            raise ValueError("Standalone migration did not complete")
    if version<=2:
        try:
            db.executescript(MIGRATION_3)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='3':
            raise ValueError("Standalone symbol migration did not complete")
    if version<=3:
        try:
            db.executescript(MIGRATION_4)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='4':
            raise ValueError("Standalone linework migration did not complete")
    if version<=4:
        try:
            db.executescript(MIGRATION_5)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='5':
            raise ValueError("Standalone OCR/text-link migration did not complete")
    if version<=5:
        try:
            db.executescript(MIGRATION_6)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='6':
            raise ValueError("Standalone signal/tag profile migration did not complete")
    if version<=6:
        try:
            db.executescript(MIGRATION_7)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='7':
            raise ValueError("Standalone drawing-set migration did not complete")
    if version<=7:
        try:
            db.executescript(MIGRATION_8)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='8':
            raise ValueError("Standalone symbol catalogue migration did not complete")
    if version<=8:
        try:
            db.executescript(MIGRATION_9)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='9':
            raise ValueError('Standalone batch/comparison migration did not complete')
    if version<=9:
        try:
            db.executescript(MIGRATION_10)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='10':
            raise ValueError('Standalone raster evidence migration did not complete')
    if version<=10:
        try:
            db.executescript(MIGRATION_11)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='11':
            raise ValueError('Standalone raster network migration did not complete')
    if version<=11:
        try:
            db.executescript(MIGRATION_12)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='12':
            raise ValueError('Standalone centreline migration did not complete')
    if version<=12:
        try:
            db.executescript(MIGRATION_13)
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        check=db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()
        if check is None or check[0]!='13':
            raise ValueError('Standalone engineering-intelligence migration did not complete')
    return backup_path

MIGRATION_4 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS linework_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  geometry_analysis_id TEXT NOT NULL REFERENCES geometry_analysis(analysis_id),
  symbol_analysis_id TEXT NOT NULL REFERENCES symbol_analysis(analysis_id),
  algorithm TEXT NOT NULL, result_hash TEXT NOT NULL,
  result_json TEXT NOT NULL, imported_utc TEXT NOT NULL,
  UNIQUE(extraction_id,geometry_analysis_id,symbol_analysis_id,result_hash)
);
CREATE TABLE IF NOT EXISTS linework_candidate (
  candidate_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES linework_analysis(analysis_id),
  native_candidate_id TEXT NOT NULL, page INTEGER NOT NULL,
  kind TEXT NOT NULL, candidate_json TEXT NOT NULL,
  UNIQUE(analysis_id,native_candidate_id)
);
CREATE TABLE IF NOT EXISTS linework_decision (
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES linework_candidate(candidate_id),
  actor TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('ACCEPTED_AS_READING','REJECTED','UNRESOLVED')),
  reason TEXT NOT NULL, created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_linework_analysis_extraction ON linework_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_linework_candidate_analysis ON linework_candidate(analysis_id);
CREATE INDEX IF NOT EXISTS ix_linework_candidate_kind ON linework_candidate(kind);
CREATE INDEX IF NOT EXISTS ix_linework_decision_candidate ON linework_decision(candidate_id);
CREATE TRIGGER IF NOT EXISTS block_update_linework_analysis BEFORE UPDATE ON linework_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_linework_analysis BEFORE DELETE ON linework_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_linework_candidate BEFORE UPDATE ON linework_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_linework_candidate BEFORE DELETE ON linework_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_linework_decision BEFORE UPDATE ON linework_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_linework_decision BEFORE DELETE ON linework_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='4' WHERE key='standalone_schema' AND value='3';
COMMIT;
"""


MIGRATION_5 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS ocr_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  engine_version TEXT NOT NULL, result_hash TEXT NOT NULL,
  result_json TEXT NOT NULL, imported_utc TEXT NOT NULL,
  UNIQUE(extraction_id,result_hash)
);
CREATE TABLE IF NOT EXISTS ocr_word (
  word_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES ocr_analysis(analysis_id),
  native_word_id TEXT NOT NULL, page INTEGER NOT NULL,
  text TEXT NOT NULL, bbox_json TEXT NOT NULL, word_json TEXT NOT NULL,
  UNIQUE(analysis_id,native_word_id)
);
CREATE TABLE IF NOT EXISTS text_link_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  symbol_analysis_id TEXT NOT NULL REFERENCES symbol_analysis(analysis_id),
  ocr_analysis_id TEXT NOT NULL REFERENCES ocr_analysis(analysis_id),
  result_hash TEXT NOT NULL, result_json TEXT NOT NULL, imported_utc TEXT NOT NULL,
  UNIQUE(symbol_analysis_id,ocr_analysis_id,result_hash)
);
CREATE TABLE IF NOT EXISTS text_link_proposal (
  proposal_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES text_link_analysis(analysis_id),
  native_proposal_id TEXT NOT NULL,
  symbol_candidate_id TEXT NOT NULL REFERENCES symbol_candidate(candidate_id),
  page INTEGER NOT NULL, proposal_json TEXT NOT NULL,
  UNIQUE(analysis_id,native_proposal_id)
);
CREATE TABLE IF NOT EXISTS text_link_decision (
  decision_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES text_link_proposal(proposal_id),
  actor TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('ACCEPTED_AS_READING','EDITED_AND_ACCEPTED','REJECTED','UNRESOLVED')),
  selected_text TEXT, reason TEXT NOT NULL, created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ocr_analysis_source ON ocr_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_ocr_word_page ON ocr_word(analysis_id,page);
CREATE INDEX IF NOT EXISTS ix_ocr_word_text ON ocr_word(text);
CREATE INDEX IF NOT EXISTS ix_text_link_source ON text_link_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_text_link_proposal_sym ON text_link_proposal(symbol_candidate_id);
CREATE INDEX IF NOT EXISTS ix_text_link_decision_prop ON text_link_decision(proposal_id);
CREATE TRIGGER IF NOT EXISTS block_update_ocr_analysis BEFORE UPDATE ON ocr_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_ocr_analysis BEFORE DELETE ON ocr_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_ocr_word BEFORE UPDATE ON ocr_word BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_ocr_word BEFORE DELETE ON ocr_word BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_text_link_analysis BEFORE UPDATE ON text_link_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_text_link_analysis BEFORE DELETE ON text_link_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_text_link_proposal BEFORE UPDATE ON text_link_proposal BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_text_link_proposal BEFORE DELETE ON text_link_proposal BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_text_link_decision BEFORE UPDATE ON text_link_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_text_link_decision BEFORE DELETE ON text_link_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='5' WHERE key='standalone_schema' AND value='4';
COMMIT;
"""

MIGRATION_6 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS signal_analysis (
 analysis_id TEXT PRIMARY KEY,
 extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
 geometry_analysis_id TEXT NOT NULL REFERENCES geometry_analysis(analysis_id),
 symbol_analysis_id TEXT NOT NULL REFERENCES symbol_analysis(analysis_id),
 linework_analysis_id TEXT NOT NULL REFERENCES linework_analysis(analysis_id),
 result_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_utc TEXT NOT NULL,
 UNIQUE(extraction_id,geometry_analysis_id,symbol_analysis_id,linework_analysis_id,result_hash)
);
CREATE TABLE IF NOT EXISTS signal_candidate (
 candidate_id TEXT PRIMARY KEY,
 analysis_id TEXT NOT NULL REFERENCES signal_analysis(analysis_id),
 native_candidate_id TEXT NOT NULL,
 symbol_candidate_id TEXT NOT NULL REFERENCES symbol_candidate(candidate_id),
 page INTEGER NOT NULL, candidate_json TEXT NOT NULL,
 UNIQUE(analysis_id,native_candidate_id)
);
CREATE TABLE IF NOT EXISTS signal_decision (
 decision_id TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL REFERENCES signal_candidate(candidate_id),
 actor TEXT NOT NULL, decision TEXT NOT NULL,
 reason TEXT NOT NULL, created_utc TEXT NOT NULL,
 CHECK(decision IN ('SUPPORTED_AS_DRAWN','NOT_CONNECTED_AS_DRAWN','UNRESOLVED','REJECTED'))
);
CREATE TABLE IF NOT EXISTS tag_profile (
 profile_id TEXT PRIMARY KEY, profile_sha256 TEXT NOT NULL UNIQUE,
 profile_json TEXT NOT NULL, created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tag_profile_evaluation (
 evaluation_id TEXT PRIMARY KEY,
 text_link_analysis_id TEXT NOT NULL REFERENCES text_link_analysis(analysis_id),
 profile_id TEXT NOT NULL REFERENCES tag_profile(profile_id),
 result_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_utc TEXT NOT NULL,
 UNIQUE(text_link_analysis_id,profile_id,result_hash)
);
CREATE INDEX IF NOT EXISTS ix_signal_analysis_extraction ON signal_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_signal_candidate_analysis ON signal_candidate(analysis_id,page);
CREATE INDEX IF NOT EXISTS ix_signal_decision_candidate ON signal_decision(candidate_id);
CREATE INDEX IF NOT EXISTS ix_profile_evaluation_text ON tag_profile_evaluation(text_link_analysis_id);
CREATE TRIGGER IF NOT EXISTS block_update_signal_analysis BEFORE UPDATE ON signal_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_signal_analysis BEFORE DELETE ON signal_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_signal_candidate BEFORE UPDATE ON signal_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_signal_candidate BEFORE DELETE ON signal_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_signal_decision BEFORE UPDATE ON signal_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_signal_decision BEFORE DELETE ON signal_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_tag_profile BEFORE UPDATE ON tag_profile BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_tag_profile BEFORE DELETE ON tag_profile BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_tag_profile_evaluation BEFORE UPDATE ON tag_profile_evaluation BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_tag_profile_evaluation BEFORE DELETE ON tag_profile_evaluation BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='6' WHERE key='standalone_schema' AND value='5';
COMMIT;
"""

MIGRATION_7 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS drawing_registration (
 registration_id TEXT PRIMARY KEY,
 extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
 drawing_no TEXT NOT NULL, revision_label TEXT NOT NULL,
 facility TEXT NOT NULL, area TEXT NOT NULL,
 actor TEXT NOT NULL, reason TEXT NOT NULL,
 registered_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_drawing_register_extraction ON drawing_registration(extraction_id);
CREATE INDEX IF NOT EXISTS ix_drawing_register_number ON drawing_registration(drawing_no);
CREATE TABLE IF NOT EXISTS offpage_annotation (
 annotation_id TEXT PRIMARY KEY,
 extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
 page INTEGER NOT NULL, bbox_json TEXT NOT NULL,
 label TEXT NOT NULL, source_sha256 TEXT NOT NULL,
 actor TEXT NOT NULL, reason TEXT NOT NULL, created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_offpage_extraction ON offpage_annotation(extraction_id);
CREATE INDEX IF NOT EXISTS ix_offpage_label ON offpage_annotation(label);
CREATE TABLE IF NOT EXISTS crosssheet_analysis (
 analysis_id TEXT PRIMARY KEY,
 result_sha256 TEXT NOT NULL,
 result_json TEXT NOT NULL, created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS crosssheet_candidate (
 candidate_id TEXT PRIMARY KEY,
 analysis_id TEXT NOT NULL REFERENCES crosssheet_analysis(analysis_id),
 from_annotation_id TEXT NOT NULL REFERENCES offpage_annotation(annotation_id),
 to_annotation_id TEXT NOT NULL REFERENCES offpage_annotation(annotation_id),
 native_candidate_id TEXT NOT NULL, candidate_json TEXT NOT NULL,
 UNIQUE(analysis_id,native_candidate_id)
);
CREATE INDEX IF NOT EXISTS ix_crosssheet_candidate_analysis ON crosssheet_candidate(analysis_id);
CREATE TABLE IF NOT EXISTS crosssheet_decision (
 decision_id TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL REFERENCES crosssheet_candidate(candidate_id),
 actor TEXT NOT NULL, decision TEXT NOT NULL,
 reason TEXT NOT NULL, created_utc TEXT NOT NULL,
 CHECK(decision IN ('LINKED_AS_DRAWN','NOT_LINKED_AS_DRAWN','UNRESOLVED','REJECTED'))
);
CREATE INDEX IF NOT EXISTS ix_crosssheet_decision_candidate ON crosssheet_decision(candidate_id);
CREATE TABLE IF NOT EXISTS signal_trace_snapshot (
 trace_id TEXT PRIMARY KEY,
 signal_analysis_id TEXT NOT NULL REFERENCES signal_analysis(analysis_id),
 result_sha256 TEXT NOT NULL, result_json TEXT NOT NULL,
 created_utc TEXT NOT NULL,
 UNIQUE(signal_analysis_id,result_sha256)
);
CREATE INDEX IF NOT EXISTS ix_signal_trace_analysis ON signal_trace_snapshot(signal_analysis_id);
CREATE TRIGGER IF NOT EXISTS block_update_drawing_registration BEFORE UPDATE ON drawing_registration BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_drawing_registration BEFORE DELETE ON drawing_registration BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_offpage_annotation BEFORE UPDATE ON offpage_annotation BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_offpage_annotation BEFORE DELETE ON offpage_annotation BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_crosssheet_analysis BEFORE UPDATE ON crosssheet_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_crosssheet_analysis BEFORE DELETE ON crosssheet_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_crosssheet_candidate BEFORE UPDATE ON crosssheet_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_crosssheet_candidate BEFORE DELETE ON crosssheet_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_crosssheet_decision BEFORE UPDATE ON crosssheet_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_crosssheet_decision BEFORE DELETE ON crosssheet_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_signal_trace_snapshot BEFORE UPDATE ON signal_trace_snapshot BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_signal_trace_snapshot BEFORE DELETE ON signal_trace_snapshot BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='7' WHERE key='standalone_schema' AND value='6';
COMMIT;
"""

MIGRATION_8 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS symbol_catalogue (
 catalogue_id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL,
 catalog_json TEXT NOT NULL, registered_utc TEXT NOT NULL,
 UNIQUE(content_sha256)
);
CREATE TABLE IF NOT EXISTS catalog_analysis (
 analysis_id TEXT PRIMARY KEY,
 extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
 geometry_analysis_id TEXT NOT NULL REFERENCES geometry_analysis(analysis_id),
 symbol_analysis_id TEXT NOT NULL REFERENCES symbol_analysis(analysis_id),
 linework_analysis_id TEXT NOT NULL REFERENCES linework_analysis(analysis_id),
 catalogue_id TEXT NOT NULL REFERENCES symbol_catalogue(catalogue_id),
 result_sha256 TEXT NOT NULL, result_json TEXT NOT NULL,
 created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_catalog_analysis_extraction ON catalog_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_catalog_analysis_catalogue ON catalog_analysis(catalogue_id);
CREATE TABLE IF NOT EXISTS catalog_candidate (
 candidate_id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES catalog_analysis(analysis_id),
 native_candidate_id TEXT NOT NULL, page INTEGER NOT NULL,
 candidate_class TEXT NOT NULL, candidate_json TEXT NOT NULL,
 UNIQUE(analysis_id, native_candidate_id)
);
CREATE INDEX IF NOT EXISTS ix_catalog_candidate_analysis ON catalog_candidate(analysis_id);
CREATE TABLE IF NOT EXISTS catalog_decision (
 decision_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES catalog_candidate(candidate_id),
 actor TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
 edited_json TEXT, created_utc TEXT NOT NULL,
 CHECK(decision IN ('ACCEPTED_AS_READING','EDITED_AND_ACCEPTED','REJECTED','UNRESOLVED'))
);
CREATE INDEX IF NOT EXISTS ix_catalog_decision_candidate ON catalog_decision(candidate_id);
CREATE TRIGGER IF NOT EXISTS block_update_symbol_catalogue BEFORE UPDATE ON symbol_catalogue BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_symbol_catalogue BEFORE DELETE ON symbol_catalogue BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_catalog_analysis BEFORE UPDATE ON catalog_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_catalog_analysis BEFORE DELETE ON catalog_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_catalog_candidate BEFORE UPDATE ON catalog_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_catalog_candidate BEFORE DELETE ON catalog_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_catalog_decision BEFORE UPDATE ON catalog_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_catalog_decision BEFORE DELETE ON catalog_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='8' WHERE key='standalone_schema' AND value='7';
COMMIT;
"""

MIGRATION_9 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS batch_import_run (
  batch_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
  manifest_json TEXT NOT NULL, params_json TEXT NOT NULL,
  created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_import_outcome (
  outcome_id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL REFERENCES batch_import_run(batch_id),
  ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
  status TEXT NOT NULL CHECK(status IN ('IMPORTED','FAILED')),
  extraction_id TEXT REFERENCES extraction(extraction_id),
  detail TEXT NOT NULL, created_utc TEXT NOT NULL,
  UNIQUE(batch_id,ordinal),
  CHECK((status='IMPORTED' AND extraction_id IS NOT NULL) OR (status='FAILED' AND extraction_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_batch_outcome_run ON batch_import_outcome(batch_id,ordinal);
CREATE TABLE IF NOT EXISTS revision_comparison (
  comparison_id TEXT PRIMARY KEY,
  before_extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  after_extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  result_sha256 TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  UNIQUE(before_extraction_id,after_extraction_id,result_sha256)
);
CREATE INDEX IF NOT EXISTS ix_revision_diff_before ON revision_comparison(before_extraction_id);
CREATE INDEX IF NOT EXISTS ix_revision_diff_after ON revision_comparison(after_extraction_id);
CREATE TRIGGER IF NOT EXISTS block_update_batch_import_run BEFORE UPDATE ON batch_import_run BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_batch_import_run BEFORE DELETE ON batch_import_run BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_batch_import_outcome BEFORE UPDATE ON batch_import_outcome BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_batch_import_outcome BEFORE DELETE ON batch_import_outcome BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_revision_comparison BEFORE UPDATE ON revision_comparison BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_revision_comparison BEFORE DELETE ON revision_comparison BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='9' WHERE key='standalone_schema' AND value='8';
COMMIT;
"""


MIGRATION_10 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS raster_analysis (
 analysis_id TEXT PRIMARY KEY,
 extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
 algorithm TEXT NOT NULL, result_hash TEXT NOT NULL,
 result_json TEXT NOT NULL, created_utc TEXT NOT NULL,
 UNIQUE(extraction_id, algorithm, result_hash)
);
CREATE TABLE IF NOT EXISTS raster_valve_candidate (
 candidate_id TEXT PRIMARY KEY,
 analysis_id TEXT NOT NULL REFERENCES raster_analysis(analysis_id),
 native_candidate_id TEXT NOT NULL, page INTEGER NOT NULL,
 candidate_json TEXT NOT NULL, UNIQUE(analysis_id, native_candidate_id)
);
CREATE TABLE IF NOT EXISTS raster_valve_decision (
 decision_id TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL REFERENCES raster_valve_candidate(candidate_id),
 actor TEXT NOT NULL, decision TEXT NOT NULL,
 reason TEXT NOT NULL, created_utc TEXT NOT NULL,
 CHECK(decision IN ('ACCEPTED_AS_READING','REJECTED','UNRESOLVED'))
);
CREATE INDEX IF NOT EXISTS ix_raster_analysis_extraction ON raster_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_raster_candidate_analysis ON raster_valve_candidate(analysis_id);
CREATE INDEX IF NOT EXISTS ix_raster_review_candidate ON raster_valve_decision(candidate_id);
CREATE TRIGGER IF NOT EXISTS block_update_raster_analysis BEFORE UPDATE ON raster_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_raster_analysis BEFORE DELETE ON raster_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_raster_valve_candidate BEFORE UPDATE ON raster_valve_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_raster_valve_candidate BEFORE DELETE ON raster_valve_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_raster_valve_decision BEFORE UPDATE ON raster_valve_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_raster_valve_decision BEFORE DELETE ON raster_valve_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='10' WHERE key='standalone_schema' AND value='9';
COMMIT;
"""


MIGRATION_11 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS raster_network_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  raster_analysis_id TEXT NOT NULL REFERENCES raster_analysis(analysis_id),
  ocr_analysis_id TEXT REFERENCES ocr_analysis(analysis_id),
  result_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  UNIQUE(extraction_id,raster_analysis_id,ocr_analysis_id,result_hash)
);
CREATE TABLE IF NOT EXISTS raster_network_candidate (
  candidate_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES raster_network_analysis(analysis_id),
  native_candidate_id TEXT NOT NULL,
  page INTEGER NOT NULL,
  kind TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  UNIQUE(analysis_id,native_candidate_id)
);
CREATE TABLE IF NOT EXISTS raster_network_decision (
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES raster_network_candidate(candidate_id),
  actor TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('CONTACT_AS_DRAWN','NOT_CONTACT_AS_DRAWN','UNRESOLVED','REJECTED')),
  reason TEXT NOT NULL,
  created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rnet_analysis_extraction ON raster_network_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_rnet_candidate_analysis ON raster_network_candidate(analysis_id);
CREATE INDEX IF NOT EXISTS ix_rnet_decision_candidate ON raster_network_decision(candidate_id);
CREATE TRIGGER IF NOT EXISTS block_update_rnet_analysis BEFORE UPDATE ON raster_network_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_rnet_analysis BEFORE DELETE ON raster_network_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_rnet_candidate BEFORE UPDATE ON raster_network_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_rnet_candidate BEFORE DELETE ON raster_network_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_rnet_decision BEFORE UPDATE ON raster_network_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_rnet_decision BEFORE DELETE ON raster_network_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='11' WHERE key='standalone_schema' AND value='10';
COMMIT;
"""


MIGRATION_12 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS raster_centreline_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  raster_analysis_id TEXT NOT NULL REFERENCES raster_analysis(analysis_id),
  raster_network_analysis_id TEXT NOT NULL REFERENCES raster_network_analysis(analysis_id),
  result_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  UNIQUE(extraction_id,raster_analysis_id,raster_network_analysis_id,result_hash)
);
CREATE TABLE IF NOT EXISTS raster_centreline_gap (
  candidate_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES raster_centreline_analysis(analysis_id),
  native_candidate_id TEXT NOT NULL, page INTEGER NOT NULL,
  candidate_json TEXT NOT NULL,
  UNIQUE(analysis_id,native_candidate_id)
);
CREATE TABLE IF NOT EXISTS raster_centreline_decision (
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES raster_centreline_gap(candidate_id),
  actor TEXT NOT NULL, decision TEXT NOT NULL,
  reason TEXT NOT NULL, created_utc TEXT NOT NULL,
  CHECK(decision IN ('CONTINUOUS_AS_DRAWN','SEPARATE_AS_DRAWN','UNRESOLVED','REJECTED'))
);
CREATE INDEX IF NOT EXISTS ix_rc_analysis_extraction ON raster_centreline_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_rc_gap_analysis ON raster_centreline_gap(analysis_id);
CREATE INDEX IF NOT EXISTS ix_rc_decision_gap ON raster_centreline_decision(candidate_id);
CREATE TRIGGER IF NOT EXISTS block_update_rc_analysis BEFORE UPDATE ON raster_centreline_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_rc_analysis BEFORE DELETE ON raster_centreline_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_rc_gap BEFORE UPDATE ON raster_centreline_gap BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_rc_gap BEFORE DELETE ON raster_centreline_gap BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_rc_decision BEFORE UPDATE ON raster_centreline_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_rc_decision BEFORE DELETE ON raster_centreline_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='12' WHERE key='standalone_schema' AND value='11';
COMMIT;
"""


# Rev X (WPU-12): engineering-intelligence storage. Purely additive: no v12 table is touched, so a v12
# reader still opens the file. Downgrade is by restoring the automatic pre-migration backup, never by dropping tables.
MIGRATION_13 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS intelligence_run (
  run_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  preset TEXT NOT NULL, status TEXT NOT NULL,
  engine_version TEXT NOT NULL, config_sha256 TEXT NOT NULL,
  source_sha256 TEXT NOT NULL, run_hash TEXT NOT NULL,
  summary_json TEXT NOT NULL, created_utc TEXT NOT NULL,
  CHECK(status IN ('COMPLETE_CANDIDATES','PARTIAL','INCOMPLETE','FAILED','NOT_RUN','CANCELLED')),
  UNIQUE(extraction_id,run_hash)
);
CREATE TABLE IF NOT EXISTS stage_outcome (
  outcome_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES intelligence_run(run_id),
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  stage_id TEXT NOT NULL, status TEXT NOT NULL,
  outcome_json TEXT NOT NULL, created_utc TEXT NOT NULL,
  CHECK(status IN ('SUCCESS','PARTIAL','SKIPPED','FAILED','TIMEOUT','CANCELLED','NOT_RUN')),
  UNIQUE(run_id,stage_id)
);
CREATE TABLE IF NOT EXISTS page_region (
  region_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES intelligence_run(run_id),
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  page INTEGER NOT NULL, kind TEXT NOT NULL,
  region_json TEXT NOT NULL,
  UNIQUE(run_id,region_id)
);
CREATE TABLE IF NOT EXISTS engineering_item (
  item_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES intelligence_run(run_id),
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  item_kind TEXT NOT NULL, tag_normalized TEXT,
  page INTEGER, item_json TEXT NOT NULL,
  CHECK(item_kind IN ('OCCURRENCE','PORT','RELATION','ASSET_HYPOTHESIS','CONFLICT','LOOP','TABLE','ATTRIBUTE','EVIDENCE'))
);
CREATE TABLE IF NOT EXISTS intelligence_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  run_id TEXT NOT NULL REFERENCES intelligence_run(run_id),
  schema_id TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
  snapshot_json TEXT NOT NULL, created_utc TEXT NOT NULL,
  UNIQUE(extraction_id,snapshot_sha256)
);
CREATE TABLE IF NOT EXISTS intelligence_decision (
  decision_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  item_id TEXT NOT NULL, actor TEXT NOT NULL,
  decision TEXT NOT NULL, old_value_json TEXT, new_value_json TEXT,
  reason TEXT NOT NULL, source_sha256 TEXT NOT NULL, model_generation TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  CHECK(decision IN ('ACCEPTED_AS_READING','REJECTED','IGNORED','NEEDS_REVIEW','RECLASSIFIED','EDITED','LINKED','UNLINKED','AMBIGUITY_RESOLVED'))
);
CREATE INDEX IF NOT EXISTS ix_ir_extraction ON intelligence_run(extraction_id);
CREATE INDEX IF NOT EXISTS ix_so_run ON stage_outcome(run_id);
CREATE INDEX IF NOT EXISTS ix_so_status ON stage_outcome(status);
CREATE INDEX IF NOT EXISTS ix_pr_extraction_page ON page_region(extraction_id,page);
CREATE INDEX IF NOT EXISTS ix_ei_run_kind ON engineering_item(run_id,item_kind);
CREATE INDEX IF NOT EXISTS ix_ei_tag ON engineering_item(item_kind,tag_normalized);
CREATE INDEX IF NOT EXISTS ix_isn_extraction ON intelligence_snapshot(extraction_id);
CREATE INDEX IF NOT EXISTS ix_idec_item ON intelligence_decision(item_id);
CREATE TRIGGER IF NOT EXISTS block_update_intelligence_run BEFORE UPDATE ON intelligence_run BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_intelligence_run BEFORE DELETE ON intelligence_run BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_stage_outcome BEFORE UPDATE ON stage_outcome BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_stage_outcome BEFORE DELETE ON stage_outcome BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_page_region BEFORE UPDATE ON page_region BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_page_region BEFORE DELETE ON page_region BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_engineering_item BEFORE UPDATE ON engineering_item BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_engineering_item BEFORE DELETE ON engineering_item BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_intelligence_snapshot BEFORE UPDATE ON intelligence_snapshot BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_intelligence_snapshot BEFORE DELETE ON intelligence_snapshot BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_intelligence_decision BEFORE UPDATE ON intelligence_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_intelligence_decision BEFORE DELETE ON intelligence_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
UPDATE project_meta SET value='13' WHERE key='standalone_schema' AND value='12';
COMMIT;
"""
