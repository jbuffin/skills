#!/usr/bin/env python3
"""Break down where a commodore coordinator's context goes, from its Claude Code session transcripts.

usage: coordinator-tokens.py [--days N] [--min-calls N] [--units N] [--raw] [--sessions] [--simulate-handoff]
                             [--json] [transcript.jsonl | projects-dir ...]

With no paths it scans ~/.claude*/projects/*/ for sessions that invoked commodore (or the older agent-team skills)
as a slash command in the last --days days. A path may be a transcript or a projects directory.

For each API call the context is input + cache read + cache write. The growth since the previous call is split
across what was added in between (tool results, tool inputs, attachments, assistant text) in proportion to their
characters. An item's carry is its tokens times the calls that re-read it before the context next shrinks
(a compaction). Summed, carry matches the sessions' cache reads, so it shows which sources drive cost.

Calls per unit divides the API calls by the run's units. --units N sets the count; otherwise each session's run
directory is the one whose state.md its tool calls name most, and its units are the rows of the Units table (or the
`- uN →` bullets of the older format). Sessions of the same run count its units once.

--simulate-handoff replays each session as if the coordinator restarted fresh whenever its context passed a
threshold, resetting to the session's first-call context plus RESUME_TOKENS for re-reading state and references.
"""

import argparse
import collections
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

COORD = re.compile(r"command-name>/[^<]*\b(commodore|agent-team[\w-]*)</command-name>")
NOT_COORD = re.compile(r"setup-commodore|commodore-launcher")
SCRIPTS = re.compile(
    r"(verify-report|watch-teammates|watch-ci|teammate-tail|team-preflight|advisor-probe|launch-teammate|"
    r"close-teammate|retasked|retask|team-init|role-skills|push-branch|unit-worktree|evidence|team-env|state-set|"
    r"review-round|admiral-io)\.(sh|zsh)"
)
COMPACTION_DROP = 2000
RESUME_TOKENS = 35_000
STATE_PATH = re.compile(r"[~\w/.$-]*/teams/[\w.-]+/state\.md")
HANDOFF_THRESHOLDS = (150_000, 200_000, 300_000)
MIN_TRANSCRIPT_BYTES = 200_000
MIN_SHARE_SHOWN = 0.002

# Raw categories collapse into these groups, first match wins.
GROUPS = [
    (r"^initial", "base prompt (system, tools, MCP, skill listing)"),
    (r"post-compact|compact-summary", "compaction"),
    (r"read:report|read-report", "teammate reports read in full"),
    (r"verify-report", "verify-report.sh"),
    (r"skill-ref|meta:skill-body|Skill$|invoked_skills|skill_listing", "skill and reference text"),
    (r"watch-teammates|Monitor|notification", "watchdog and notifications"),
    (r"watch-ci", "watch-ci.sh"),
    (r"teammate-tail|bash:claude", "teammate-tail / claude logs"),
    (r"team-preflight|advisor-probe", "team-preflight / advisor probe"),
    (r"launch-teammate|close-teammate|retask", "launch / retask / close"),
    (r"review-round", "review-round.sh"),
    (r"team-init|role-skills|team-env|unit-worktree|push-branch|admiral-io", "other commodore scripts"),
    (r"state\.md|read-state|state-set", "state.md"),
    (r"prompt/brief|profile/brief-common|read-brief", "briefs, job files, profile"),
    (r"read-diff", "diffs read by the coordinator"),
    (r"read:source|read-source", "source read by the coordinator"),
    (r"persisted-tool-output", "persisted tool output re-read"),
    (r"evidence\.sh", "evidence.sh run by the coordinator"),
    (r"bash:git", "git"),
    (r"bash:gh", "gh"),
    (r"Agent$", "subagents (prompt and result)"),
    (r"SendMessage", "SendMessage"),
    (r"^out:(text|thinking)", "coordinator text and thinking"),
    (r"^attach:", "harness attachments"),
    (r"^user:|AskUserQuestion", "engineer messages and questions"),
]


def is_coordinator(path):
    with open(path, errors="replace") as f:
        for line in f:
            if '"type":"user"' in line and "command-name" in line:
                m = COORD.search(line)
                if m and not NOT_COORD.search(m.group(0)):
                    return True
    return False


