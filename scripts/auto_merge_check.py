#!/usr/bin/env python3
"""Decide whether a pull request to this repository may be merged without a human, and merge it if so.

Run by .github/workflows/automerge.yml on pull_request_target, from the BASE branch. It never checks out, imports or
runs anything from the pull request: it only reads the PR's file list and the content of its review files through the
GitHub API, as data.

A PR is merged automatically only when ALL of these hold:
  * it is open, not a draft, and targets main;
  * it changes at most MAX_FILES files and every one is reviews/<number>.json, added or modified, never removed or
    renamed, each at most MAX_BYTES;
  * each file is valid by the same rules build_table.py uses, its name matches its "pr" field, and its "reviewer"
    starts with the PR author's login (so nobody can file a review in someone else's name);
  * the text fields hold no link, HTML, markdown link, control or invisible characters, and stay short;
  * a modified file keeps the same reviewer as the file on main (nobody rewrites another reviewer's verdict);
  * the author is a collaborator/owner, or already had a pull request merged here (first contributions get a human).

Anything else is left for a human and the reason is printed. Exit status is always 0 unless the merge call itself fails.
Standard library only; needs gh and GH_TOKEN.

    python -I scripts/auto_merge_check.py PR_NUMBER [--dry-run]
"""
import argparse
import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_table  # noqa: E402  (base-branch copy: this script is run from the base checkout)

MAX_FILES = 100
MAX_BYTES = 20 * 1024
MAX_TEXT = 400
MAX_FINDINGS = 20
NAME = re.compile(r"^reviews/([0-9]{1,6})\.json$")
SHA = re.compile(r"^(unknown|[0-9a-f]{7,40})$")
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
BAD_TEXT = re.compile(r"https?://|ftp://|javascript:|data:|<[a-zA-Z/!]|\]\(|!\[|`{3}", re.I)


def gh(*args, check=True, raw=False):
    out = subprocess.run(["gh", *args], capture_output=True, timeout=60)
    if out.returncode != 0:
        if check:
            raise RuntimeError("gh %s: %s" % (" ".join(args[:3]), out.stderr.decode("utf-8", "replace").strip()))
        return None
    return out.stdout if raw else out.stdout.decode("utf-8", "replace")


def clean_text(value, label, problems):
    if not isinstance(value, str):
        problems.append("%s must be text" % label)
        return
    if len(value) > MAX_TEXT:
        problems.append("%s is longer than %d characters" % (label, MAX_TEXT))
    if BAD_TEXT.search(value):
        problems.append("%s contains a link, HTML or markdown that needs a human look" % label)
    for ch in value:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Co", "Cs") or (ch in "  "):
            problems.append("%s contains a control or invisible character" % label)
            break


