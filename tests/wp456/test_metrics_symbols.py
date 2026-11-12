import unittest
from pid_reader.engineering.wp456.metrics import score,score_associations,_maximum_matching
from pid_reader.engineering.wp456.symbols import candidates,associations,calibration_report
from .test_readings import word
SHA='a'*64


class MetricsTests(unittest.TestCase):
    def ref(self,items):
        return {'status':'SYNTHETIC_REFERENCE','source_sha256':SHA,'reviewer':'synthetic fixture',
                'reviewed_utc':'2026-11-12T00:00:00Z','coverage':[{'page':1,'kind':'TAG','exhaustive':True}],
                'items':items}
    def label(self,id='g',text='FE-2202',**kw):return word(id,text,kind='TAG',**kw)

    def test_exact_and_duplicate(self):
        out=score(self.ref([self.label()]),[self.label('p'),self.label('duplicate')],source_sha256=SHA)
        m=out['per_class']['TAG'];self.assertEqual((m['true_positive'],m['false_positive'],m['false_negative']),(1,1,0))
        self.assertEqual(m['precision'],.5)

    def test_wrong_text_is_fp_and_fn(self):
        out=score(self.ref([self.label()]),[self.label('p','FE-2203')],source_sha256=SHA)
        self.assertEqual(out['per_class']['TAG']['true_positive'],0)
        self.assertEqual(out['per_class']['TAG']['false_negative'],1)

    def test_uncovered_page_excluded(self):
        out=score(self.ref([]),[self.label('p',page=2)],source_sha256=SHA)
        self.assertEqual(out['excluded_predictions'],1)

    def test_draft_not_measured(self):
        r=self.ref([]);r['status']='DRAFT'
        self.assertEqual(score(r,[],source_sha256=SHA)['status'],'NOT_RUN')

    def test_other_source_refused(self):
        with self.assertRaises(ValueError):score(self.ref([]),[],source_sha256='b'*64)

    def test_no_exhaustive_scope_not_measured(self):
        r=self.ref([]);r['coverage'][0]['exhaustive']=False
        self.assertEqual(score(r,[],source_sha256=SHA)['status'],'NOT_RUN')

    def test_maximum_matching_not_greedy(self):
        self.assertEqual(len(_maximum_matching({'p1':['g1','g2'],'p2':['g1']})),2)

    def test_empty_denominators_are_null(self):
        m=score(self.ref([]),[],source_sha256=SHA)['per_class']['TAG']
        self.assertIsNone(m['precision']);self.assertIsNone(m['recall'])

    def test_association_duplicates_and_missing_endpoints(self):
        m=score_associations([['a','b']],[['x','y'],['x','y'],['bad','y']],{'x':'a','y':'b'})
        self.assertEqual((m['true_positive'],m['false_positive'],m['false_negative']),(1,2,0))


class SymbolTests(unittest.TestCase):
    def reading(self,id='r',**kw):
        return dict(word(id,**kw),kind='INSTRUMENT_TAG',text_candidate='FE-2202')
    def symbol(self,id='s',**kw):
        return dict(word(id,b=(.2,.1,.22,.12),**kw),kind='INSTRUMENT',eligibility='ASSOCIATION_CANDIDATE')
    def test_unique_compatible_association(self):
        r=associations([self.reading()],[self.symbol()],page_sizes={1:(1000,800)})[0]
        self.assertEqual(r['state'],'ASSOCIATION_PROPOSED')

    def test_two_symbols_abstain(self):
        r=associations([self.reading()],[self.symbol('a'),self.symbol('b')],page_sizes={1:(1000,800)})[0]
        self.assertEqual(r['state'],'AMBIGUOUS_SYMBOLS');self.assertIsNone(r['symbol_id'])

    def test_two_tags_compete(self):
        out=associations([self.reading('r1'),self.reading('r2')],[self.symbol()],page_sizes={1:(1000,800)})
        self.assertTrue(all(a['state']=='MULTIPLE_TAGS_COMPETE' for a in out))

    def test_other_page_not_linked(self):
        r=associations([self.reading()],[self.symbol(page=2)],page_sizes={1:(1000,800),2:(1000,800)})[0]
        self.assertEqual(r['state'],'NO_COMPATIBLE_CANDIDATE')

    def test_wrong_class_not_linked(self):
        s=self.symbol();s['kind']='VALVE'
        self.assertIsNone(associations([self.reading()],[s],page_sizes={1:(1000,800)})[0]['symbol_id'])

    def test_withheld_not_resurrected(self):
        d=dict(word(),coarse_class='instrumentation',raw_score=.99,eligibility='WITHHELD_NOT_DELETED',filter_reason='DOCUMENT_METADATA_REGION')
        self.assertEqual(candidates([d])[0]['eligibility'],'WITHHELD')

    def test_general_class_not_equipment(self):
        d=dict(word(),coarse_class='general',raw_score=.99,eligibility='REVIEWABLE_CLASS_CANDIDATE')
        r=candidates([d])[0];self.assertEqual(r['kind'],'UNKNOWN');self.assertEqual(r['eligibility'],'WITHHELD')

    def test_bubble_route_distinct_from_detector(self):
        b=word('b',ocr_ids=['w'])
        self.assertEqual(candidates([], [b])[0]['eligibility'],'BUBBLE_GEOMETRY_CANDIDATE')

    def test_page_aspect_ratio_used(self):
        s=self.symbol();s['bbox']=word(b=(.21,.1,.23,.12))['bbox']
        a=associations([self.reading()],[s],page_sizes={1:(4000,200)},max_gap_points=24)[0]
        self.assertIsNone(a['symbol_id'])

    def test_calibration_cannot_use_holdout(self):
        row=dict(id='d',split='HOLDOUT',is_correct=True,raw_score=.9,source_sha256=SHA,coarse_class='valve')
        with self.assertRaises(ValueError):calibration_report([row],dataset_id='train',source_sha256s=[SHA])

    def test_calibration_study_not_runtime_change(self):
        row=dict(id='d',split='TRAIN',is_correct=True,raw_score=.9,source_sha256=SHA,coarse_class='valve')
        r=calibration_report([row],dataset_id='train',source_sha256s=[SHA]);self.assertFalse(r['runtime_gate_changed'])
        with self.assertRaises(ValueError):calibration_report([row],dataset_id='train',source_sha256s=[SHA],thresholds=(.2,))

    def test_reviewer_equipment_candidate_is_separate_evidence(self):
        from pid_reader.engineering.wp456.symbols import explicit_candidates
        row=dict(word('human'),kind='EQUIPMENT',actor='Reviewer',reason='Vessel outline',evidence_ids=['source-box'],source_sha256=SHA)
        out=explicit_candidates([row],source_sha256=SHA)
        self.assertEqual(out[0]['origin'],'REVIEWER_DRAWING_PROPOSAL')
        with self.assertRaises(ValueError):explicit_candidates([row],source_sha256='b'*64)