def text_len(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(b.get("text", "")) if isinstance(b, dict) else len(str(b)) for b in content)
    return len(json.dumps(content)) if content else 0


def classify_bash(cmd):
    rules = [
        (r"SKILL\.md|/references/", "read-skill-ref"),
        (r"/reports/", "read-report"),
        (r"state\.md", "read-state"),
        (r"/prompts/", "read-brief"),
        (r"git( -C \S+)? (diff|show)|git( -C \S+)? log[^|;&]* -p", "read-diff"),
    ]
    m = SCRIPTS.search(cmd)
    if m:
        return "bash:" + m.group(0)
    for rx, name in rules:
        if re.search(rx, cmd):
            return "bash:" + name
    if re.search(r"\b(cat|grep|rg|sed|head|tail)\b", cmd) and re.search(r"worktrees|/src/|/tests?/", cmd):
        return "bash:read-source"
    m = re.search(r"(?:^|[;&|] *)gh (\S+ ?\S*)", cmd)
    if m:
        return "bash:gh " + m.group(1)
    if re.search(r"(?:^|[;&|] *)git ", cmd):
        return "bash:git"
    words = cmd.split()
    return "bash:" + (os.path.basename(words[0]) if words else "")


def classify_path(path):
    rules = [
        ("/reports/", "report"),
        ("state.md", "state.md"),
        ("/prompts/", "prompt/brief"),
        ("SKILL.md", "skill-ref"),
        ("/references/", "skill-ref"),
        ("profile.md", "profile/brief-common"),
        ("brief-common", "profile/brief-common"),
        ("/tool-results/", "persisted-tool-output"),
        ("worktrees", "source"),
        ("/src/", "source"),
        ("/tests/", "source"),
    ]
    return next((name for needle, name in rules if needle in path), "other")


def classify_tool(name, inp):
    if name == "Bash":
        return classify_bash(inp.get("command", "").strip())
    if name == "Read":
        return "read:" + classify_path(inp.get("file_path", ""))
    if name in ("Write", "Edit"):
        return name.lower() + ":" + classify_path(inp.get("file_path", ""))
    if name.startswith("mcp__"):
        return "mcp:" + name.split("__")[1]
    return name


def user_items(entry, tool_cat):
    content = entry.get("message", {}).get("content")
    if entry.get("isCompactSummary"):
        return [("compact-summary", text_len(content))]
    if isinstance(content, str):
        if "<task-notification" in content:
            return [("notification", len(content))]
        return [("meta:text" if entry.get("isMeta") else "user:prompt", len(content))]
    items = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_result":
            items.append(("res:" + tool_cat.get(b.get("tool_use_id"), "?"), text_len(b.get("content"))))
        elif b.get("type") == "text":
            tx = b.get("text", "")
            if "<task-notification" in tx:
                kind = "notification"
            elif tx.startswith("Base directory for this skill"):
                kind = "meta:skill-body"
            else:
                kind = "meta:text" if entry.get("isMeta") else "user:prompt"
            items.append((kind, len(tx)))
    return items


def attachment_items(entry):
    a = entry.get("attachment", {})
    kind = a.get("type")
    if kind == "prompt_snapshot":
        return []
    # Hook results reach the model only through their content field.
    n = len(str(a.get("content") or "")) if kind == "hook_success" else len(json.dumps(a))
    return [("attach:" + str(kind), n)] if n else []


def assistant_items(msg, tool_cat):
    items = []
    for b in msg.get("content") or []:
        kind = b.get("type")
        if kind == "tool_use":
            cat = classify_tool(b.get("name", "?"), b.get("input", {}))
            tool_cat[b.get("id")] = cat
            items.append(("out:" + cat, len(json.dumps(b.get("input", {})))))
        elif kind in ("text", "thinking"):
            items.append(("out:" + kind, len(b.get(kind, ""))))
    return items


