#!/usr/bin/env python3
"""Publish a daily-progress digest into one running Google Doc.

Reads the dated markdown digest the skill already wrote
(`hive_artifacts/daily_progress/YYYY-MM-DD.md`), then inserts a new section
at the TOP of a Google Doc (newest-first). The doc id is remembered locally
so subsequent days append to the same doc.

Auth: uses your existing gcloud Application Default Credentials. The token
needs the Docs scope — if it doesn't, this script prints the one-time
re-consent command and exits. No pip dependencies (stdlib + gcloud only).

Usage:
    python3 publish_gdoc.py [--date YYYY-MM-DD] [--file PATH]
                            [--doc-id ID] [--create] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

DOCS_API = "https://docs.googleapis.com/v1/documents"
ARTIFACT_DIR = "/mnt/c/Users/Evernine/Desktop/hive_artifacts/daily_progress"
ID_FILE = os.path.join(ARTIFACT_DIR, ".gdoc_id")
DOC_TITLE = "Hive — Daily Progress"
SEP = "─" * 40  # ─ separator line
# Preserves the repo's existing ADC scopes (incl. sqlservice.login for the
# Cloud SQL proxy) and ADDS Docs — never drop a scope on re-consent.
RECONSENT = (
    "gcloud auth application-default login --scopes="
    "openid,https://www.googleapis.com/auth/userinfo.email,"
    "https://www.googleapis.com/auth/cloud-platform,"
    "https://www.googleapis.com/auth/sqlservice.login,"
    "https://www.googleapis.com/auth/documents"
)


def _token() -> str:
    out = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"Could not get gcloud token:\n{out.stderr.strip()}\n"
                 f"Run once:\n  {RECONSENT}")
    return out.stdout.strip()


def _api(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        if e.code in (401, 403) and ("insufficient" in detail.lower()
                                     or "scope" in detail.lower()):
            sys.exit("Docs scope missing on your gcloud credentials.\n"
                     f"Run once (opens a browser):\n  {RECONSENT}")
        sys.exit(f"Docs API {method} {url} failed ({e.code}):\n{detail}")


def _parse_digest(path: str) -> tuple[str, list[str], str]:
    """Return (heading, bullets, pace) from the markdown digest."""
    heading, bullets, pace = "", [], ""
    with open(path) as fh:
        for line in fh:
            s = line.rstrip("\n")
            if s.startswith("# "):
                heading = s[2:].strip()
            elif s.lstrip().startswith("- "):
                bullets.append(s.lstrip()[2:].strip())
            elif "**Pace:**" in s or s.startswith("Pace:"):
                pace = s.replace("**Pace:**", "Pace:").replace("**", "").strip()
    if not heading:
        heading = "Progress — " + os.path.basename(path).replace(".md", "")
    return heading, bullets, pace


def _build_section(heading: str, bullets: list[str], pace: str) -> str:
    lines = [heading]
    lines += [f"• {b}" for b in bullets]
    if pace:
        lines.append("")
        lines.append(pace)
    lines.append("")
    lines.append(SEP)
    lines.append("")
    return "\n".join(lines) + "\n"


def _create_doc(token: str) -> str:
    doc = _api("POST", DOCS_API, token, {"title": DOC_TITLE})
    return doc["documentId"]


def _insert_top(token: str, doc_id: str, text: str, heading_len: int) -> None:
    requests = [
        {"insertText": {"location": {"index": 1}, "text": text}},
        # Bold the heading line (first `heading_len` chars of what we inserted).
        {"updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 1 + heading_len},
            "textStyle": {"bold": True},
            "fields": "bold",
        }},
    ]
    _api("POST", f"{DOCS_API}/{doc_id}:batchUpdate", token,
         {"requests": requests})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--file")
    ap.add_argument("--doc-id")
    ap.add_argument("--create", action="store_true",
                    help="force-create a fresh doc and store its id")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent; no API calls")
    args = ap.parse_args()

    date = args.date or datetime.now().astimezone().strftime("%Y-%m-%d")
    path = args.file or os.path.join(ARTIFACT_DIR, f"{date}.md")
    if not os.path.exists(path):
        sys.exit(f"Digest not found: {path}\n"
                 f"Generate it first via the daily-progress skill.")

    heading, bullets, pace = _parse_digest(path)
    section = _build_section(heading, bullets, pace)

    if args.dry_run:
        print(f"[dry-run] would insert at top of doc (date={date}):\n")
        print(section)
        print(f"[dry-run] heading bold range: 1..{1 + len(heading)}")
        return 0

    token = _token()

    doc_id = args.doc_id
    if not doc_id and not args.create and os.path.exists(ID_FILE):
        doc_id = open(ID_FILE).read().strip()
    if not doc_id:
        doc_id = _create_doc(token)
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        with open(ID_FILE, "w") as fh:
            fh.write(doc_id)
        print(f"Created Google Doc: {doc_id}")

    _insert_top(token, doc_id, section, len(heading))
    print(f"Published {date} → https://docs.google.com/document/d/{doc_id}/edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
