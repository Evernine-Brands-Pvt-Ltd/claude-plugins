#!/usr/bin/env python3
"""Gather raw material for a daily progress digest.

Collects, for one local-day window, the two authoritative records of work:
  1. Git commits in the window (what shipped + how)
  2. Claude Code session transcripts in the window (what was worked on,
     including research/audits/debugging that never produced a commit)

Output is condensed markdown on stdout. It is RAW MATERIAL — the calling
agent reads it and synthesises the 5-10 human-facing bullets. This script
makes no judgements and writes no files (read-only).

Usage:
    python3 gather_day.py [--date YYYY-MM-DD] [--start-hour 0]
                          [--project-dir /abs/path] [--max-prompts 60]

Defaults: date=today (local), start-hour=0 (full calendar day),
project-dir=current working directory.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta


def _local_window(date_str: str | None, start_hour: int) -> tuple[datetime, datetime, str]:
    """Return (start, end, label) as local-aware datetimes for the day."""
    if date_str:
        base = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        base = datetime.now()
    base = base.astimezone()  # attach local tz
    start = base.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    label = start.strftime("%Y-%m-%d")
    return start, end, label


def _find_project_dir(cwd: str) -> str | None:
    """Locate the ~/.claude/projects transcript dir for this repo.

    Claude encodes the project path by replacing every non-alphanumeric
    char with '-'. Fall back to scanning for a dir whose transcripts carry
    a matching `cwd` field.
    """
    root = os.path.expanduser("~/.claude/projects")
    encoded = re.sub(r"[^A-Za-z0-9]", "-", cwd)
    guess = os.path.join(root, encoded)
    if os.path.isdir(guess):
        return guess
    # Fallback: scan for a dir whose first transcript records this cwd.
    for d in glob.glob(os.path.join(root, "*")):
        for f in glob.glob(os.path.join(d, "*.jsonl"))[:1]:
            try:
                with open(f) as fh:
                    for line in fh:
                        rec = json.loads(line)
                        if rec.get("cwd") == cwd:
                            return d
                        break
            except Exception:
                pass
    return None


def _parse_ts(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except Exception:
        return None


def _human_text(msg: dict) -> str | None:
    """Extract a real human prompt; skip tool-result echoes and noise."""
    c = msg.get("content")
    text = None
    if isinstance(c, str):
        text = c
    elif isinstance(c, list):
        parts = []
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_result":
                return None  # this is a tool result, not a human turn
            if b.get("type") == "text":
                parts.append(b.get("text", ""))
        text = " ".join(parts).strip()
    if not text:
        return None
    text = " ".join(text.split())
    if text.startswith("<") or text.startswith("Caveat:"):
        return None  # system reminders / harness noise
    return _redact(text)


# Scrub secret-like tokens so they never reach the digest or terminal.
_SECRET_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_.-]{20,})"
)


def _redact(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED-SECRET]", text)


_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _scan_transcripts(proj_dir: str, start, end, max_prompts: int) -> dict:
    prompts: list[tuple[datetime, str]] = []
    files_touched: set[str] = set()
    tool_counts: dict[str, int] = {}
    titles: set[str] = set()
    sessions_in_window: set[str] = set()
    assistant_turns = 0

    for f in glob.glob(os.path.join(proj_dir, "*.jsonl")):
        try:
            fh = open(f)
        except Exception:
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") in ("ai-title", "summary") and rec.get("title"):
                    titles.add(rec["title"])
                ts = _parse_ts(rec.get("timestamp"))
                if ts is None or not (start <= ts <= end):
                    continue
                sid = rec.get("sessionId") or os.path.basename(f)
                sessions_in_window.add(sid)
                t = rec.get("type")
                msg = rec.get("message")
                if t == "user" and isinstance(msg, dict):
                    txt = _human_text(msg)
                    if txt:
                        prompts.append((ts, txt))
                elif t == "assistant" and isinstance(msg, dict):
                    assistant_turns += 1
                    content = msg.get("content")
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                name = b.get("name", "?")
                                tool_counts[name] = tool_counts.get(name, 0) + 1
                                if name in _EDIT_TOOLS:
                                    fp = (b.get("input") or {}).get("file_path")
                                    if fp:
                                        files_touched.add(fp)

    prompts.sort(key=lambda p: p[0])
    # Dedupe consecutive identical prompts; truncate each.
    seen_last = None
    cleaned = []
    for ts, txt in prompts:
        if txt == seen_last:
            continue
        seen_last = txt
        cleaned.append((ts, txt[:200]))
    return {
        "prompts": cleaned[:max_prompts],
        "prompt_total": len(cleaned),
        "files_touched": sorted(files_touched),
        "tool_counts": tool_counts,
        "sessions": len(sessions_in_window),
        "assistant_turns": assistant_turns,
        "titles": sorted(titles),
    }


def _git(args: list[str], cwd: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except Exception:
        return ""


def _gather_git(cwd: str, start, end) -> dict:
    since = start.strftime("%Y-%m-%d %H:%M:%S")
    until = end.strftime("%Y-%m-%d %H:%M:%S")
    raw = _git(
        ["log", "--all", "--no-merges", f"--since={since}", f"--until={until}",
         "--pretty=format:%h\x1f%an\x1f%s"], cwd)
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            commits.append({"hash": parts[0], "author": parts[1], "subject": parts[2]})
    # Files changed across the window.
    numstat = _git(
        ["log", "--all", "--no-merges", f"--since={since}", f"--until={until}",
         "--numstat", "--pretty=format:"], cwd)
    files = {ln.split("\t")[-1] for ln in numstat.splitlines() if "\t" in ln}
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return {"commits": commits, "files_changed": len(files), "branch": branch}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--start-hour", type=int, default=0)
    ap.add_argument("--project-dir", default=os.getcwd())
    ap.add_argument("--max-prompts", type=int, default=60)
    args = ap.parse_args()

    cwd = os.path.abspath(args.project_dir)
    start, end, label = _local_window(args.date, args.start_hour)

    out: list[str] = []
    out.append(f"# Daily activity — {label}")
    out.append(f"_Window: {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} (local)_")
    out.append("")

    git = _gather_git(cwd, start, end)
    out.append(f"## Git commits in window ({len(git['commits'])})")
    out.append(f"Current branch: `{git['branch']}` · files changed: {git['files_changed']}")
    if git["commits"]:
        for c in git["commits"]:
            out.append(f"- `{c['hash']}` {c['subject']}  _(by {c['author']})_")
    else:
        out.append("- (no commits — work may be uncommitted / research-only)")
    out.append("")

    proj = _find_project_dir(cwd)
    if not proj:
        out.append("## Claude sessions\n- (no transcript dir found for this repo)")
        print("\n".join(out))
        return 0

    sess = _scan_transcripts(proj, start, end, args.max_prompts)
    out.append("## Claude session activity")
    out.append(
        f"Sessions: {sess['sessions']} · assistant turns: {sess['assistant_turns']} "
        f"· user requests: {sess['prompt_total']} · files edited via tools: "
        f"{len(sess['files_touched'])}"
    )
    if sess["tool_counts"]:
        tc = ", ".join(f"{k}×{v}" for k, v in sorted(
            sess["tool_counts"].items(), key=lambda x: -x[1])[:8])
        out.append(f"Top tools: {tc}")
    out.append("")
    out.append("### User requests (chronological — the work asked for)")
    if sess["prompts"]:
        for ts, txt in sess["prompts"]:
            out.append(f"- {ts:%H:%M} — {txt}")
    else:
        out.append("- (none in window)")
    if sess["files_touched"]:
        out.append("")
        out.append("### Files edited via tools")
        for fp in sess["files_touched"][:40]:
            out.append(f"- {fp}")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