def check_review(path, number, data, author):
    """Return a list of reasons this file cannot be merged automatically (empty = fine)."""
    problems = []
    if not isinstance(data, dict):
        return ["%s is not a JSON object" % path]
    missing = [k for k in build_table.REQUIRED if k not in data]
    if missing:
        return ["%s is missing: %s" % (path, ", ".join(missing))]
    extra = sorted(set(data) - set(build_table.REQUIRED))
    if extra:
        problems.append("%s has unknown fields: %s" % (path, ", ".join(extra)))
    if not isinstance(data["pr"], int) or isinstance(data["pr"], bool) or data["pr"] != number:
        problems.append("%s: the pr field must be the number %d" % (path, number))
    if data["verdict"] not in build_table.VERDICTS:
        problems.append("%s: unknown verdict" % path)
    if not isinstance(data["head_sha"], str) or not SHA.match(data["head_sha"]):
        problems.append("%s: head_sha must be unknown or 7 to 40 hex characters" % path)
    if not isinstance(data["date"], str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", data["date"]):
        problems.append("%s: date must be YYYY-MM-DD" % path)
    for key in ("read_by_human", "commented_on_github"):
        if not isinstance(data[key], bool):
            problems.append("%s: %s must be true or false" % (path, key))
    for key in ("reviewer", "scope"):
        clean_text(data[key], "%s %s" % (path, key), problems)
    if not isinstance(data["findings"], list) or len(data["findings"]) > MAX_FINDINGS:
        problems.append("%s: findings must be a list of at most %d texts" % (path, MAX_FINDINGS))
    else:
        for i, finding in enumerate(data["findings"]):
            clean_text(finding, "%s finding %d" % (path, i + 1), problems)
    reviewer = data["reviewer"] if isinstance(data["reviewer"], str) else ""
    if reviewer.split("/", 1)[0].lower() != author.lower():
        problems.append("%s: reviewer must start with the PR author's login (%s)" % (path, author))
    return problems


def evaluate(pr, files, read_head, read_main, trusted_author):
    """pr: dict(number, author, draft, state, base). files: list of dict(filename, status, size).
    read_head(path) / read_main(path) return parsed JSON or None. Returns a list of reasons; empty means mergeable."""
    reasons = []
    if pr["state"] != "open" or pr["draft"] or pr["base"] != "main":
        reasons.append("the PR must be open, not a draft, and target main")
    if not files:
        reasons.append("the PR changes no file")
    if len(files) > MAX_FILES:
        reasons.append("more than %d files" % MAX_FILES)
        return reasons
    for f in files:
        m = NAME.match(f["filename"])
        if not m:
            reasons.append("%s is not a review file (only reviews/<number>.json can be merged automatically)" % f["filename"])
            continue
        if f["status"] not in ("added", "modified"):
            reasons.append("%s is %s: removals and renames need a human" % (f["filename"], f["status"]))
            continue
        if f.get("size", 0) > MAX_BYTES:
            reasons.append("%s is larger than %d bytes" % (f["filename"], MAX_BYTES))
            continue
        data = read_head(f["filename"])
        if data is None:
            reasons.append("%s could not be read as JSON" % f["filename"])
            continue
        reasons += check_review(f["filename"], int(m.group(1)), data, pr["author"])
        if f["status"] == "modified":
            old = read_main(f["filename"])
            if not isinstance(old, dict) or str(old.get("reviewer", "")).lower() != str(data.get("reviewer", "")).lower():
                reasons.append("%s: a modification must keep the reviewer of the existing file" % f["filename"])
    if not trusted_author:
        reasons.append("first contribution by %s: a human merges the first one" % pr["author"])
    return reasons


def load_json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pr", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    repo = os.environ.get("GITHUB_REPOSITORY", "Etoile-Bleu/leonida-reviews")

    meta = json.loads(gh("api", "repos/%s/pulls/%d" % (repo, args.pr)))
    head_sha = meta["head"]["sha"]
    head_repo = (meta["head"].get("repo") or {}).get("full_name")
    pr = {"number": args.pr, "author": meta["user"]["login"], "draft": bool(meta["draft"]), "state": meta["state"],
          "base": meta["base"]["ref"]}
    if not head_repo:
        print("not merged automatically: the source repository no longer exists")
        return 0
    page1 = json.loads(gh("api", "repos/%s/pulls/%d/files?per_page=100&page=1" % (repo, args.pr)))
    page2 = json.loads(gh("api", "repos/%s/pulls/%d/files?per_page=100&page=2" % (repo, args.pr))) if len(page1) == 100 else []
    # More than 100 files is over MAX_FILES anyway; the size of each file is checked when its content is read.
    files = [{"filename": f["filename"], "status": f["status"]} for f in page1 + page2]

    def read_ref(repo_name, path, ref):
        raw = gh("api", "-H", "Accept: application/vnd.github.raw", "repos/%s/contents/%s?ref=%s" % (repo_name, path, ref),
                 check=False, raw=True)
        if raw is None:
            return None
        if len(raw) > MAX_BYTES:
            return {"__too_large__": True}
        return load_json(raw)

    def read_head(path):
        data = read_ref(head_repo, path, head_sha)
        if isinstance(data, dict) and data.get("__too_large__"):
            return None
        return data

    def read_main(path):
        return read_ref(repo, path, "main")

    assoc = meta.get("author_association", "NONE")
    trusted = assoc in TRUSTED
    if not trusted:
        found = gh("api", "-X", "GET", "search/issues", "-f", "q=repo:%s is:pr is:merged author:%s" % (repo, pr["author"]),
                   "-q", ".total_count", check=False)
        trusted = bool(found and found.strip().isdigit() and int(found.strip()) >= 1)

    reasons = evaluate(pr, files, read_head, read_main, trusted)
    if reasons:
        print("PR #%d is left for a human:" % args.pr)
        for r in reasons:
            print("  -", r)
        return 0
    print("PR #%d passes every rule (%d files, author %s, head %s)." % (args.pr, len(files), pr["author"], head_sha[:8]))
    if args.dry_run:
        print("dry run: not merging")
        return 0
    # --match-head-commit: if the author pushed again after the checks above, GitHub refuses and the next run decides.
    out = subprocess.run(["gh", "pr", "merge", str(args.pr), "-R", repo, "--merge", "--match-head-commit", head_sha],
                         capture_output=True, text=True, timeout=60)
    print(out.stdout.strip() or out.stderr.strip())
    return 0 if out.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
