"""Immutable source and named human review of WP01-03 proposals."""
import sqlite3
import pytest
from pid_reader.engineering.wp123_recovery import recover_wp123
from pid_reader.engineering.wp123_store import WP123Store

PDF=b'%PDF-1.4\nsource evidence only\n'

def sample():
    w={'id':'w','page':1,'text':'V-2201','bbox':{'x0':.2,'y0':.2,'x1':.28,'y1':.23},
       'raw_score':.9,'review_state':'PROPOSED_UNVERIFIED'}
    return recover_wp123(PDF,[w],[])


def test_analysis_idempotent_and_persistent(tmp_path):
    a=sample();p=tmp_path/'wp123.sqlite'
    with WP123Store(p) as db:
        i=db.add(a)
        assert db.add(a)==i
        assert db.get(i)==a
    with WP123Store(p) as db:assert db.get(i)==a


def test_named_review_and_valid_audit_chain(tmp_path):
    a=sample()
    with WP123Store(tmp_path/'review.sqlite') as db:
        i=db.add(a);target=a['readings'][0]['id']
        first=db.review(i,target,actor='Engineer A',decision='UNRESOLVED',reason='Uncertain scanned tag')
        second=db.review(i,target,actor='Engineer B',decision='CORRECTED_READING',
                         corrected_text='V-2201',reason='Compared with original scan')
        assert first!=second
        assert db.verify_audit()==[]
        assert [x['action'] for x in db.decisions(i)]==['UNRESOLVED','CORRECTED_READING']
        assert db.get(i)==a


def test_review_requires_named_actor_and_real_target(tmp_path):
    a=sample()
    with WP123Store(tmp_path/'r.sqlite') as db:
        i=db.add(a)
        with pytest.raises(ValueError):db.review(i,'made-up',actor='A',decision='REJECTED',reason='Not visible')
        with pytest.raises(ValueError):db.review(i,a['readings'][0]['id'],actor='',decision='REJECTED',reason='Not visible')
        with pytest.raises(ValueError):db.review(i,a['readings'][0]['id'],actor='A',decision='CORRECTED_READING',reason='Corrected')
        assert db.verify_audit()==[]


def test_immutable_tables_reject_update_delete(tmp_path):
    a=sample()
    with WP123Store(tmp_path/'r.sqlite') as db:
        i=db.add(a)
        eid=db.review(i,a['readings'][0]['id'],actor='A',decision='REJECTED',reason='False reading')
        with pytest.raises(sqlite3.IntegrityError):
            db.con.execute('UPDATE wp123_analyses SET document_json=? WHERE analysis_id=?',('{}',i))
        with pytest.raises(sqlite3.IntegrityError):
            db.con.execute('DELETE FROM wp123_decisions WHERE event_id=?',(eid,))
        db.con.rollback()
        assert db.verify_audit()==[]


def test_hashed_payload_must_be_complete(tmp_path):
    a=sample();a['summary']['tags_proposed']=100
    with WP123Store(tmp_path/'r.sqlite') as db:
        with pytest.raises(ValueError):db.add(a)
