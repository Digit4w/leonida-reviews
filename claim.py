#!/usr/bin/env python3
"""Claim a PR before reviewing it, or finish a review.

    python -I claim.py start 7782 --reviewer "name/agent"
    python -I claim.py done  7782 --verdict notes --scope "static, diff only" \
        --finding "first finding" --finding "second finding" [--commented] [--human-read]

`start` fails if reviews/<pr>.json already exists in any verdict folder: someone has it or has done it.
`git pull` first, and push right after `start`, so the others see the claim. Needs gh for the PR head SHA.
Standard library only.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
REPO = "ItsNotRexed/Leonida"
VERDICTS = ("do-not-merge", "notes", "clean", "scan-only", "not-reviewed")
ALL_FOLDERS = VERDICTS + ("in-progress",)


def head_sha(pr):
    out = subprocess.run(["gh", "pr", "view", str(pr), "-R", REPO, "--json", "headRefOid", "-q", ".headRefOid"],
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit("could not read the head SHA of PR #%d: %s" % (pr, out.stderr.strip()))
    return out.stdout.strip()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def find_existing(pr):
    """Check if review exists in any verdict folder."""
    for folder in ALL_FOLDERS:
        path = ROOT / "reviews" / folder / ("%d.json" % pr)
        if path.exists():
            return path, folder
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "done"))
    ap.add_argument("pr", type=int)
    ap.add_argument("--reviewer", default="")
    ap.add_argument("--verdict", choices=VERDICTS)
    ap.add_argument("--scope", default="")
    ap.add_argument("--finding", action="append", default=[])
    ap.add_argument("--commented", action="store_true", help="a comment was posted on the PR")
    ap.add_argument("--human-read", action="store_true", help="a human read the diff, not only the AI's summary")
    args = ap.parse_args()
    today = datetime.date.today().isoformat()

    if args.action == "start":
        existing_path, existing_folder = find_existing(args.pr)
        if existing_path:
            sys.exit("reviews/%s/%d.json already exists: already claimed or reviewed. Pick another PR." % (existing_folder, args.pr))
        if not args.reviewer:
            sys.exit("--reviewer is required")
        path = ROOT / "reviews" / "in-progress" / ("%d.json" % args.pr)
        write(path, {"pr": args.pr, "head_sha": head_sha(args.pr), "reviewer": args.reviewer, "date": today,
                     "scope": "in progress", "verdict": "in-progress", "findings": [],
                     "read_by_human": False, "commented_on_github": False})
        print("claimed #%d. Now: git add reviews && git commit && git push" % args.pr)
        return 0

    # done: read from in-progress, write to verdict folder
    in_progress_path = ROOT / "reviews" / "in-progress" / ("%d.json" % args.pr)
    if not in_progress_path.exists():
        sys.exit("no claim for #%d: run `start` first" % args.pr)
    data = json.loads(in_progress_path.read_text(encoding="utf-8"))
    if args.reviewer and args.reviewer != data["reviewer"]:
        sys.exit("#%d is claimed by %s, not %s" % (args.pr, data["reviewer"], args.reviewer))
    if not args.verdict or not args.scope:
        sys.exit("--verdict and --scope are required for `done`")
    data.update({"verdict": args.verdict, "scope": args.scope, "findings": args.finding, "date": today,
                 "head_sha": head_sha(args.pr), "commented_on_github": args.commented,
                 "read_by_human": args.human_read})
    target_path = ROOT / "reviews" / args.verdict / ("%d.json" % args.pr)
    write(target_path, data)
    # remove the in-progress file
    in_progress_path.unlink()
    print("finished #%d as %s. Now: python -I build_table.py --check, then commit and push." % (args.pr, args.verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
