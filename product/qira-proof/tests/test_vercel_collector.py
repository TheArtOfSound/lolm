import importlib.util
import json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("qira_collector_vercel",HERE/"collector.py")
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
WHEN="2026-11-15T19:00:00Z"
SENSITIVE="PRIVATE-VALUE-NEVER-EXPORT"
PROJECT="example-project"

def reader(url,token,provider):
    assert provider=="vercel"
    assert token==SENSITIVE
    if "/v9/projects/" in url:
        return {"id":"prj_AbCd987654321","name":PROJECT,
          "ssoProtection":{"enabled":False,"deploymentType":None},
          "passwordProtection":{"enabled":False,"deploymentType":None},
          "trustedIps":{"enabled":False,"deploymentType":None,"addresses":[SENSITIVE]}}
    if "target=preview" in url:
        return {"deployments":[{"id":"dpl_preview","target":"preview","readyState":"READY",
          "secret":SENSITIVE}]}
    if "target=production" in url:
        return {"deployments":[{"id":"dpl_production","target":"production","readyState":"ERROR",
          "secret":SENSITIVE}]}
    raise AssertionError(url)

class VercelCollectorTests(unittest.TestCase):
    def test_only_three_bounded_metadata_facts_without_tokens_or_urls_with_query(self):
        out=collector.build_snapshot(vercel_projects=[PROJECT],vercel_token=SENSITIVE,
          vercel_team="team_Valid654",reader=reader,when=WHEN)
        assert len(out["facts"])==3
        signals={f["signal"]:f["value"] for f in out["facts"]}
        self.assertEqual(signals,{
            "vercel_deployment_protection_configured":False,
            "vercel_latest_production_errored":True,
            "vercel_recent_preview_observed":True
        })
        body=json.dumps(out)
        self.assertNotIn(SENSITIVE,body)
        self.assertNotIn("team_Valid654",body)
        self.assertNotIn("?target",body)
        self.assertTrue(all(f["provider"]=="vercel" for f in out["facts"]))
        self.assertTrue(all("?" not in f["source_url"] for f in out["facts"]))

    def test_unknown_and_non_error_states_are_not_promoted_to_false_or_incident(self):
        def incomplete(url,token,provider):
            if "/v9/projects/" in url:
                return {"id":"prj_AbCd987654321","name":PROJECT,
                    "ssoProtection":{"enabled":False}}
            if "target=preview" in url:
                return {"deployments":[]}
            return {"deployments":[{"target":"production","readyState":"BUILDING"}]}
        facts=collector.vercel_facts(PROJECT,"placeholder",reader=incomplete,when=WHEN)
        values={f["signal"]:f["value"] for f in facts}
        self.assertEqual(values["vercel_deployment_protection_configured"],"unknown")
        self.assertEqual(values["vercel_recent_preview_observed"],"unknown")
        self.assertEqual(values["vercel_latest_production_errored"],"unknown")

    def test_active_protection_and_ready_production_are_not_findings(self):
        def secure(url,token,provider):
            if "/v9/projects/" in url:
                return {"id":"prj_AbCd987654321","name":PROJECT,
                  "ssoProtection":{"enabled":True,"deploymentType":"all_except_custom_domains"},
                  "passwordProtection":{"enabled":False}, "trustedIps":{"enabled":False}}
            if "target=preview" in url:
                return {"deployments":[{"target":"preview","readyState":"READY"}]}
            return {"deployments":[{"target":"production","readyState":"READY"}]}
        facts=collector.vercel_facts(PROJECT,"placeholder",reader=secure,when=WHEN)
        self.assertEqual([f["value"] for f in facts],[True,True,False])

    def test_invalid_inputs_fail_without_network(self):
        never=lambda *a: self.fail("Network should never run")
        for project in ["../secrets","http://example.org","bad?token=abc","",None]:
            with self.assertRaises(ValueError):
                collector.vercel_facts(project,"placeholder",reader=never)
        with self.assertRaises(ValueError):
            collector.vercel_facts(PROJECT,"placeholder",team="../../bad",reader=never)
        with self.assertRaises(collector.ProviderError):
            collector.build_snapshot(vercel_projects=[PROJECT],reader=never)
        with self.assertRaises(ValueError):
            collector.build_snapshot(vercel_projects=[PROJECT,PROJECT],vercel_token="x",reader=never)

    def test_malformed_provider_data_fails_closed(self):
        def wrong(url,token,provider):
            if "/v9/projects/" in url: return {"id":"bogus","name":"proj"}
            return {"deployments":[]}
        with self.assertRaises(collector.ProviderError):
            collector.vercel_facts(PROJECT,"placeholder",reader=wrong)

if __name__=="__main__":
    unittest.main()
