"""Persistent queue with a single-runner lease, recovery and a hash-chained ledger."""
from datetime import datetime,timezone
import hashlib,json,sqlite3,time
from pathlib import Path

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
class Store:
    def __init__(self,root):
        root=Path(root);root.mkdir(parents=True,exist_ok=True);self.root=root
        self.db=sqlite3.connect(root/'programme.sqlite',timeout=30);self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT,payload TEXT,status TEXT,result TEXT,attempts INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,payload TEXT,previous TEXT,hash TEXT);
        CREATE TABLE IF NOT EXISTS lease(id INTEGER PRIMARY KEY,owner TEXT,expires REAL);
        CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append only');END;
        CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append only');END;''')
    def close(self):self.db.close()
    def event(self,kind,**fields):
        last=self.db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone();previous=last[0] if last else '0'*64
        value=dict(kind=kind,utc=datetime.now(timezone.utc).isoformat(),**fields)
        self.db.execute('INSERT INTO events(payload,previous,hash) VALUES(?,?,?)',(canonical(value),previous,digest([previous,value])))
    def enqueue(self,kind,payload):
        if kind not in ('TRAIN_OCR','EVALUATE_OCR','EVALUATE_BASELINE_OCR','EXPERIMENT_WP08'):raise ValueError('Unsupported fixed job kind')
        jid=digest([kind,payload])[:24]
        with self.db:
            if not self.db.execute('SELECT 1 FROM jobs WHERE id=?',(jid,)).fetchone():
                self.db.execute('INSERT INTO jobs(id,kind,payload,status) VALUES(?,?,?,?)',(jid,kind,canonical(payload),'QUEUED'));self.event('ENQUEUED',job=jid,job_kind=kind)
        return jid
    def acquire(self,owner,seconds=4000):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            lease=self.db.execute('SELECT owner,expires FROM lease WHERE id=1').fetchone()
            if lease and lease['expires']>time.time() and lease['owner']!=owner:self.db.rollback();return False
            self.db.execute('INSERT OR REPLACE INTO lease VALUES(1,?,?)',(owner,time.time()+seconds))
            self.db.execute("UPDATE jobs SET status='QUEUED' WHERE status='RUNNING'")
            self.event('LEASE_ACQUIRED',owner=owner);self.db.commit();return True
        except BaseException:self.db.rollback();raise
    def release(self,owner):
        with self.db:self.db.execute('DELETE FROM lease WHERE owner=?',(owner,))
    def next(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute("SELECT * FROM jobs WHERE status IN ('QUEUED','PARTIAL') AND attempts<100 ORDER BY attempts,rowid LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE jobs SET status='RUNNING',attempts=attempts+1 WHERE id=?",(row['id'],));self.event('STARTED',job=row['id'])
            self.db.commit();return dict(row) if row else None
        except BaseException:self.db.rollback();raise
    def finish(self,jid,status,result):
        if status not in ('SUCCEEDED','PARTIAL','BLOCKED','FAILED','CANCELLED'):raise ValueError('Invalid terminal/slice state')
        with self.db:
            self.db.execute('UPDATE jobs SET status=?,result=? WHERE id=?',(status,canonical(result),jid));self.event('FINISHED',job=jid,status=status,result_sha256=digest(result),wall_seconds=float(result.get('guard',{}).get('wall_s',0)))
    def verify(self):
        previous='0'*64;problems=[]
        for row in self.db.execute('SELECT * FROM events ORDER BY seq'):
            if row['previous']!=previous or row['hash']!=digest([previous,json.loads(row['payload'])]):problems.append(row['seq'])
            previous=row['hash']
        return problems
