"""Separate append-only review sidecar; never a standalone DB migration."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import sqlite3
from .common import canonical, digest, ident, verify_seal


def targets(result):
    out={}
    for key in ('readings','document_fields','line_number_fragments'):
        for row in result['wp04'].get(key,[]): out[row['id']]='READING'
    for row in result['wp04']['bubble_readings']: out[row['id']]='HYPOTHESIS'
    for group in ('symbols','associations'):
        for row in result['wp05'][group]: out[row['id']]='HYPOTHESIS'
    for group in ('nodes','edges','contacts','gaps','port_attachments'):
        for row in result['wp06']['graph'][group]: out[row['id']]='HYPOTHESIS'
    return out


class Store:
    def __init__(self,path):
        self.con=sqlite3.connect(str(path),timeout=15)
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.executescript('''
        CREATE TABLE IF NOT EXISTS wp456_analyses (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS wp456_decisions (
          seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, previous_hash TEXT NOT NULL,
          record_hash TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS wp456_no_update BEFORE UPDATE ON wp456_decisions
          BEGIN SELECT RAISE(ABORT,'append-only decisions'); END;
        CREATE TRIGGER IF NOT EXISTS wp456_no_delete BEFORE DELETE ON wp456_decisions
          BEGIN SELECT RAISE(ABORT,'append-only decisions'); END;
        CREATE TRIGGER IF NOT EXISTS wp456_analysis_no_update BEFORE UPDATE ON wp456_analyses
          BEGIN SELECT RAISE(ABORT,'immutable analysis'); END;
        CREATE TRIGGER IF NOT EXISTS wp456_analysis_no_delete BEFORE DELETE ON wp456_analyses
          BEGIN SELECT RAISE(ABORT,'immutable analysis'); END;
        ''')

    def close(self): self.con.close()

    def add(self,result):
        if result.get('schema')!='pid-reader-wp456-proposals-v1' or not verify_seal(result):
            raise ValueError('Invalid analysis content hash')
        aid=ident('analysis456',result['result_sha256'])
        with self.con:
            self.con.execute('INSERT OR IGNORE INTO wp456_analyses VALUES (?,?,?)',
                             (aid,result['source_sha256'],canonical(result)))
        return aid

    def get(self,aid):
        row=self.con.execute('SELECT payload FROM wp456_analyses WHERE id=?',(aid,)).fetchone()
        if row is None: raise KeyError(aid)
        result=json.loads(row[0])
        if not verify_seal(result): raise ValueError('Analysis hash mismatch')
        return result

    def decide(self,aid,target_id,action,*,actor,reason,corrected_text=None):
        kinds=targets(self.get(aid))
        if target_id not in kinds: raise ValueError('Unknown target')
        allowed={'REJECTED','UNRESOLVED','SUPPORTED_AS_DRAWING_HYPOTHESIS'}
        if kinds[target_id]=='READING': allowed |= {'ACCEPTED_AS_READING','CORRECTED_READING'}
        if action not in allowed: raise ValueError('Action does not apply to target scope')
        if not isinstance(actor,str) or not actor.strip() or not isinstance(reason,str) or not reason.strip():
            raise ValueError('Named reviewer and reason required')
        if action=='CORRECTED_READING':
            if not isinstance(corrected_text,str) or not corrected_text.strip() or len(corrected_text)>200:
                raise ValueError('Correction text required, at most 200 characters')
        elif corrected_text is not None: raise ValueError('Correction belongs only to corrected readings')
        payload={'analysis_id':aid,'target_id':target_id,'action':action,'actor':actor.strip(),
                 'reason':reason.strip(),'corrected_text':corrected_text,
                 'utc':datetime.now(timezone.utc).isoformat(),'scope':kinds[target_id]}
        self.con.execute('BEGIN IMMEDIATE')
        try:
            problems=self.verify()
            if problems: raise ValueError('Existing audit chain invalid: '+str(problems))
            last=self.con.execute('SELECT record_hash FROM wp456_decisions ORDER BY seq DESC LIMIT 1').fetchone()
            prev=last[0] if last else '0'*64
            rh=digest({'previous_hash':prev,'payload':payload})
            self.con.execute('INSERT INTO wp456_decisions(payload,previous_hash,record_hash) VALUES (?,?,?)',
                             (canonical(payload),prev,rh))
            self.con.commit()
        except Exception:
            self.con.rollback(); raise
        return rh

    def decisions(self,aid):
        return [d for (p,) in self.con.execute('SELECT payload FROM wp456_decisions ORDER BY seq')
                if (d:=json.loads(p))['analysis_id']==aid]

    def verify(self):
        errors=[]; prev='0'*64; expected_seq=1
        for seq,p,ph,rh in self.con.execute('SELECT seq,payload,previous_hash,record_hash FROM wp456_decisions ORDER BY seq'):
            try:
                payload=json.loads(p)
                if seq!=expected_seq or ph!=prev or rh!=digest({'previous_hash':ph,'payload':payload}):
                    errors.append('DECISION_CHAIN_MISMATCH:'+str(seq))
                result=self.get(payload['analysis_id'])
                if payload['target_id'] not in targets(result): errors.append('UNKNOWN_TARGET:'+str(seq))
            except (ValueError,KeyError,TypeError): errors.append('INVALID_RECORD:'+str(seq))
            prev=rh; expected_seq=seq+1
        for aid,p in self.con.execute('SELECT id,payload FROM wp456_analyses'):
            try:
                r=json.loads(p)
                if not verify_seal(r) or aid!=ident('analysis456',r['result_sha256']): errors.append('ANALYSIS_HASH:'+aid)
            except (ValueError,KeyError,TypeError): errors.append('INVALID_ANALYSIS:'+aid)
        return errors
