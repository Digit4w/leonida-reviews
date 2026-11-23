"""Offline tests for scripts/auto_merge_check.py: no network, no gh. Run: python -I -m unittest discover -s tests"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import auto_merge_check as amc  # noqa: E402


def review(pr=100, reviewer="alice/claude", **extra):
    data = {"pr": pr, "head_sha": "abcdef12", "reviewer": reviewer, "date": "2026-11-23", "scope": "static, diff only",
            "verdict": "clean", "findings": ["a plain finding"], "read_by_human": False, "commented_on_github": False}
    data.update(extra)
    return data


PR = {"number": 5, "author": "alice", "draft": False, "state": "open", "base": "main"}


def run(files, heads, mains=None, trusted=True, pr=PR):
    mains = mains or {}
    return amc.evaluate(pr, files, lambda p: heads.get(p), lambda p: mains.get(p), trusted)


def added(n):
    return {"filename": "reviews/%d.json" % n, "status": "added"}


class AutoMergeRules(unittest.TestCase):
    def test_plain_new_review_is_mergeable(self):
        self.assertEqual(run([added(100)], {"reviews/100.json": review()}), [])

    def test_untrusted_first_contribution_waits_for_a_human(self):
        self.assertTrue(run([added(100)], {"reviews/100.json": review()}, trusted=False))

    def test_other_files_are_refused(self):
        for name in ("build_table.py", ".github/workflows/table.yml", "docs/index.html", "AUTHORS.md",
                     "reviews/abc.json", "reviews/sub/100.json", "reviews/100.json.bak", "reviews/0100x.json"):
            self.assertTrue(run([{"filename": name, "status": "added"}], {}), name)

    def test_removed_and_renamed_are_refused(self):
        for status in ("removed", "renamed", "copied"):
            self.assertTrue(run([{"filename": "reviews/100.json", "status": status}], {"reviews/100.json": review()}))

    def test_cannot_file_a_review_in_someone_elses_name(self):
        self.assertTrue(run([added(100)], {"reviews/100.json": review(reviewer="bob/claude")}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(reviewer="alice-evil/claude")}))

    def test_file_name_must_match_pr_field(self):
        self.assertTrue(run([added(100)], {"reviews/100.json": review(pr=101)}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(pr=True)}))

    def test_modification_must_keep_the_reviewer(self):
        f = [{"filename": "reviews/100.json", "status": "modified"}]
        heads = {"reviews/100.json": review()}
        self.assertEqual(run(f, heads, {"reviews/100.json": review()}), [])
        self.assertTrue(run(f, heads, {"reviews/100.json": review(reviewer="bob/claude")}))
        self.assertTrue(run(f, heads, {}))

    def test_links_html_markdown_and_invisible_text_are_refused(self):
        for text in ("see https://example.com", "<img src=x>", "[x](http://y)", "![i](j)", "javascript:alert(1)",
                     "zero​width", "bidi‮evil", "ctrl\x07", "x" * 401):
            self.assertTrue(run([added(100)], {"reviews/100.json": review(findings=[text])}), repr(text))
            self.assertTrue(run([added(100)], {"reviews/100.json": review(scope=text)}), repr(text))

    def test_unknown_or_wrongly_typed_fields_are_refused(self):
        self.assertTrue(run([added(100)], {"reviews/100.json": review(verdict="safe")}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(extra_field=1)}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(head_sha="../../x")}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(date="yesterday")}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(read_by_human="yes")}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(findings="not a list")}))
        self.assertTrue(run([added(100)], {"reviews/100.json": review(findings=["f"] * 21)}))
        self.assertTrue(run([added(100)], {"reviews/100.json": ["not", "an", "object"]}))

    def test_draft_closed_or_other_base_is_refused(self):
        for change in ({"draft": True}, {"state": "closed"}, {"base": "dev"}):
            pr = dict(PR, **change)
            self.assertTrue(run([added(100)], {"reviews/100.json": review()}, pr=pr), change)

    def test_empty_and_huge_prs_are_refused(self):
        self.assertTrue(run([], {}))
        many = [added(n) for n in range(1, 102)]
        self.assertTrue(run(many, {"reviews/%d.json" % n: review(pr=n) for n in range(1, 102)}))

    def test_unreadable_file_is_refused(self):
        self.assertTrue(run([added(100)], {}))

    def test_one_bad_file_blocks_the_whole_pr(self):
        heads = {"reviews/100.json": review(), "reviews/101.json": review(pr=101, findings=["http://x"])}
        self.assertTrue(run([added(100), added(101)], heads))


if __name__ == "__main__":
    unittest.main()
