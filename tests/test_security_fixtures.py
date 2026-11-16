import tempfile
import unittest
from pathlib import Path
from lolm.security_research.fixtures import study_events, write_study
from lolm.security_research.lab import parse_jsonl


class FixtureTests(unittest.TestCase):
    def test_disjoint_and_preceding(self):
        train,test = study_events()
        self.assertEqual(len(train),60)
        self.assertEqual(len(test),109)
        self.assertTrue(all(not e.truth for e in train))
        self.assertLess(max(e.ts for e in train),min(e.ts for e in test))
        self.assertTrue(any(e.truth for e in test))

    def test_file_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/"fixture"
            out = write_study(target)
            self.assertEqual(out["reference_events"],60)
            with (target/"heldout-events.jsonl").open() as handle:
                self.assertEqual(len(parse_jsonl(handle)),109)
            with self.assertRaises(FileExistsError):
                write_study(target)

    def test_bounded_size(self):
        with self.assertRaises(ValueError): study_events(39)
        with self.assertRaises(ValueError): study_events(201)


if __name__=="__main__":
    unittest.main()
