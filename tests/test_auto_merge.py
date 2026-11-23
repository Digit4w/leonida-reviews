"""Offline tests for scripts/auto_merge_check.py: no network, no gh. Run: python -I -m unittest discover -s tests

Layout under test: reviews/<verdict>/<number>.json, the folder is the verdict.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import auto_merge_check as amc  # noqa: E402


def review(pr=100, reviewer="alice/claude", verdict="clean", **extra):
    data = {"pr": pr, "head_sha": "abcdef12", "reviewer": reviewer, "date": "2026-11-23", "scope": "static, diff only",
            "verdict": verdict, "findings": ["a plain finding"], "read_by_human": False, "commented_on_github": False}
    data.update(extra)
    return data


PR = {"number": 5, "author": "alice", "draft": False, "state": "open", "base": "main"}


def path(n, folder="clean"):
    return "reviews/%s/%d.json" % (folder, n)


def run(files, heads, mains=None, trusted=True, pr=PR):
    mains = mains or {}
    return amc.evaluate(pr, files, lambda p: heads.get(p), lambda p: mains.get(p), trusted)


def added(n, folder="clean"):
    return {"filename": path(n, folder), "status": "added"}


def one(n=100, folder="clean", **kw):
    """A new review file by alice in its verdict folder."""
    return [added(n, folder)], {path(n, folder): review(pr=n, verdict=folder, **kw)}


class AutoMergeRules(unittest.TestCase):
    def test_plain_new_review_is_mergeable(self):
        files, heads = one()
        self.assertEqual(run(files, heads), [])

    def test_every_verdict_folder_is_accepted(self):
        for folder in ("clean", "notes", "do-not-merge", "scan-only", "not-reviewed", "in-progress"):
            files, heads = one(folder=folder)
            self.assertEqual(run(files, heads), [], folder)

    def test_folder_must_match_the_verdict(self):
        files = [added(100, "clean")]
        self.assertTrue(run(files, {path(100, "clean"): review(verdict="notes")}))

    def test_untrusted_first_contribution_waits_for_a_human(self):
        files, heads = one()
        self.assertTrue(run(files, heads, trusted=False))

    def test_other_files_are_refused(self):
        for name in ("build_table.py", ".github/workflows/table.yml", "docs/index.html", "AUTHORS.md",
                     "reviews/100.json", "reviews/clean/abc.json", "reviews/clean/sub/100.json",
                     "reviews/other/100.json", "reviews/clean/100.json.bak", "reviews/clean/0100x.json",
                     "reviews/../build_table.py", "reviews/clean/../../claim.py"):
            self.assertTrue(run([{"filename": name, "status": "added"}], {}), name)

    def test_copies_are_refused(self):
        self.assertTrue(run([{"filename": path(100), "status": "copied"}], {path(100): review()}))

    def test_removing_a_review_is_refused_but_your_own_claim_can_go(self):
        mine = review(verdict="in-progress")
        self.assertEqual(run([{"filename": path(100, "in-progress"), "status": "removed"}], {},
                             {path(100, "in-progress"): mine}), [])
        # not a claim
        self.assertTrue(run([{"filename": path(100, "clean"), "status": "removed"}], {}, {path(100, "clean"): review()}))
        # someone else's claim
        self.assertTrue(run([{"filename": path(100, "in-progress"), "status": "removed"}], {},
                            {path(100, "in-progress"): review(reviewer="bob/claude", verdict="in-progress")}))
        # a claim that does not exist on main
        self.assertTrue(run([{"filename": path(100, "in-progress"), "status": "removed"}], {}, {}))

    def test_finishing_a_claim_by_rename(self):
        claim = path(100, "in-progress")
        files = [{"filename": path(100, "notes"), "status": "renamed", "previous_filename": claim}]
        heads = {path(100, "notes"): review(verdict="notes")}
        self.assertEqual(run(files, heads, {claim: review(verdict="in-progress")}), [])
        # another reviewer's claim
        self.assertTrue(run(files, heads, {claim: review(reviewer="bob/claude", verdict="in-progress")}))
        # rename that changes the PR number
        bad = [{"filename": path(101, "notes"), "status": "renamed", "previous_filename": claim}]
        self.assertTrue(run(bad, {path(101, "notes"): review(pr=101, verdict="notes")}, {claim: review(verdict="in-progress")}))
        # rename from a path that is not a review
        bad = [{"filename": path(100, "notes"), "status": "renamed", "previous_filename": "README.md"}]
        self.assertTrue(run(bad, heads, {}))

    def test_finishing_a_claim_as_add_plus_remove(self):
        claim = path(100, "in-progress")
        files = [{"filename": claim, "status": "removed"}, added(100, "clean")]
        heads = {path(100, "clean"): review()}
        self.assertEqual(run(files, heads, {claim: review(verdict="in-progress")}), [])

    def test_adding_a_second_review_for_the_same_pr_is_refused(self):
        files, heads = one(100, "clean")
        self.assertTrue(run(files, heads, {path(100, "notes"): review(reviewer="bob/claude", verdict="notes")}))
        self.assertTrue(run(files, heads, {path(100, "in-progress"): review(verdict="in-progress")}))

    def test_cannot_file_a_review_in_someone_elses_name(self):
        for who in ("bob/claude", "alice-evil/claude"):
            files, heads = one(reviewer=who)
            self.assertTrue(run(files, heads), who)

    def test_file_name_must_match_pr_field(self):
        files = [added(100)]
        self.assertTrue(run(files, {path(100): review(pr=101)}))
        self.assertTrue(run(files, {path(100): review(pr=True)}))

    def test_modification_must_keep_the_reviewer(self):
        f = [{"filename": path(100), "status": "modified"}]
        heads = {path(100): review()}
        self.assertEqual(run(f, heads, {path(100): review()}), [])
        self.assertTrue(run(f, heads, {path(100): review(reviewer="bob/claude")}))
        self.assertTrue(run(f, heads, {}))

    def test_links_html_markdown_and_invisible_text_are_refused(self):
        for text in ("see https://example.com", "<img src=x>", "[x](http://y)", "![i](j)", "javascript:alert(1)",
                     "zero​width", "bidi‮evil", "ctrl\x07", "x" * 401):
            files, _ = one()
            self.assertTrue(run(files, {path(100): review(findings=[text])}), repr(text))
            self.assertTrue(run(files, {path(100): review(scope=text)}), repr(text))

    def test_unknown_or_wrongly_typed_fields_are_refused(self):
        files = [added(100)]
        for bad in (review(verdict="safe"), review(extra_field=1), review(head_sha="../../x"), review(date="yesterday"),
                    review(read_by_human="yes"), review(findings="not a list"), review(findings=["f"] * 21),
                    ["not", "an", "object"]):
            self.assertTrue(run(files, {path(100): bad}))

    def test_draft_closed_or_other_base_is_refused(self):
        files, heads = one()
        for change in ({"draft": True}, {"state": "closed"}, {"base": "dev"}):
            self.assertTrue(run(files, heads, pr=dict(PR, **change)), change)

    def test_empty_and_huge_prs_are_refused(self):
        self.assertTrue(run([], {}))
        many = [added(n) for n in range(1, 102)]
        self.assertTrue(run(many, {path(n): review(pr=n) for n in range(1, 102)}))

    def test_unreadable_file_is_refused(self):
        self.assertTrue(run([added(100)], {}))

    def test_one_bad_file_blocks_the_whole_pr(self):
        heads = {path(100): review(), path(101): review(pr=101, findings=["http://x"])}
        self.assertTrue(run([added(100), added(101)], heads))


if __name__ == "__main__":
    unittest.main()
