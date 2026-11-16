import unittest

from lolm.security_research.causal import Context, structural, replay, frontier, demo, receipt, verify


class CausalObservatoryTests(unittest.TestCase):
    def test_baseline_is_matured_fictional_cascade(self):
        self.assertTrue(structural(Context())["adverse_outcome"])

    def test_stepup_is_not_robust_against_token_fallback(self):
        self.assertFalse(structural(Context(),["step_up_auth"],"primary")["adverse_outcome"])
        self.assertTrue(structural(Context(),["step_up_auth"],"token_fallback")["adverse_outcome"])

    def test_export_guard_can_be_bypassed_in_hypothesized_shadow_path(self):
        self.assertFalse(structural(Context(),["export_guard"],"primary")["adverse_outcome"])
        self.assertTrue(structural(Context(),["export_guard"],"shadow_export")["adverse_outcome"])

    def test_robust_least_privilege(self):
        self.assertTrue(replay(Context(),["least_privilege"])["robust_prevention"])

    def test_robust_multicontrol(self):
        self.assertTrue(replay(Context(),["step_up_auth","revoke_service_token"])["robust_prevention"])

    def test_frontier_does_not_include_dominated_solutions(self):
        choices = frontier(Context())
        self.assertGreater(len(choices),0)
        self.assertTrue(any("least_privilege" in c["controls"] for c in choices))
        for x in choices:
            for y in choices:
                self.assertFalse(y["cost"]<x["cost"] and y["count"]<=x["count"])

    def test_receipts_detect_manipulation(self):
        d=demo(["least_privilege"])
        self.assertTrue(d["receipts_verified"])
        experiments=[d["experiment"],{"version":"causal-observatory/scm-1.0","frontier":d["frontier"]}]
        self.assertTrue(verify(experiments,d["receipts"]))
        experiments[0]["cost"]=999
        self.assertFalse(verify(experiments,d["receipts"]))

    def test_authorization_is_declared_not_inferred(self):
        self.assertFalse(structural(Context(authorized_workflow=True))["adverse_outcome"])

    def test_invalid_interventions_fail_closed(self):
        with self.assertRaises(ValueError):
            replay(Context(),["bad_control"])
        with self.assertRaises(ValueError):
            structural(Context(),["least_privilege","least_privilege"])

    def test_reproducible_experiments(self):
        self.assertEqual(demo(["egress_guard"]),demo(["egress_guard"]))

    def test_negative_control_unchanged_baseline(self):
        self.assertEqual(structural(Context(),["revoke_service_token"])["adverse_outcome"],
                         structural(Context())["adverse_outcome"])

    def test_sensitivity_to_assumptions(self):
        outcomes=[structural(Context(),["step_up_auth"],v)["adverse_outcome"]
                  for v in ("primary","token_fallback","shadow_export","combined")]
        self.assertEqual(outcomes,[False,True,False,True])


if __name__ == "__main__":
    unittest.main()
