#!/usr/bin/env python3
"""Finish clearing the theme PR queue: close duplicates, merge batch PR, close superseded PRs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = "y1-community/InnioasisY1Themes"
FORK_HEAD = "ryan-specter:maintainer/clear-pr-queue"
ROOT = Path(__file__).resolve().parent.parent
GH = Path.home() / ".local/bin/gh"
if not GH.is_file():
    GH = Path("gh")


def run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env:
        t = subprocess.run([str(GH), "auth", "token"], capture_output=True, text=True, check=False)
        if t.returncode == 0 and t.stdout.strip():
            env["GH_TOKEN"] = t.stdout.strip()
    return subprocess.run(
        list(args),
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        env=env,
    )


def gh(*args: str) -> tuple[int, str, str]:
    p = run(str(GH), *args, check=False)
    return p.returncode, p.stdout, p.stderr


def can_write_upstream() -> bool:
    code, out, err = gh("api", f"repos/{REPO}", "--jq", ".permissions.push")
    if code == 0 and out.strip() == "true":
        return True
    # dry-run push
    token = os.environ.get("GH_TOKEN") or subprocess.run(
        [str(GH), "auth", "token"], capture_output=True, text=True, check=False
    ).stdout.strip()
    if not token:
        return False
    p = subprocess.run(
        ["git", "push", "--dry-run", f"https://x-access-token:{token}@github.com/{REPO}.git", "HEAD:refs/heads/_perm-test"],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    return p.returncode == 0 and "denied" not in (p.stderr + p.stdout).lower()


def main() -> int:
    if not can_write_upstream():
        print(
            "ERROR: GH_TOKEN cannot merge/close PRs on y1-community/InnioasisY1Themes.\n"
            "Fix: https://github.com/settings/tokens — edit this fine-grained PAT:\n"
            "  - Repository access: add y1-community/InnioasisY1Themes\n"
            "  - Permissions: Contents (R/W), Pull requests (R/W)\n"
            "  - Configure SSO for y1-community if prompted\n"
            "Then open PR manually:\n"
            "  https://github.com/y1-community/InnioasisY1Themes/compare/main...ryan-specter:maintainer/clear-pr-queue?expand=1\n"
            "Branch maintainer/clear-pr-queue is pushed to ryan-specter/y1-rockbox-themes (fork).",
            file=sys.stderr,
        )
        return 2

    report_path = Path("/tmp/triage-report.json")
    if not report_path.is_file():
        print("Missing /tmp/triage-report.json — run scripts/triage_open_prs.py first", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text())

    closed = 0
    for old, keep, _ in sorted(report["close_list"], reverse=True):
        code, _, err = gh("pr", "close", str(old), "--repo", REPO)
        if code == 0:
            closed += 1
            print(f"closed duplicate #{old} (keep #{keep})")
        else:
            print(f"skip close #{old}: {err.strip()[:120]}", file=sys.stderr)
        time.sleep(0.2)

    code, out, err = gh(
        "pr", "create", "--repo", REPO,
        "--base", "main", "--head", FORK_HEAD,
        "--title", "Maintainer batch: clear open theme PR queue",
        "--body", "Batch apply of 46 unique open PRs (removals, metadata, themes). Closes duplicate upload PRs.",
    )
    batch_num = None
    if code == 0:
        for line in out.splitlines():
            if "/pull/" in line:
                batch_num = line.rstrip("/").split("/")[-1]
        print(f"created batch PR: {out.strip()}")
    else:
        _, listed, _ = gh("pr", "list", "--repo", REPO, "--state", "open", "--search", "Maintainer batch", "--json", "number", "--jq", ".[0].number")
        if listed.strip():
            batch_num = listed.strip()
            print(f"using existing batch PR #{batch_num}")

    if batch_num:
        code, _, err = gh("pr", "merge", batch_num, "--repo", REPO, "--squash", "--delete-branch")
        if code != 0:
            print(f"batch merge failed: {err}", file=sys.stderr)
            return 1
        print(f"merged batch PR #{batch_num}")
        time.sleep(30)
        run("git", "fetch", "origin", "main", check=False)
        run("git", "checkout", "main", check=False)
        run("git", "reset", "--hard", "origin/main", check=False)

    keep = {r["number"] for r in report["rows"]} - {x[0] for x in report["close_list"]}
    _, open_json, _ = gh("pr", "list", "--repo", REPO, "--state", "open", "--limit", "100", "--json", "number,title")
    try:
        open_prs = json.loads(open_json)
    except json.JSONDecodeError:
        open_prs = []
    for pr in open_prs:
        n = pr["number"]
        if batch_num and str(n) == str(batch_num):
            continue
        msg = f"Superseded by maintainer batch PR #{batch_num}." if batch_num else "Superseded by maintainer batch merge to main."
        code, _, _ = gh("pr", "close", str(n), "--repo", REPO, "--comment", msg)
        if code == 0:
            print(f"closed superseded #{n}: {pr['title'][:50]}")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
