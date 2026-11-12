import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from pid_reader.engineering.wp456.common import digest,seal,verify_seal
from pid_reader.engineering.wp456.pipeline import build,export
from pid_reader.engineering.wp456.store import Store,targets
from .test_readings import word


def fixture():
    words=[word('a','FE-2202'),word('b','NTS'),word('c','NTS')]
    reading=dict(words[0],kind='INSTRUMENT_TAG',text_candidate='FE-2202',ocr_ids=['a'])
    fields=[dict(w,field='SCALE_CANDIDATE',value_candidate='NTS',ocr_ids=[w['id']]) for w in words[1:]]
    upstream=seal({'schema':'pid-reader-wp123-recovery-v1','source_sha256':'a'*64,
                   'inputs':{'ocr_evidence_sha256':digest(words)},'readings':[reading],
                   'document_fields':fields,'bubble_candidates':[],'detector_decisions':[]})
    return upstream,words


def result():
    u,w=fixture();return build(u,w,page_sizes={1:(1000,800)})


class PipelineTests(unittest.TestCase):
    def test_metadata_duplicates_removed(self):
        r=result();self.assertEqual(len(r['wp04']['document_fields']),1);self.assertTrue(verify_seal(r))

    def test_result_roundtrip_multi_page_hash(self):
        u,w=fixture();r=build(u,w,page_sizes={1:(1000,800),2:(1000,800),10:(1000,800)})
        self.assertTrue(verify_seal(json.loads(json.dumps(r))))

    def test_mutated_evidence_refused(self):
        u,w=fixture();w[0]['text']='DIFFERENT'
        with self.assertRaises(ValueError):build(u,w,page_sizes={1:(1000,800)})

    def test_mutated_upstream_refused(self):
        u,w=fixture();u['source_sha256']='b'*64
        with self.assertRaises(ValueError):build(u,w,page_sizes={1:(1000,800)})

    def test_result_has_no_host_payload(self):
        r=result();self.assertEqual(r['wp06']['worksheet_r1_status'],'UNCHANGED_NOT_EXPORTED')
        self.assertNotIn('objects',r);self.assertEqual(r['metrics']['status'],'NOT_RUN')

    def test_exports_verify_hash(self):
        with tempfile.TemporaryDirectory() as d:
            export(result(),d)
            self.assertTrue(verify_seal(json.loads((Path(d)/'wp456_result.json').read_text())))

    def test_exports_reject_tampered_result(self):
        r=result();r['wp04']['readings']=[]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):export(r,d)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'review.sqlite';self.s=Store(self.path)
        self.r=result();self.aid=self.s.add(self.r);self.target=self.r['wp04']['readings'][0]['id']
    def tearDown(self):self.s.close();self.tmp.cleanup()

    def test_repeated_add_idempotent(self):
        self.assertEqual(self.s.add(self.r),self.aid)
        self.assertEqual(self.s.con.execute('SELECT COUNT(*) FROM wp456_analyses').fetchone()[0],1)

    def test_append_correct_and_accept_chain(self):
        self.s.decide(self.aid,self.target,'ACCEPTED_AS_READING',actor='Reviewer',reason='Printed text checked')
        self.s.decide(self.aid,self.target,'CORRECTED_READING',actor='Reviewer',reason='Suffix visible',corrected_text='FE-2202A')
        self.assertEqual(len(self.s.decisions(self.aid)),2);self.assertEqual(self.s.verify(),[])

    def test_actor_required(self):
        with self.assertRaises(ValueError):self.s.decide(self.aid,self.target,'REJECTED',actor='',reason='r')

    def test_reason_required(self):
        with self.assertRaises(ValueError):self.s.decide(self.aid,self.target,'REJECTED',actor='a',reason=' ')

    def test_unknown_target_rejected(self):
        with self.assertRaises(ValueError):self.s.decide(self.aid,'wrong','REJECTED',actor='a',reason='r')

    def test_plant_acceptance_not_allowed(self):
        with self.assertRaises(ValueError):self.s.decide(self.aid,self.target,'ENGINEERING_VERIFIED',actor='a',reason='r')

    def test_missing_correction_rejected(self):
        with self.assertRaises(ValueError):self.s.decide(self.aid,self.target,'CORRECTED_READING',actor='a',reason='r')

    def test_delete_trigger(self):
        self.s.decide(self.aid,self.target,'REJECTED',actor='a',reason='r')
        with self.assertRaises(sqlite3.IntegrityError):self.s.con.execute('DELETE FROM wp456_decisions')
        self.s.con.rollback();self.assertEqual(self.s.verify(),[])

    def test_tamper_detected(self):
        self.s.decide(self.aid,self.target,'REJECTED',actor='a',reason='r')
        self.s.con.execute('DROP TRIGGER wp456_no_update')
        self.s.con.execute("UPDATE wp456_decisions SET previous_hash='wrong'");self.s.con.commit()
        self.assertTrue(self.s.verify())
        with self.assertRaises(ValueError):self.s.decide(self.aid,self.target,'UNRESOLVED',actor='a',reason='r')


class EvidenceRetentionTests(unittest.TestCase):
    def test_incomplete_lines_and_full_evidence_retained(self):
        u,w=fixture();u['line_number_fragments']=[dict(word('frag','GHS-22203-168.3'),text_observed='GHS-22203-168.3')];u=seal(u)
        r=build(u,w,page_sizes={1:(1000,800)})
        self.assertEqual(len(r['wp04']['line_number_fragments']),1)
        self.assertEqual(r['ocr_evidence'],w);self.assertEqual(r['upstream_wp123_result'],u)
        self.assertEqual(targets(r)['frag'],'READING')
