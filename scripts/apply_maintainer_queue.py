#!/usr/bin/env python3
"""Apply open maintainer PR queue to local main (squash-merge simulation)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )


def fetch_pr(num: int) -> None:
    run("git", "fetch", "origin", f"pull/{num}/head:pr-{num}", check=False)


def merge_squash(num: int, title: str) -> bool:
    fetch_pr(num)
    ref = f"pr-{num}"
    proc = run("git", "rev-parse", "--verify", ref, check=False)
    if proc.returncode != 0:
        print(f"  skip #{num}: cannot fetch ref", file=sys.stderr)
        return False

    merge = run("git", "merge", "--squash", "-X", "theirs", ref, check=False)
    if merge.returncode != 0:
        print(f"  conflict on #{num}, resolving with theirs + sync...", file=sys.stderr)
        run("git", "checkout", "--theirs", ".", check=False)
        run("git", "add", "-A", check=False)

    run("python", "scripts/sync_theme_metadata.py", check=False)
    run("git", "add", "-A", check=False)
    status = run("git", "status", "--porcelain", check=False)
    if not status.stdout.strip():
        print(f"  #{num}: no changes after merge (already on main?)")
        run("git", "reset", "--hard", "HEAD", check=False)
        return True

    msg = f"Apply PR #{num}: {title[:72]}"
    commit = run("git", "commit", "-m", msg, check=False)
    if commit.returncode != 0:
        print(commit.stderr, file=sys.stderr)
        return False
    print(f"  applied #{num}")
    return True


def main() -> int:
    report = json.loads(Path("/tmp/triage-report.json").read_text())
    close = {x[0] for x in report["close_list"]}
    rows = [r for r in report["rows"] if r["number"] not in close]

    order = {"removal": 0, "metadata": 1, "theme": 2}
    rows.sort(key=lambda r: (order.get(r["category"], 9), r["number"]))

    run("git", "fetch", "origin", "main", check=False)
    run("git", "checkout", "-f", "main", check=False)
    run("git", "reset", "--hard", "origin/main", check=False)
    run("git", "checkout", "-B", "maintainer/clear-pr-queue", check=False)

    ok = 0
    fail = 0
    for row in rows:
        n, title = row["number"], row["title"]
        print(f"Merging #{n} ({row['category']})...")
        if merge_squash(n, title):
            ok += 1
        else:
            fail += 1
            run("git", "merge", "--abort", check=False)
            run("git", "reset", "--hard", "HEAD", check=False)

    run("python", "scripts/process_theme_zips.py", check=False)
    run("python", "scripts/backfill_legacy_os_keys.py", check=False)
    run("python", "scripts/sync_theme_metadata.py", check=False)
    run("git", "add", "-A", check=False)
    st = run("git", "status", "--porcelain", check=False)
    if st.stdout.strip():
        run("git", "commit", "-m", "Theme ingest: extract zips and sync themes.json", check=False)

    print(f"\nDone: {ok} applied, {fail} failed")
    print(run("git", "log", "--oneline", "-8", check=False).stdout)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
