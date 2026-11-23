#!/usr/bin/env python3
"""Write docs/coverage.json: how much of Leonida's open pull request queue has a review on record.

    python -I scripts/coverage.py                 # list the open PRs with gh, then write docs/coverage.json
    python -I scripts/coverage.py --open-file F   # read the open PR numbers from F (one per line) instead: tests, offline

Run by the table workflow on its schedule, not on every push: listing about 4,500 open PRs is about 45 API calls.
It only reads: the open PR numbers of ItsNotRexed/Leonida, and this repository's own review files. Standard library
only; needs gh and GH_TOKEN unless --open-file is given. If the listing fails, nothing is written and the old file
stays, so the page keeps the last known numbers and their time.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_table  # noqa: E402

REPO = "ItsNotRexed/Leonida"
NEWEST = 30          # how many unreviewed PR numbers the page lists as free to take


def open_numbers_from_gh():
    out = subprocess.run(["gh", "api", "--paginate", "repos/%s/pulls?state=open&per_page=100" % REPO, "--jq", ".[].number"],
                         capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError("gh could not list the open pull requests: %s" % out.stderr.strip()[:300])
    return parse_numbers(out.stdout)


def parse_numbers(text):
    numbers = set()
    for line in text.split():
        if line.isdigit():
            numbers.add(int(line))
    return numbers


def summarize(open_numbers, rows, as_of):
    """rows: the reviews build_table.load() returns. Every count is about PRs that are open right now."""
    verdict = {r["pr"]: r["verdict"] for r in rows}
    in_progress = {n for n in open_numbers if verdict.get(n) == "in-progress"}
    scan_only = {n for n in open_numbers if verdict.get(n) == "scan-only"}
    reviewed = {n for n in open_numbers if n in verdict} - in_progress
    unreviewed = sorted(open_numbers - reviewed - in_progress, reverse=True)
    return {"as_of": as_of, "open_total": len(open_numbers), "reviewed_open": len(reviewed),
            "scan_only_open": len(scan_only), "in_progress_open": len(in_progress),
            "unreviewed_total": len(unreviewed), "newest_unreviewed": unreviewed[:NEWEST]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-file")
    args = ap.parse_args()
    rows, errors = build_table.load()
    if errors:
        for e in errors:
            print("error:", e, file=sys.stderr)
        return 1
    try:
        numbers = (parse_numbers(pathlib.Path(args.open_file).read_text(encoding="utf-8")) if args.open_file
                   else open_numbers_from_gh())
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        print("coverage not updated:", e, file=sys.stderr)
        return 0
    if not numbers:
        print("coverage not updated: the open pull request list came back empty", file=sys.stderr)
        return 0
    as_of = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = summarize(numbers, rows, as_of)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "coverage.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("docs/coverage.json written: %d open, %d reviewed, %d unreviewed" % (
        data["open_total"], data["reviewed_open"], data["unreviewed_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