def section(text, heading):
    m = re.search(r"^## " + heading + r"\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def count_units(state):
    """Count the units in a state.md: rows of the Units table (or `- uN →` bullets in the older format), plus any
    uN that owns an acceptance-trace row, since older runs stopped adding bullets."""
    try:
        text = Path(state).read_text(errors="replace")
    except OSError:
        return None
    rows = re.findall(r"^\|\s*([^|]*?)\s*\|", section(text, "Units"), re.M)
    units = {r for r in rows if r and r != "unit" and not r.startswith("---")}
    units |= set(re.findall(r"^- (u\d+) →", section(text, "Units"), re.M))
    for cell in re.findall(r"^\|[^|]*\|([^|]*)\|", section(text, "Acceptance trace"), re.M):
        units |= set(re.findall(r"\bu\d+\b", cell))
    return len(units) or None


def find_run(state_paths):
    """Return the run directory whose state.md the session named most, if it still exists."""
    for named, _ in state_paths.most_common():
        path = os.path.expanduser(named.replace("$HOME", "~"))
        if os.path.isfile(path):
            return os.path.dirname(path)
    return None


def read_calls(path):
    """Return the session's model, API calls in order as (context_tokens, items_added_before_it, usage), and run."""
    tool_cat, pending, calls, seen = {}, [], [], set()
    state_paths = collections.Counter()
    model = None
    with open(path, errors="replace") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("isSidechain"):
                continue
            kind = e.get("type")
            if kind == "assistant":
                msg = e.get("message", {})
                usage = msg.get("usage")
                if usage and msg.get("id") not in seen:
                    seen.add(msg.get("id"))
                    model = msg.get("model", model)
                    ctx = sum(
                        usage.get(k, 0)
                        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
                    )
                    calls.append((ctx, pending, usage))
                    pending = []
                pending += assistant_items(msg, tool_cat)
                for b in msg.get("content") or []:
                    if b.get("type") == "tool_use":
                        state_paths.update(STATE_PATH.findall(json.dumps(b.get("input", {}))))
            elif kind == "user":
                pending += user_items(e, tool_cat)
            elif kind == "attachment":
                pending += attachment_items(e)
    return model, calls, find_run(state_paths)


def attribute(calls):
    """Split each call's context growth across its items; return (added, carry, compactions)."""
    per_call, segments, seg, prev = [], [], [], None
    for i, (ctx, items, _) in enumerate(calls):
        if prev is None:
            adds = [("initial", ctx)]
        elif ctx < prev - COMPACTION_DROP:
            segments.append(seg)
            seg = []
            adds = [("post-compact base", ctx)]
        else:
            growth = max(ctx - prev, 0)
            chars = sum(n for _, n in items)
            adds = [(c, growth * n / chars) for c, n in items] if chars else [("unattributed", growth)]
        seg.append(i)
        per_call.append(adds)
        prev = ctx
    segments.append(seg)
    added, carry = collections.Counter(), collections.Counter()
    for s in segments:
        for j, i in enumerate(s):
            for cat, tok in per_call[i]:
                added[cat] += tok
                carry[cat] += tok * (len(s) - j)
    return added, carry, len(segments) - 1


def simulate_handoff(calls, threshold):
    ctxs = [c for c, _, _ in calls]
    base = ctxs[0] + RESUME_TOKENS
    total, offset, prev, handoffs = 0, 0, ctxs[0], 0
    for ctx in ctxs:
        if ctx < prev - COMPACTION_DROP:
            offset = 0
        sim = ctx - offset
        if sim > threshold:
            offset, sim = ctx - base, base
            handoffs += 1
        total += sim
        prev = ctx
    return total, handoffs


def group(cat):
    return next((name for rx, name in GROUPS if re.search(rx, cat)), "other: " + re.sub(r"^(res|out):", "", cat))


def find_transcripts(paths, days):
    cutoff = time.time() - days * 86400
    roots = paths or sorted(glob.glob(os.path.expanduser("~/.claude*/projects")))
    files = []
    for root in roots:
        candidates = [root] if root.endswith(".jsonl") else glob.glob(os.path.join(root, "*", "*.jsonl"))
        files += [
            p
            for p in candidates
            if os.path.getmtime(p) >= cutoff and os.path.getsize(p) >= MIN_TRANSCRIPT_BYTES and is_coordinator(p)
        ]
    return files


def report(sessions, args):
    carry, added = collections.Counter(), collections.Counter()
    for s in sessions:
        for k, v in s["carry"].items():
            carry[k if args.raw else group(k)] += v
        for k, v in s["added"].items():
            added[k if args.raw else group(k)] += v
    calls = sum(s["calls"] for s in sessions)
    total = sum(carry.values())
    runs = {s["run"]: s["units"] for s in sessions}
    units = args.units or (sum(runs.values()) if None not in runs and None not in runs.values() else None)
    out = {
        "sessions": len(sessions),
        "calls": calls,
        "cache_read": sum(s["cache_read"] for s in sessions),
        "mean_context_per_call": round(total / calls) if calls else 0,
        "never_compacted": sum(1 for s in sessions if s["compactions"] == 0),
        "mean_initial_context": round(sum(s["added"].get("initial", 0) for s in sessions) / len(sessions)),
        "units": units,
        "calls_per_unit": round(calls / units, 1) if units else None,
        "breakdown": [
            {"source": k, "carry": round(v), "share": round(v / total, 4), "added": round(added[k])}
            for k, v in carry.most_common()
        ],
    }
    if args.simulate_handoff:
        out["handoff"] = []
        for t in HANDOFF_THRESHOLDS:
            sims = [simulate_handoff(s["series"], t) for s in sessions]
            sim_total = sum(x for x, _ in sims)
            out["handoff"].append(
                {"threshold": t, "saving": round(1 - sim_total / total, 4), "handoffs": sum(h for _, h in sims)}
            )
    if args.sessions:
        keys = ("path", "model", "calls", "peak", "compactions", "cache_read", "run", "units")
        out["per_session"] = [{k: s[k] for k in keys} for s in sessions]
    return out


def print_text(out):
    print(
        f"{out['sessions']} coordinator sessions, {out['calls']} API calls, {out['cache_read'] / 1e6:.0f}M cache reads"
    )
    if out["units"]:
        print(f"{out['units']} units, {out['calls_per_unit']:.1f} calls per unit")
    else:
        print("units unknown: pass --units N for calls per unit")
    print(
        f"mean context per call {out['mean_context_per_call'] / 1e3:.0f}k, mean initial context "
        f"{out['mean_initial_context'] / 1e3:.0f}k, {out['never_compacted']} never compacted\n"
    )
    print(f"{'carry':>9} {'share':>6} {'added':>9}  source")
    for row in out["breakdown"]:
        if row["share"] < MIN_SHARE_SHOWN:
            break
        print(f"{row['carry'] / 1e6:8.1f}M {row['share']:6.1%} {row['added'] / 1e3:8.1f}k  {row['source']}")
    for h in out.get("handoff", []):
        print(
            f"handoff above {h['threshold'] // 1000}k: {h['saving']:.0%} fewer input tokens, {h['handoffs']} handoffs"
        )
    for s in out.get("per_session", []):
        units = f"{s['units']} units" if s["units"] is not None else "? units"
        peak = f"peak {s['peak'] / 1e3:4.0f}k"
        print(f"{s['calls']:5} calls  {peak}  {s['compactions']} compactions  {units:>8}  {s['path']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", help="transcripts or projects directories (default: ~/.claude*/projects)")
    ap.add_argument("--days", type=int, default=30, help="only transcripts modified in the last N days")
    ap.add_argument("--min-calls", type=int, default=50, help="skip sessions with fewer API calls")
    ap.add_argument("--units", type=int, help="units in the run(s), for calls per unit (default: from state.md)")
    ap.add_argument("--raw", action="store_true", help="show raw categories instead of groups")
    ap.add_argument("--sessions", action="store_true", help="list the sessions analysed")
    ap.add_argument("--simulate-handoff", action="store_true", help="estimate savings from fresh-coordinator handoff")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args()

    sessions = []
    for path in find_transcripts(args.paths, args.days):
        model, calls, run = read_calls(path)
        if len(calls) < args.min_calls:
            continue
        added, carry, compactions = attribute(calls)
        sessions.append(
            {
                "path": str(path).replace(str(Path.home()), "~"),
                "model": model,
                "calls": len(calls),
                "peak": max(c for c, _, _ in calls),
                "compactions": compactions,
                "cache_read": sum(u.get("cache_read_input_tokens", 0) for _, _, u in calls),
                "added": added,
                "carry": carry,
                "series": calls,
                "run": run and run.replace(str(Path.home()), "~"),
                "units": run and count_units(os.path.join(run, "state.md")),
            }
        )
    if not sessions:
        print("no coordinator sessions found", file=sys.stderr)
        return 1
    out = report(sessions, args)
    if args.json:
        json.dump(out, sys.stdout, indent=1)
        print()
    else:
        print_text(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
