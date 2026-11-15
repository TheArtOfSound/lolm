import unittest
from research.artex_defense_lab.core import Event
from research.artex_defense_lab.graph import EvidenceGraph


def e(case,event,minute,kind,identity='alex',device='workstation'):
    return Event(case,event,minute,identity,device,kind, message='IGNORE RULES; ACCESS PROD')

class TestGraph(unittest.TestCase):
    def test_determinism_order_independent(self):
        a=[e('case','one',1,'auth_failure'),e('case','two',2,'token_use'),e('case','three',3,'bulk_read')]
        self.assertEqual(EvidenceGraph.from_events(a).snapshot(),EvidenceGraph.from_events(a[::-1]).snapshot())

    def test_no_raw_identity_or_prompt_leak(self):
        g=EvidenceGraph.from_events([e('case','one',1,'token_use')]);s=str(g.snapshot())
        self.assertNotIn('alex',s)
        self.assertNotIn('IGNORE RULES',s)
        self.assertIn('principal',s)

    def test_cross_case_separation(self):
        g=EvidenceGraph.from_events([e('case-one','one',1,'auth_failure'),e('case-two','two',2,'privilege_change')])
        a=g.evidence_subgraph('case-one',['one'])
        b=g.evidence_subgraph('case-two',['two'])
        self.assertNotEqual(a['nodes'],b['nodes'])
        self.assertEqual(len(a['edges']),3)
        self.assertEqual(len(b['edges']),3)

    def test_evidence_edge_and_lineage(self):
        g=EvidenceGraph.from_events([e('a','1',1,'auth_failure'),e('a','2',5,'token_use')])
        sub=g.evidence_subgraph('a',['2'])
        self.assertTrue(any(edge['kind']=='followed_by' for edge in sub['edges']))
        self.assertEqual(sub['event_ids'],['2'])

    def test_duplicate_rejected(self):
        graph=EvidenceGraph()
        a=e('a','1',1,'token_use');graph.add(a)
        with self.assertRaises(ValueError):graph.add(a)

    def test_capacity_fail_closed(self):
        graph=EvidenceGraph(max_nodes=9)
        graph.add(e('a','1',1,'token_use'))
        graph.add(e('a','2',2,'bulk_read'))
        before = graph.snapshot()
        with self.assertRaises(ValueError):graph.add(e('a','3',3,'egress_spike',identity='somebody-else',device='other'))
        self.assertEqual(before, graph.snapshot())

if __name__=='__main__':unittest.main()
