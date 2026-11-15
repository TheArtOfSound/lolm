import unittest
import torch
from lolm.security_research.native_capture import capture_native
from lolm.security_research.lab import Event
from lolm.security_research.observer import check_manifest


class DummyTokenizer:
    def encode(self, text):
        if 'PRIVATE' in text:
            raise AssertionError('actor leaked into prompt')
        return [1, 2, 3, 4]


class DummyNativeModel:
    def __init__(self, valid=True):
        self.valid = valid
        self.eval_called = False
    def eval(self):
        self.eval_called = True
        return self
    def __call__(self, ids):
        B,T=ids.shape
        class Output: pass
        out=Output()
        out.logits=torch.ones(B,T,5)
        out.h=torch.arange(T*3,dtype=torch.float32).view(1,T,3)
        out.gate_values=torch.full((B,T,3),0.55)
        out.regime_probs=torch.full((B,T,4),0.25)
        if not self.valid:out.regime_probs=None
        return out


class NativeCaptureTests(unittest.TestCase):
    def test_real_tensor_path_without_model_loading(self):
        e=[Event(100,'PRIVATE','login_failed',source='synthetic',truth=True)]
        model=DummyNativeModel()
        tokens,manifest=capture_native(e,model,DummyTokenizer(),checkpoint_sha256='a'*64)
        self.assertEqual(len(tokens),4)
        self.assertTrue(model.eval_called)
        self.assertGreater(tokens[1].hidden_drift,0)
        self.assertAlmostEqual(tokens[0].gate_mean,.55,places=5)
        self.assertTrue(check_manifest(manifest,e,tokens)['trace_binding_verified'])
        self.assertFalse(manifest['trace_origin_attested'])
        self.assertEqual(manifest['model_family'],'native-lolm')

    def test_fictional_only(self):
        e=[Event(100,'someone','ordinary_action',source='ocsf-iam-authentication')]
        with self.assertRaises(ValueError):
            capture_native(e,DummyNativeModel(),DummyTokenizer(),checkpoint_sha256='a'*64)

    def test_missing_neural_components_are_failure(self):
        e=[Event(100,'someone','ordinary_action',source='synthetic')]
        with self.assertRaises(RuntimeError):
            capture_native(e,DummyNativeModel(valid=False),DummyTokenizer(),checkpoint_sha256='a'*64)

    def test_bad_provenance_refused(self):
        e=[Event(100,'someone','ordinary_action',source='synthetic')]
        with self.assertRaises(ValueError):
            capture_native(e,DummyNativeModel(),DummyTokenizer(),checkpoint_sha256='not-a-hash')

    def test_independent_events_have_bounded_token_indices(self):
        e=[Event(100,'a','ordinary_action',source='synthetic'),Event(101,'b','login_success',source='synthetic')]
        tokens,_=capture_native(e,DummyNativeModel(),DummyTokenizer(),checkpoint_sha256='a'*64)
        self.assertEqual([x.token_index for x in tokens],[0,1,2,3,0,1,2,3])


if __name__=='__main__':unittest.main()
