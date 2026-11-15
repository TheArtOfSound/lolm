import dataclasses
import unittest
from lolm.security_research.falsification import (
    _validate_scenarios, shuffle_event_traces, exact_scenario_permutation_p,
    evaluate_falsification,
)
from lolm.security_research.observer import NFETToken
from lolm.security_research.fixtures import study_events
from lolm.security_research.stress import cases, Case


def null_trace(events):
    # Artificial uninformative telemetry, independent of truth labels.
    return [NFETToken(i,0,2.0+(i%3)*.02, .03+(i%4)*.002,
                      .5+(i%5)*.002, 1.4+(i%6)*.002)
            for i in range(len(events))]


class FalsificationTests(unittest.TestCase):
    def test_trace_shuffle_preserves_within_event_values(self):
        events,_=cases()
        trace=null_trace(events)
        flipped=shuffle_event_traces(trace,len(events),37)
        self.assertEqual(len(flipped),len(trace))
        self.assertEqual(sorted(x.logit_entropy for x in flipped),
                         sorted(x.logit_entropy for x in trace))
        self.assertNotEqual([x.logit_entropy for x in flipped],
                            [x.logit_entropy for x in trace])

    def test_shuffling_multitoken_groups(self):
        t=[NFETToken(i,j,2.0+i,.03+i,.5,1.4) for i in range(5) for j in range(2)]
        s=shuffle_event_traces(t,5,37)
        self.assertEqual([x.token_index for x in s],[0,1]*5)
        self.assertEqual([s[i].logit_entropy for i in range(0,10,2)],
                         [s[i+1].logit_entropy for i in range(0,10,2)])

    def test_exact_scenario_permutations_match_combination_count(self):
        out=exact_scenario_permutation_p([True,True,True,False,False,False,False,False],
                                        [True,True,True,False,False,False,False,False])
        self.assertEqual(out['permutations'],56)
        self.assertAlmostEqual(out['one_sided_p'],1/56,places=5)

    def test_constant_scores_not_claimed_as_model_gain(self):
        train,test=study_events()
        _,groups=cases()
        result=evaluate_falsification(train,null_trace(train),test,null_trace(test),groups)
        self.assertFalse(result['model_forward_executed_here'])
        self.assertIn('not_met',result['claim_gate'])
        self.assertEqual(len(result['shuffled_controls']),7)

    def test_mismatched_scenario_labels_refused(self):
        _,test=study_events(); _,scenarios=cases()
        wrong=list(scenarios)
        wrong[0]=dataclasses.replace(wrong[0],incident=True)
        with self.assertRaises(ValueError):
            _validate_scenarios(test,wrong)

    def test_missing_scenario_refused(self):
        _,test=study_events(); _,scenarios=cases()
        with self.assertRaises(ValueError):
            _validate_scenarios(test,scenarios[:-1])

    def test_invalid_seeds_refused(self):
        train,test=study_events()
        _,groups=cases()
        with self.assertRaises(ValueError):
            evaluate_falsification(train,null_trace(train),test,null_trace(test),groups,seeds=[1,1])

    def test_source_truth_not_in_trace(self):
        train,test=study_events()
        _,groups=cases()
        a=evaluate_falsification(train,null_trace(train),test,null_trace(test),groups,seeds=[1,2])
        self.assertEqual(a['heldout_events'],109)
        self.assertEqual(sum(x.incident for x in groups),3)


if __name__=='__main__':
    unittest.main()
