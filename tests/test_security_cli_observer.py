import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from lolm.security_research.lab import Event
from lolm.security_research.observer import NFETToken, security_event_hash, trace_digest


def prepare_bundle(folder, prefix, base, n=40):
    ev = [Event(base+i*10,"person","ordinary_action") for i in range(n)]
    t = [NFETToken(i,0,2.0+(i%3)*.01,.03,.5,1.4) for i in range(n)]
    a,b,c = (folder/(prefix+"_"+ext) for ext in ("events.jsonl","trace.jsonl","manifest.json"))
    a.write_text("".join(json.dumps(dataclasses.asdict(x))+"\n" for x in ev))
    b.write_text("".join(json.dumps(dataclasses.asdict(x))+"\n" for x in t))
    c.write_text(json.dumps({
        "schema":"lolm-nfet-observer/v1","source_type":"synthetic",
        "events_sha256":security_event_hash(ev),"trace_sha256":trace_digest(t)
    }))
    return [str(x) for x in (a,b,c)]


class CLITests(unittest.TestCase):
    def test_full_cli_rejects_unacknowledged_benign(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            train = prepare_bundle(directory,"train",1000)
            test = prepare_bundle(directory,"test",5000)
            args = [sys.executable,"-m","lolm.security_research.cli","observe",
                    "--train-events",train[0],"--train-trace",train[1],"--train-manifest",train[2],
                    "--test-events",test[0],"--test-trace",test[1],"--test-manifest",test[2]]
            p = subprocess.run(args,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertIn("ack-known-benign",p.stderr)
            p = subprocess.run([*args,"--ack-known-benign"],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            result = json.loads(p.stdout)
            self.assertFalse(result["test_provenance"]["trace_origin_attested"])
            self.assertEqual(result["reference_count"],20)
            self.assertEqual(result["calibration_count"],20)

    def test_stress_cli_reports_failure_modes(self):
        p = subprocess.run([sys.executable,"-m","lolm.security_research.cli","stress"],
                           capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        result = json.loads(p.stdout)
        self.assertGreater(result["methods"]["rules"]["fp"],0)


if __name__=="__main__":
    unittest.main()
