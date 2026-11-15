import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lolm.security_research.lab import Event
from lolm.security_research.observer import NFETToken, security_event_hash, trace_digest
from lolm.security_research.fixtures import study_events
from lolm.security_research.stress import cases


def null_trace(events):
    return [NFETToken(i,0,2.0+(i%3)*.02,.03+(i%4)*.002,.5+(i%5)*.002,1.4+(i%6)*.002)
            for i in range(len(events))]


def save_bundle(directory, prefix, events):
    tokens = null_trace(events)
    files = [directory/(prefix+'-events.jsonl'),directory/(prefix+'-trace.jsonl'),
             directory/(prefix+'-manifest.json')]
    files[0].write_text(''.join(json.dumps(dataclasses.asdict(x))+'\n' for x in events))
    files[1].write_text(''.join(json.dumps(dataclasses.asdict(x))+'\n' for x in tokens))
    files[2].write_text(json.dumps({'schema':'lolm-nfet-observer/v1',
                  'source_type':'synthetic','events_sha256':security_event_hash(events),
                  'trace_sha256':trace_digest(tokens)}))
    return list(map(str,files))


class FalsificationCLITests(unittest.TestCase):
    def args(self, directory):
        ref,test=study_events()
        _,scenarios=cases()
        r=save_bundle(directory,'reference',ref)
        t=save_bundle(directory,'test',test)
        label_path=directory/'scenarios.json'
        label_path.write_text(json.dumps([dataclasses.asdict(x) for x in scenarios]))
        return [sys.executable,'-m','lolm.security_research.cli','falsify',
                '--train-events',r[0],'--train-trace',r[1],'--train-manifest',r[2],
                '--test-events',t[0],'--test-trace',t[1],'--test-manifest',t[2],
                '--scenarios',str(label_path)]

    def test_falsify_rejects_unacknowledged_reference(self):
        with tempfile.TemporaryDirectory() as root:
            args=self.args(Path(root))
            response=subprocess.run(args,capture_output=True,text=True)
            self.assertNotEqual(response.returncode,0)
            self.assertIn('ack-known-benign',response.stderr)

    def test_offline_end_to_end_synthetic_null(self):
        with tempfile.TemporaryDirectory() as root:
            args=self.args(Path(root))
            response=subprocess.run(args+['--ack-known-benign'],capture_output=True,text=True)
            self.assertEqual(response.returncode,0,response.stderr)
            data=json.loads(response.stdout)
            self.assertEqual(data['schema'],'lolm-nfet-falsification/v1')
            self.assertEqual(data['aligned']['counts']['tp'],0)
            self.assertEqual(data['aligned']['permutation']['permutations'],56)
            self.assertFalse(data['train_provenance']['trace_origin_attested'])
            self.assertEqual(data['shuffle_control_exceedance']['controls'],7)

    def test_bad_label_schema_refused(self):
        with tempfile.TemporaryDirectory() as root:
            args=self.args(Path(root))
            path=Path(args[-1]);path.write_text('[{"name":"fake"}]')
            response=subprocess.run(args+['--ack-known-benign'],capture_output=True,text=True)
            self.assertNotEqual(response.returncode,0)
            self.assertIn('scenario metadata',response.stderr)


if __name__=='__main__':
    unittest.main()
