import unittest
from pid_reader.engineering.wp456.readings import deduplicate,propose_regions,line_alternatives,bubble_readings


def word(id='w',text='NTS',b=(.1,.1,.2,.12),page=1,**kw):
    return dict(id=id,text=text,bbox=dict(zip(('x0','y0','x1','y1'),b)),page=page,raw_score=.9,**kw)


class ReadingsTests(unittest.TestCase):
    def test_duplicate_sources_merge_keep_members(self):
        rows=deduplicate([word('a'),word('b')])
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]['member_ids'],['a','b'])
        self.assertEqual(len(rows[0]['evidence_members']),2)

    def test_occurrences_on_different_parts_stay_separate(self):
        self.assertEqual(len(deduplicate([word('a'),word('b',b=(.5,.5,.6,.52))])),2)

    def test_different_pages_stay_separate(self):
        self.assertEqual(len(deduplicate([word('a'),word('b',page=2)])),2)

    def test_conflicting_text_kept(self):
        self.assertEqual(len(deduplicate([word('a','FR'),word('b','FQ')])),2)

    def test_complete_link_prevents_chain_merge(self):
        rows=[word('a',b=(.1,.1,.2,.2)),word('b',b=(.13,.1,.23,.2)),word('c',b=(.16,.1,.26,.2))]
        self.assertEqual(len(deduplicate(rows)),2)

    def test_dedup_order_invariant(self):
        a,b=word('a'),word('b')
        self.assertEqual(deduplicate([a,b]),deduplicate([b,a]))

    def test_dedup_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):deduplicate([word(),word()])

    def test_region_priority_and_caps(self):
        rows=[word(str(i),'PF-00019-14.3-A3S-40',b=(i/100,.1,i/100+.005,.11)) for i in range(12)]
        r=propose_regions(rows,max_regions=2)
        self.assertEqual(len(r['regions']),2);self.assertTrue(r['truncated'])

    def test_selected_crop_exact(self):
        selected={'page':2,'bbox':word()['bbox']}
        r=propose_regions([],selected=selected)
        self.assertEqual(r['regions'][0]['bbox'],selected['bbox']);self.assertEqual(r['regions'][0]['page'],2)

    def test_selected_large_crop_rejected(self):
        r=propose_regions([],selected={'page':1,'bbox':dict(x0=0,y0=0,x1=1,y1=1)})
        self.assertEqual(r['regions'],[]);self.assertTrue(r['truncated'])

    def test_line_alternative_requires_observation(self):
        r=word(text='x');r.update(kind='PIPE_LINE_NUMBER',text_candidate='PF-00019-14.3-A3S-40')
        out=line_alternatives([r],[])
        self.assertEqual(out[0]['alternatives'],[])
        w=word('better','HPF-00019-114.3-A3S-40')
        out=line_alternatives([r],[w]);self.assertEqual(out[0]['alternatives'][0]['text_candidate'],w['text'])
        self.assertEqual(out[0]['original'],r['text_candidate'])

    def test_neighbouring_label_not_used_as_correction(self):
        r=word(text='x');r.update(kind='PIPE_LINE_NUMBER',text_candidate='PF-00019-14.3-A3S-40')
        w=word('other','HPF-00019-114.3-A3S-40',b=(.5,.5,.7,.52))
        self.assertEqual(line_alternatives([r],[w])[0]['alternatives'],[])

    def bubble(self):return word('bubble',b=(.1,.1,.2,.2),ocr_ids=['c','n'])
    def inside(self):
        return [word('c','FR',b=(.13,.12,.17,.14),run_id='r',roi_id='roi'),
                word('n','720201',b=(.12,.16,.18,.18),run_id='r',roi_id='roi')]

    def test_bubble_same_pass_join(self):
        r=bubble_readings([self.bubble()],self.inside())[0]
        self.assertEqual(r['options'][0]['text_candidate'],'FR-720201')
        self.assertIn('FR_FQ_CONFUSION_CHECK',r['warnings'])

    def test_bubble_different_runs_abstain(self):
        words=self.inside();words[1]['run_id']='different'
        r=bubble_readings([self.bubble()],words)[0]
        self.assertFalse(r['options']);self.assertIn('CROSS_RUN_FRAGMENTS_NOT_JOINED',r['warnings'])

    def test_bubble_missing_run_not_assumed(self):
        words=self.inside();[w.pop('run_id') for w in words]
        self.assertFalse(bubble_readings([self.bubble()],words)[0]['options'])

    def test_bubble_outside_number_not_joined(self):
        words=self.inside();words[1]['bbox']=word(b=(.3,.3,.4,.4))['bbox']
        self.assertFalse(bubble_readings([self.bubble()],words)[0]['options'])

    def test_bubble_number_above_code_not_joined(self):
        words=self.inside();words[0]['bbox'],words[1]['bbox']=words[1]['bbox'],words[0]['bbox']
        self.assertFalse(bubble_readings([self.bubble()],words)[0]['options'])

    def test_bubble_reading_enters_register_only_if_unique(self):
        from pid_reader.engineering.wp456.readings import bubble_tag_proposals
        words=self.inside();results=bubble_readings([self.bubble()],words)
        self.assertEqual(bubble_tag_proposals(results,words)[0]['text_candidate'],'FR-720201')
        results[0]['options'].append(dict(text_candidate='FQ-77701',ocr_ids=['c','n']))
        self.assertEqual(bubble_tag_proposals(results,words),[])
