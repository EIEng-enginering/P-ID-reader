"""Additive, isolated SQLite storage for WP01-03; never writes Worksheet R1 or host DB.

Use a separate file until a future, reviewed host migration integrates this layer.
Analysis JSON is immutable; human decisions append immutable hash-chained events.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
from .wp123_recovery import SCHEMA,canon,digest,sid

SCHEMA_VERSION=1
ALLOWED={'ACCEPTED_AS_READING','CORRECTED_READING','REJECTED','UNRESOLVED'}

class WP123Store:
    def __init__(self,path:str|Path):
        self.path=str(path)
        self.con=sqlite3.connect(self.path,timeout=10)
        self.con.row_factory=sqlite3.Row
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.execute('PRAGMA busy_timeout=10000')
        self.con.executescript('''
            CREATE TABLE IF NOT EXISTS wp123_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wp123_analyses(
              analysis_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL,
              content_sha256 TEXT NOT NULL UNIQUE, document_json TEXT NOT NULL,
              created_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wp123_decisions(
              event_id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL,
              target_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
              reason TEXT NOT NULL, corrected_text TEXT, created_utc TEXT NOT NULL,
              prev_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE,
              FOREIGN KEY(analysis_id) REFERENCES wp123_analyses(analysis_id));
            CREATE TRIGGER IF NOT EXISTS wp123_no_update BEFORE UPDATE ON wp123_analyses
              BEGIN SELECT RAISE(ABORT,'Immutable WP123 analysis'); END;
            CREATE TRIGGER IF NOT EXISTS wp123_no_delete BEFORE DELETE ON wp123_analyses
              BEGIN SELECT RAISE(ABORT,'Immutable WP123 analysis'); END;
            CREATE TRIGGER IF NOT EXISTS wp123_event_no_update BEFORE UPDATE ON wp123_decisions
              BEGIN SELECT RAISE(ABORT,'Immutable WP123 decision'); END;
            CREATE TRIGGER IF NOT EXISTS wp123_event_no_delete BEFORE DELETE ON wp123_decisions
              BEGIN SELECT RAISE(ABORT,'Immutable WP123 decision'); END;
        ''')
        self.con.execute('INSERT OR IGNORE INTO wp123_meta(key,value) VALUES (?,?)',('schema_version',str(SCHEMA_VERSION)))
        version=self.con.execute('SELECT value FROM wp123_meta WHERE key=?',('schema_version',)).fetchone()[0]
        if version!=str(SCHEMA_VERSION):raise ValueError('Unsupported WP123 sidecar schema')
        self.con.commit()

    def close(self):self.con.close()
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()

    def add(self,result:dict)->str:
        if not isinstance(result,dict) or result.get('schema')!=SCHEMA or digest({k:v for k,v in result.items() if k!='result_sha256'})!=result.get('result_sha256'):
            raise ValueError('Invalid WP123 analysis content hash')
        content=canon(result)
        analysis_id=sid('wp123-analysis',result['source_sha256'],result['result_sha256'])
        row=self.con.execute('SELECT document_json FROM wp123_analyses WHERE analysis_id=?',(analysis_id,)).fetchone()
        if row is not None:
            if row[0]!=content:raise ValueError('Conflicting result under same analysis identity')
            return analysis_id
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self.con:
            self.con.execute('INSERT INTO wp123_analyses VALUES (?,?,?,?,?)',
                             (analysis_id,result['source_sha256'],result['result_sha256'],content,now))
        return analysis_id

    def get(self,analysis_id:str)->dict:
        row=self.con.execute('SELECT document_json FROM wp123_analyses WHERE analysis_id=?',(analysis_id,)).fetchone()
        if not row:raise KeyError('Unknown WP123 analysis')
        payload=json.loads(row[0])
        if digest({k:v for k,v in payload.items() if k!='result_sha256'})!=payload['result_sha256']:
            raise ValueError('Stored WP123 content has changed')
        return payload

    def review(self,analysis_id:str,target_id:str,*,actor:str,decision:str,reason:str,corrected_text:str|None=None)->str:
        if not actor or not actor.strip() or not reason or not reason.strip() or decision not in ALLOWED:
            raise ValueError('Named reviewer, reason and allowed decision required')
        if len(actor)>160 or len(reason)>2000 or len(corrected_text or '')>300:
            raise ValueError('Review field length limit exceeded')
        if decision=='CORRECTED_READING' and not corrected_text:
            raise ValueError('Corrected reading text required')
        doc=self.get(analysis_id)
        targets={r['id'] for r in doc['readings']} | {x['id'] for x in doc['document_fields']} | \
                {r['id'] for r in doc['bubble_candidates']} | {r['id'] for r in doc['line_number_fragments']} | \
                {r['id'] for r in doc['detector_decisions']} | {r['id'] for r in doc['bubble_text_links']}
        if target_id not in targets:raise ValueError('Target does not exist in original evidence')
        # Serialize append and hash chaining with an IMMEDIATE transaction.
        self.con.execute('BEGIN IMMEDIATE')
        try:
            last=self.con.execute('SELECT event_hash FROM wp123_decisions ORDER BY rowid DESC LIMIT 1').fetchone()
            prev=last[0] if last else 'GENESIS'
            created=datetime.now(timezone.utc).isoformat(timespec='microseconds')
            body={'analysis_id':analysis_id,'target_id':target_id,'actor':actor.strip(),
                  'action':decision,'reason':reason.strip(),'corrected_text':corrected_text,
                  'created_utc':created,'prev_event_hash':prev}
            event_hash=digest(body)
            event_id=sid('wp123-review',event_hash)
            self.con.execute('INSERT INTO wp123_decisions VALUES (?,?,?,?,?,?,?,?,?,?)',
                (event_id,analysis_id,target_id,body['actor'],decision,body['reason'],corrected_text,created,prev,event_hash))
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise
        return event_id

    def decisions(self,analysis_id:str)->list[dict]:
        self.get(analysis_id)
        return [dict(r) for r in self.con.execute('SELECT * FROM wp123_decisions WHERE analysis_id=? ORDER BY rowid',(analysis_id,))]

    def verify_audit(self)->list[str]:
        errors=[]
        prev='GENESIS'
        for row in self.con.execute('SELECT * FROM wp123_decisions ORDER BY rowid'):
            d=dict(row)
            body={'analysis_id':d['analysis_id'],'target_id':d['target_id'],
                  'actor':d['actor'],'action':d['action'],'reason':d['reason'],
                  'corrected_text':d['corrected_text'],'created_utc':d['created_utc'],
                  'prev_event_hash':d['prev_event_hash']}
            if d['prev_event_hash']!=prev or digest(body)!=d['event_hash'] or sid('wp123-review',d['event_hash'])!=d['event_id']:
                errors.append('Broken WP123 audit event '+d['event_id'])
            prev=d['event_hash']
        return errors
