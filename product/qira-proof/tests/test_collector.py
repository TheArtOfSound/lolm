import base64
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("qira_collector",HERE/"collector.py")
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

TOKEN_SENTINEL="SECRET-STRING-THAT-MUST-NOT-APPEAR"
WHEN="2026-11-15T19:00:00Z"

def reader(url,token,provider):
    if provider=="github":
        if url.endswith("/repos/org/repository"):
            return {"default_branch":"development"}
        if "/commits/development" in url:
            return {"sha":"0123456789abcdef0123456789abcdef01234567"}
        if "/branches/development/protection" in url:
            raise collector.ProviderError("resource forbidden")
        if "/contents/" in url:
            text='''name: deploy-production
steps:
  - uses: actions/checkout@v4
  - name: Set up SSH
    run: ssh-keyscan -H "$HOST" >> ~/.ssh/known_hosts
'''
            return {"encoding":"base64","content":base64.b64encode(text.encode()).decode()}
        raise AssertionError("unknown github request")
    if provider=="cloudflare":
        if url.endswith("/subdomain"):
            return {"enabled":True,"previews_enabled":True}
        if url.endswith("/settings"):
            return {"bindings":[{"type":"secret_text","name":"PRIVATE_KEY","text":TOKEN_SENTINEL},
                                {"type":"d1","name":"PRIVATE_DB"}]}
    raise AssertionError("unexpected request")

class CollectorTests(unittest.TestCase):
    def test_authorized_local_collector_has_expected_signals(self):
        out=collector.build_snapshot(
            github_repos=["org/repository"],cloudflare_workers=["edge-lab"],
            github_token="private",cloudflare_token="private",account_id="a"*32,
            reader=reader,when=WHEN)
        names={(f["asset"],f["signal"]):f["value"] for f in out["facts"]}
        self.assertTrue(names[("org/repository","runtime_ssh_keyscan")])
        self.assertTrue(names[("org/repository","workflow_unpinned_actions")])
        self.assertEqual(names[("org/repository","repo_branch_protection_verifiable")],"unknown")
        self.assertTrue(names[("edge-lab","worker_preview_enabled")])
        self.assertTrue(names[("edge-lab","worker_privileged_bindings")])
        self.assertNotIn(TOKEN_SENTINEL,json.dumps(out))
        self.assertNotIn("PRIVATE_KEY",json.dumps(out))
        self.assertNotIn("private",json.dumps(out))

    def test_non_main_branch_and_explicit_workflow_selection(self):
        seen=[]
        def tracking(url,token,provider):
            seen.append(url)
            return reader(url,token,provider)
        out=collector.build_snapshot(
          github_workflows=["org/repository:.github/workflows/deploy-production.yml"],
          github_token="x",reader=tracking,when=WHEN)
        self.assertTrue(out["facts"])
        self.assertTrue(any("/commits/development" in x for x in seen))
        self.assertTrue(any("?ref=0123456789abcdef0123456789abcdef01234567" in x for x in seen))
        self.assertTrue(any("/branches/development/protection" in x for x in seen))
        self.assertTrue(any("/blob/0123456789abcdef0123456789abcdef01234567/" in f["source_url"] for f in out["facts"] if f["signal"]=="runtime_ssh_keyscan"))

    def test_nested_permissions_never_claim_to_restrict_actual_workflow_token(self):
        sample="on: push\nenv:\n  permissions:\n    contents: read\njobs:\n  test:\n    steps:\n      - run: echo okay"
        result=collector.scan_workflow_syntax(sample)
        self.assertEqual(result["workflow_explicit_read_only_permissions"][0],"unknown")
        self.assertEqual(result["workflow_token_write_permission"][0],"unknown")

    def test_job_level_write_and_sequence_trigger(self):
        sample="\n".join(["on:","  - push","  - pull_request_target",
           "permissions:","  contents: read","jobs:","  deploy:",
           "    permissions:","      contents: write"])
        result=collector.scan_workflow_syntax(sample)
        self.assertTrue(result["workflow_pull_request_target_trigger"][0])
        self.assertEqual(result["workflow_pull_request_target_trigger"][1],3)
        self.assertTrue(result["workflow_token_write_permission"][0])
        self.assertFalse(result["workflow_explicit_read_only_permissions"][0])

    def test_unsupported_inline_trigger_uses_unknown(self):
        for line in ("on: { pull_request_target: {} }","on: 'pull_request_target'",
                     "on: [push, *event_alias]"):
            self.assertEqual(
                collector.scan_workflow_syntax(line)["workflow_pull_request_target_trigger"][0],
                "unknown")

    def test_reject_duplicate_repository_selection(self):
        with self.assertRaises(ValueError):
            collector.build_snapshot(github_repos=["org/repository"],
                github_workflows=["org/repository:.github/workflows/deploy-production.yml"],
                github_token="x",reader=reader,when=WHEN)

    def test_no_credentials_no_collection(self):
        with self.assertRaises(collector.ProviderError):
            collector.build_snapshot(github_repos=["org/repository"],reader=reader)
        with self.assertRaises(collector.ProviderError):
            collector.build_snapshot(cloudflare_workers=["edge-lab"],reader=reader)
        with self.assertRaises(ValueError):
            collector.build_snapshot(reader=reader)

    def test_unsafe_provider_paths_rejected(self):
        with self.assertRaises(ValueError):
            collector.github_facts("../bad","../../target","x",reader=reader)
        with self.assertRaises(ValueError):
            collector.cloudflare_facts("bad","../../bad","x",reader=reader)

    def test_existing_file_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"private.json"
            snapshot=collector.build_snapshot(github_repos=["org/repository"],
                                              github_token="x",reader=reader,when=WHEN)
            digest=collector.write_private(p,snapshot)
            self.assertEqual(len(digest),64)
            self.assertEqual(json.loads(p.read_text()),snapshot)
            with self.assertRaises(FileExistsError):
                collector.write_private(p,snapshot)
            if os.name=="posix":
                self.assertEqual(p.stat().st_mode&0o777,0o600)

    def test_no_write_api_operations(self):
        import inspect
        src=inspect.getsource(collector.fetch_json)
        self.assertIn('method="GET"',src)
        self.assertNotIn('method="POST"',src)
        self.assertNotIn('method="DELETE"',src)

if __name__=="__main__":
    unittest.main()
