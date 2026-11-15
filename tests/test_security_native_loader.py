import hashlib
import tempfile
import unittest
from pathlib import Path
from scripts.capture_security_lolm_native import validate_checkpoint


class LoaderPreflightTests(unittest.TestCase):
    def test_digest_checked_before_weights_loading(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fake.pt'
            p.write_bytes(b'dummy bytes, not real model weights')
            good=hashlib.sha256(p.read_bytes()).hexdigest()
            validate_checkpoint(p,good)
            with self.assertRaises(ValueError):
                validate_checkpoint(p,'0'*64)

    def test_missing_checkpoint_refused(self):
        with self.assertRaises(ValueError):
            validate_checkpoint(Path('/definitely/missing/trained.ckpt'),'0'*64)

    def test_short_pin_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'x')
            with self.assertRaises(ValueError):
                validate_checkpoint(p,'short')


if __name__=='__main__':unittest.main()
