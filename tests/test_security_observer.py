import dataclasses
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from lolm.security_research.lab import Event
from lolm.security_research.observer import (
    NFETToken, check_manifest, event_features, fit_benign, parse_tokens,
    security_event_hash, shadow_evaluate, trace_digest,
)


def events(n, base=1000, benign=True):
    return [Event(base + i*15, "synthetic-user", "ordinary_action",
                  truth=(not benign and i%7==0)) for i in range(n)]


def tokens_for(events, *, abnormal_at=None):
    return [NFETToken(i, 0, 2.0 + (i%3)*.01 + (2.0 if i==abnormal_at else 0),
                      0.04 + (0.9 if i==abnormal_at else 0),
                      0.51 + (0.18 if i==abnormal_at else 0),
                      1.4 + (0.8 if i==abnormal_at else 0)) for i in range(len(events))]


class ObserverTests(unittest.TestCase):
    def test_valid_frame_and_alignment(self):
        ev = events(3); tok = tokens_for(ev)
        self.assertEqual(parse_tokens([json.dumps(dataclasses.asdict(t)) for t in tok], 3), tok)

    def test_unordered_and_missing_tokens_fail(self):
        data = tokens_for(events(3))
        with self.assertRaises(ValueError):
            parse_tokens([json.dumps(dataclasses.asdict(t)) for t in data[:2]], 3)
        with self.assertRaises(ValueError):
            parse_tokens([json.dumps(dataclasses.asdict(t)) for t in reversed(data)], 3)
        gap = [dataclasses.replace(data[0], token_index=2)]
        with self.assertRaises(ValueError):
            parse_tokens([json.dumps(dataclasses.asdict(t)) for t in gap], 1)

    def test_nan_inf_bool_and_ranges_fail(self):
        x = dataclasses.asdict(tokens_for(events(1))[0])
        for field,val in [("gate_mean",1.1),("hidden_drift",float("nan")),
                          ("logit_entropy",float("inf")),("regime_entropy",True)]:
            with self.assertRaises(ValueError):
                NFETToken.parse({**x,field:val})

    def test_extra_columns_refused_to_prevent_label_leak(self):
        x = dataclasses.asdict(tokens_for(events(1))[0]); x["truth"] = True
        with self.assertRaises(ValueError):
            NFETToken.parse(x)

    def test_event_hash_excludes_ground_truth(self):
        e = events(3)
        self.assertEqual(security_event_hash(e),
                         security_event_hash([dataclasses.replace(x,truth=True) for x in e]))

    def test_manifest_hash_binds_trace_and_events(self):
        ev = events(3); t = tokens_for(ev)
        m = {"schema":"lolm-nfet-observer/v1","source_type":"synthetic",
             "events_sha256":security_event_hash(ev),"trace_sha256":trace_digest(t)}
        check = check_manifest(m, ev, t)
        self.assertTrue(check["trace_binding_verified"])
        self.assertFalse(check["trace_origin_attested"])
        with self.assertRaises(ValueError):
            check_manifest(m,events(3,base=2000),t)

    def test_checkpoint_pin_check_never_claims_origin(self):
        ev = events(2); t = tokens_for(ev)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"fake.bin"; p.write_bytes(b"arbitrary bytes: not a trained model")
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            m = {"schema":"lolm-nfet-observer/v1","source_type":"checkpoint-generated",
                 "events_sha256":security_event_hash(ev),"trace_sha256":trace_digest(t),
                 "checkpoint_sha256":sha}
            verified = check_manifest(m,ev,t,checkpoint_path=p,expected_checkpoint=sha)
            self.assertTrue(verified["checkpoint_bytes_verified"])
            self.assertFalse(verified["trace_origin_attested"])
            with self.assertRaises(ValueError):
                check_manifest(m,ev,t,checkpoint_path=p,expected_checkpoint="0"*64)

    def test_features_are_causal_and_per_event(self):
        a = event_features(tokens_for(events(3),abnormal_at=2),3)
        self.assertEqual(len(a),3)
        self.assertAlmostEqual(a[0][0],0.0)
        self.assertGreater(a[2][1],0.9)

    def test_benign_only_calibration_and_alpha(self):
        train = events(40)
        calibration = fit_benign(train,tokens_for(train),alpha=.1)
        self.assertEqual(calibration.benign_count,40)
        self.assertEqual(calibration.reference_count,20)
        self.assertEqual(calibration.calibration_count,20)
        with self.assertRaises(ValueError):
            fit_benign(events(40,benign=False),tokens_for(events(40,benign=False)))
        with self.assertRaises(ValueError):
            fit_benign(train,tokens_for(train),alpha=1)

    def test_shadow_findings_are_read_only_and_not_training(self):
        train = events(40,base=1000); test = events(30,base=5000)
        calibration = fit_benign(train,tokens_for(train),alpha=.1)
        result = shadow_evaluate(calibration,train,test,tokens_for(test,abnormal_at=3))
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["checkpoint_forward_invoked"])
        self.assertGreaterEqual(len(result["alerts"]),1)

    def test_train_test_overlap_refused(self):
        train = events(40); cal = fit_benign(train,tokens_for(train))
        with self.assertRaises(ValueError):
            shadow_evaluate(cal,train,train,tokens_for(train))

    def test_manifest_unknown_origin_rejected(self):
        train = events(2); trace = tokens_for(train)
        m = {"schema":"lolm-nfet-observer/v1","source_type":"unknown",
             "events_sha256":security_event_hash(train),"trace_sha256":trace_digest(trace)}
        with self.assertRaises(ValueError):
            check_manifest(m,train,trace)


if __name__ == "__main__":
    unittest.main()
