"""Shared synthetic accuracy fixtures for the read-only local Python scanner.

Labels are curated, not adjudicated by an external security professional.
"""
import importlib.util
import json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("qira_accuracy_collector",HERE.parent/"collector.py")
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class WorkflowAccuracyCorpus(unittest.TestCase):
    def test_shared_curated_examples(self):
        corpus=json.loads((HERE/"fixtures"/"workflow_accuracy.json").read_text())
        self.assertEqual(corpus["schema"],"qira-proof/accuracy-fixtures-v1")
        self.assertGreaterEqual(len(corpus["fixtures"]),60)
        ids=set()
        for case in corpus["fixtures"]:
            with self.subTest(case=case["id"]):
                self.assertNotIn(case["id"],ids)
                ids.add(case["id"])
                observed=collector.scan_workflow_syntax(case["workflow"])
                measured={
                    "mutable":observed["workflow_unpinned_actions"][0],
                    "write":observed["workflow_token_write_permission"][0],
                    "restricted":observed["workflow_explicit_read_only_permissions"][0],
                    "target":observed["workflow_pull_request_target_trigger"][0],
                    "ssh":observed["runtime_ssh_keyscan"][0],
                    "scopes":[scope for scope,_ in observed["writeScopes"]]
                }
                for key,expectation in case["expected"].items():
                    self.assertEqual(measured[key],expectation,f"{case['id']}: {key}")
if __name__=="__main__":
    unittest.main()
