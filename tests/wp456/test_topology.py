import unittest
from pid_reader.engineering.wp456.topology import build_graph


def seg(id,a,b,kind='PROCESS',page=1):return dict(id=id,a=a,b=b,line_kind=kind,page=page)


def graph(segments,ports=None,junctions=None):
    return build_graph(segments,ports or [],junctions or [],page_sizes={1:(1000,800),2:(1000,800)})


class TopologyTests(unittest.TestCase):
    def cross(self):return [seg('h',(.1,.5),(.9,.5)),seg('v',(.5,.1),(.5,.9))]
    def dot(self):return dict(id='dot',point=(.5,.5),page=1,line_kind='PROCESS',evidence_ids=['visible-dot'])

    def test_crossing_without_dot_not_connected(self):
        g=graph(self.cross());self.assertEqual(len(g['nodes']),4);self.assertEqual(len(g['edges']),2)
        self.assertEqual(g['contacts'][0]['state'],'CROSSING_OR_T_UNRESOLVED')

    def test_explicit_dot_splits_crossing(self):
        g=graph(self.cross(),junctions=[self.dot()]);self.assertEqual(len(g['nodes']),5);self.assertEqual(len(g['edges']),4)
        self.assertEqual(g['contacts'][0]['state'],'EXPLICIT_JUNCTION_PROPOSED')

    def test_corner_geometry_contact(self):
        g=graph([seg('a',(.1,.1),(.5,.1)),seg('b',(.5,.1),(.5,.5))])
        self.assertEqual(len(g['nodes']),3)

    def test_t_without_dot_not_connected(self):
        g=graph([seg('a',(.1,.5),(.9,.5)),seg('b',(.5,.1),(.5,.5))])
        self.assertEqual(len(g['nodes']),4)

    def test_three_incident_endpoints_need_dot(self):
        g=graph([seg('a',(.1,.5),(.5,.5)),seg('b',(.5,.5),(.9,.5)),seg('c',(.5,.5),(.5,.9))])
        self.assertEqual(len(g['nodes']),6)

    def test_unknown_strokes_do_not_join(self):
        g=graph([seg('a',(.1,.1),(.5,.1),'UNKNOWN'),seg('b',(.5,.1),(.5,.5),'UNKNOWN')])
        self.assertEqual(len(g['nodes']),4)

    def test_signal_process_not_connected(self):
        g=graph([seg('a',(.1,.1),(.5,.1),'PROCESS'),seg('b',(.5,.1),(.5,.5),'SIGNAL')])
        self.assertEqual(len(g['nodes']),4)

    def test_pages_not_connected(self):
        g=graph([seg('a',(.1,.1),(.5,.1),page=1),seg('b',(.5,.1),(.5,.5),page=2)])
        self.assertEqual(len(g['nodes']),4);self.assertEqual(g['contacts'],[])

    def test_gap_is_proposal_not_join(self):
        g=graph([seg('a',(.1,.1),(.5,.1)),seg('b',(.501,.1),(.8,.1))])
        self.assertEqual(len(g['nodes']),4);self.assertTrue(g['gaps']);self.assertEqual(len(g['edges']),2)

    def test_port_requires_exactly_one_node(self):
        port=dict(id='p',point=(.1,.1),symbol_id='s',page=1,line_kind='PROCESS',evidence_ids=['port-visible'])
        g=graph([seg('a',(.1,.1),(.5,.1))],ports=[port]);self.assertEqual(g['port_attachments'][0]['state'],'PORT_CONTACT_PROPOSED')

    def test_port_on_unknown_not_linked(self):
        port=dict(id='p',point=(.1,.1),symbol_id='s',page=1,line_kind='PROCESS',evidence_ids=['port-visible'])
        g=graph([seg('a',(.1,.1),(.5,.1),'UNKNOWN')],ports=[port]);self.assertIsNone(g['port_attachments'][0]['node_id'])

    def test_zero_length_rejected(self):
        with self.assertRaises(ValueError):graph([seg('a',(.1,.1),(.1,.1))])

    def test_bad_coordinates_rejected(self):
        with self.assertRaises(ValueError):graph([seg('a',(float('nan'),.1),(.2,.1))])

    def test_duplicate_segment_ids_rejected(self):
        with self.assertRaises(ValueError):graph([seg('a',(.1,.1),(.2,.1)),seg('a',(.3,.1),(.4,.1))])

    def test_explicit_junction_requires_evidence(self):
        j=self.dot();j['evidence_ids']=[]
        with self.assertRaises(ValueError):graph(self.cross(),junctions=[j])

    def test_collinear_duplicate_strokes_not_collapsed_into_pipe(self):
        g=graph([seg('a',(.1,.1),(.5,.1)),seg('b',(.1,.1),(.5,.1))])
        self.assertEqual(len(g['nodes']),4)
        self.assertEqual(g['contacts'][0]['state'],'COLLINEAR_OVERLAP_UNRESOLVED')
