import unittest
from lolm.security_research.stress import cases, stress_benchmark


class StressTests(unittest.TestCase):
    def test_cases_sorted_and_complete(self):
        data, groups = cases()
        self.assertEqual(len(groups),8)
        self.assertEqual([e.ts for e in data], sorted(e.ts for e in data))
        self.assertEqual(sum(s.end-s.start for s in groups), len(data))

    def test_spoofed_artifact_is_false_positive_not_attribution(self):
        result = stress_benchmark()["methods"]["rules"]
        spoof = next(x for x in result["scenarios"] if x["scenario"]=="public-agent-ua-spoof")
        self.assertTrue(spoof["alerted"])
        self.assertFalse(spoof["incident"])
        self.assertGreater(result["fp"],0)

    def test_slow_attack_may_be_missed(self):
        result = stress_benchmark()["methods"]["rules"]
        slow = next(x for x in result["scenarios"] if x["scenario"]=="slow-auth-abuse")
        self.assertFalse(slow["alerted"])

    def test_no_hybrid_guarantee(self):
        result = stress_benchmark()
        self.assertFalse(result["neural_model"])
        for method in ("rules","shift","hybrid"):
            self.assertIn("benign_case_false_alert_rate",result["methods"][method])


if __name__=="__main__":
    unittest.main()
