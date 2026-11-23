"""Offline tests for scripts/coverage.py: no network, no gh. Run: python -I -m unittest discover -s tests"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coverage  # noqa: E402


def row(pr, verdict):
    return {"pr": pr, "verdict": verdict}


class Summarize(unittest.TestCase):
    def test_counts_only_open_prs(self):
        rows = [row(1, "clean"), row(2, "notes"), row(3, "in-progress"), row(4, "scan-only"), row(99, "clean")]
        got = coverage.summarize({1, 2, 3, 4, 5, 6}, rows, "T")
        self.assertEqual(got["open_total"], 6)
        self.assertEqual(got["reviewed_open"], 3)        # 1, 2 and 4: PR 99 is reviewed but no longer open
        self.assertEqual(got["scan_only_open"], 1)
        self.assertEqual(got["in_progress_open"], 1)
        self.assertEqual(got["unreviewed_total"], 2)
        self.assertEqual(got["newest_unreviewed"], [6, 5])
        self.assertEqual(got["as_of"], "T")

    def test_the_parts_add_up(self):
        rows = [row(n, "clean") for n in range(1, 40, 3)] + [row(50, "in-progress")]
        got = coverage.summarize(set(range(1, 101)), rows, "T")
        self.assertEqual(got["reviewed_open"] + got["in_progress_open"] + got["unreviewed_total"], got["open_total"])

    def test_newest_unreviewed_is_capped_and_newest_first(self):
        got = coverage.summarize(set(range(1, 501)), [], "T")
        self.assertEqual(len(got["newest_unreviewed"]), coverage.NEWEST)
        self.assertEqual(got["newest_unreviewed"][0], 500)
        self.assertEqual(got["unreviewed_total"], 500)

    def test_parse_numbers_ignores_noise(self):
        self.assertEqual(coverage.parse_numbers("12\n7\n\nnot-a-number\n7\n"), {7, 12})


if __name__ == "__main__":
    unittest.main()
