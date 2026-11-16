import unittest
from lolm.security_research.lab import Event
from lolm.security_research.capture import capture, synthetic_prompt
from lolm.security_research.observer import check_manifest, parse_tokens
import dataclasses
import json


class CaptureTests(unittest.TestCase):
    def fake_gen(self, prompt):
        yield {"event":"start","data":{"use_graft":True}}
        for i in range(2):
            yield {"event":"token","data":{"trace":{
                "used_graft":True,"graft_entropy":2.0,
                "hidden_drift":0.02,"gate_mean":.5,"regime_entropy":1.2
            }}}
        yield {"event":"done","data":{"use_graft":True,"last_graft_error":None}}

    def test_prompt_excludes_actor_and_truth(self):
        e = Event(100,"SECRET_ACTOR","login_failed",source="synthetic",truth=True,
                  user_agent="ATTACK_PAYLOAD")
        p = synthetic_prompt(e)
        self.assertNotIn("SECRET_ACTOR",p)
        self.assertNotIn("ATTACK_PAYLOAD",p)
        self.assertNotIn("truth",p)
        self.assertIn("login_failed",p)

    def test_capture_and_manifest(self):
        events = [Event(i+100,"acct","ordinary_action",source="synthetic") for i in range(2)]
        tokens,manifest = capture(events,self.fake_gen,"a"*64)
        self.assertEqual(len(tokens),4)
        self.assertFalse(check_manifest(manifest,events,tokens)["trace_origin_attested"])
        self.assertEqual(len(parse_tokens([json.dumps(dataclasses.asdict(x)) for x in tokens],2)),4)

    def test_non_synthetic_event_blocked(self):
        event = Event(10,"real-user","login_failed",source="ocsf-iam-authentication")
        with self.assertRaises(ValueError):
            capture([event],self.fake_gen,"a"*64)

    def test_fallback_rejected(self):
        def bad(prompt):
            yield {"event":"token","data":{"trace":{"used_graft":False}}}
        with self.assertRaises(RuntimeError):
            capture([Event(100,"x","ordinary_action",source="synthetic")],bad,"a"*64)

    def test_missing_done_rejected(self):
        def incomplete(prompt):
            yield {"event":"token","data":{"trace":{
                "used_graft":True,"graft_entropy":2.0,
                "hidden_drift":.02,"gate_mean":.5,"regime_entropy":1.2
            }}}
        with self.assertRaises(RuntimeError):
            capture([Event(100,"x","ordinary_action",source="synthetic")],incomplete,"a"*64)


if __name__=="__main__":
    unittest.main()
