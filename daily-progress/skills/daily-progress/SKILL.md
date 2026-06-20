---
name: daily-progress
description: Generate an end-of-day progress digest of what was accomplished in the last 24h, by reading the day's git commits and Claude session transcripts and distilling them into a plain-language summary (objective, what we did, why it matters) that any reader can follow, plus a separate technical section for developers and a pace metric. Use when the user asks for a daily summary, "what did we do today", end-of-day report, standup notes, progress log, or wants to track/share team output with their organization.
---

# Daily Progress Digest

Produce a crisp end-of-day record of real work done, for organization
visibility and pace tracking. Two authoritative sources are combined:

- **Git commits** in the window — what *shipped* (and, from the subject, how).
- **Claude session transcripts** — what was *worked on*, including research,
  audits, and debugging that never produced a commit.

The script gathers; **you synthesise**. Never invent work — every point must
trace to a commit or a session request in the gathered material.

## Workflow

1. **Gather** the day's raw material (defaults to today, local calendar day):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/daily-progress/scripts/gather_day.py" --date YYYY-MM-DD
   ```
   - Omit `--date` for today. Add `--start-hour 1` only if the user wants the
     1 AM→11:59 PM cycle instead of full midnight-to-midnight.
   - Read-only. Secrets (API keys, tokens, JWTs) are auto-redacted.

2. **Synthesise the digest in two tiers — anchored on git commits.** The day's
   **git commits are the source of truth** for what was done; group related
   commits into one outcome each. Write the digest so it serves *both* a
   non-technical reader (CEO, teammates) and an engineer:

   **Tier 1 — plain-language summary (no jargon).** Three parts:
   - **Objective for the day** — 1-3 sentences on what the day was trying to
     achieve, inferred from the commits + the user's session requests.
   - **What we did** — one bullet per outcome. Add as many bullets as the work
     genuinely needs to be understood, but never pad and don't overdo it. Say
     what it *means* in plain words — no file names, no module names, no
     acronyms. Translate every bit of jargon ("ROAS" → "return on ad spend",
     "RLS" → "each brand's data kept separate"). Leave a blank line between
     bullets so it scans easily.
   - **Why it matters** — a short paragraph on the impact: what this unblocks
     or improves for the business or its users.

   **Tier 2 — technical detail (for developers).** After a `---` divider, a
   `## Technical detail (for developers)` section where jargon is welcome:
   PR numbers, module/file names, formula fixes, the precise mechanics — one
   bullet per outcome, mapping back to the plain bullets above.

   - **Only committed project work is an outcome.** Use the session transcripts
     ONLY to understand/explain the commits (the objective + the "how"), never
     as a source of separate outcomes. EXCLUDE meta/tooling work that wasn't a
     project commit — building skills, connecting integrations, env/API setup,
     research. A substantial read-only investigation may be noted briefly, but
     label it "(no commits)".
   - Skip pure-mechanical churn (lint, import drops, formatting) unless that
     *was* the day's work.

3. **Add a one-line Pace footer** from the script's metrics, e.g.
   `Pace: 8 commits · 23 files · 2 sessions · 27 requests.`

4. **Write the digest** to `<OUT>/YYYY-MM-DD.md` (create dirs as needed) using
   the format below, and append/update a one-line entry in `<OUT>/INDEX.md`
   (`- [YYYY-MM-DD](YYYY-MM-DD.md) — <3-5 word headline>`).
   - `<OUT>` resolves to `$DAILY_PROGRESS_DIR` if that env var is set,
     otherwise `~/daily-progress/`. This keeps the tool portable across
     machines — never hardcode an absolute path.

5. **Publish to Notion — upsert by Date** (one row per day, never duplicate).
   *Optional.* Decide the path by what's available:

   **(a) Notion MCP connected AND a data source known** (env var
   `$DAILY_PROGRESS_NOTION_DS` set, or the user gave a URL earlier) → publish:
   - **First, look for an existing row for this Date** — `notion-search` /
     `notion-fetch` the data source and match the Date title.
   - **If a row exists → overwrite it in place:** `notion-update-page` with
     `command: replace_content` (rewrites the whole body with the fresh
     digest) + `command: update_properties` (refresh Headline/Commits/Files).
     This wipes the old content and rewrites — no second row.
   - **If no row exists → create one:** `notion-create-pages` under the data
     source. If the "Daily Progress" database itself doesn't exist yet, offer
     to create it with `notion-create-database` using the schema below.
   - Headline = 3-6 word summary. Date, Commits, Files come from the gather
     script's metrics; the full two-tier digest body (plain-language summary +
     Technical detail section) + Pace line go in the page body.

   **(b) Notion MCP connected but no data source known** → `notion-search` for
   a "Daily Progress" database; if found, confirm and use it. If none, offer to
   create one (schema below), then publish. Remember the data source for next
   time (tell the user to set `DAILY_PROGRESS_NOTION_DS` so it's automatic).

   **(c) No Notion MCP connected** → still finish (local file + chat output are
   complete on their own), then print the **one-time setup brief** below so the
   user can turn on syncing. Print it once; don't nag every run.

   ```
   📋 Optional: sync these digests to a Notion board (team command center)
     1. Need a Notion account — free at https://notion.so (any workspace works).
     2. Connect Notion to Claude Code: run /mcp, pick "notion", and authorise
        in the browser. (One time per machine.)
     3. Re-run /daily-progress. I'll find or create a "Daily Progress"
        database and start upserting one row per day.
     4. To always target a shared team board, set the env var
        DAILY_PROGRESS_NOTION_DS to that database's data-source id/URL
        (ask whoever owns the team board for it).
   ```

6. **Print the digest in chat** too, so the user can paste it straight into
   a standup / Slack / status update.

## Notion database schema ("Daily Progress")

| Property | Type | Source |
|---|---|---|
| Date | Date (title or date prop) | the day |
| Headline | Text | 3-6 word summary |
| Commits | Number | gather `commits in window` |
| Files | Number | gather `files changed` |
| (body) | page body | the two-tier digest |

> Notion MCP auth is session-only — fine for on-demand. For an unattended
> nightly run, use a Notion internal-integration token in `.env` + a stdlib
> publisher (build on request). An optional Google Doc publisher also exists:
> `scripts/publish_gdoc.py` (needs an Internal OAuth client; see git history).

## Output format

```md
# Progress — YYYY-MM-DD

**Objective for the day.** <1-3 plain sentences on what the day aimed to do.>

## What we did

- **<plain outcome 1>** — <what it means, no jargon.>

- **<plain outcome 2>** — <…>

- ... (as many as the work needs — don't pad)

## Why it matters

<short paragraph on the business / user impact.>

---

## Technical detail (for developers)

- **<outcome 1>:** <PRs, modules, mechanics — jargon OK.>
- **<outcome 2>:** <…>

**Pace:** N commits · N files · N sessions · N requests
```

## Rules

- **Always two tiers:** a plain-language summary (Objective / What we did / Why
  it matters) anyone can read, then a `Technical detail (for developers)`
  section. Never collapse them into one.
- The plain tier carries **no jargon, file names, or acronyms** — translate
  everything into business English. The technical tier carries the precise
  detail.
- As many outcome bullets as the work needs; **never pad, and don't overdo it.**
  Use blank lines between bullets for readability.
- One outcome per bullet; combine many commits into one if they share a goal.
- Faithful: no claim without a commit or request behind it. If the day was
  research-only (no commits), say so plainly.
- No personal names, no secrets in the digest.
- Multiple committers may appear (`by <author>`); attribute team-wide work as
  "we" unless the user wants per-person breakdown.
