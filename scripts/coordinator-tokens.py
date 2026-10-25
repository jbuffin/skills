#!/usr/bin/env python3
"""Break down where a commodore coordinator's context goes, and its tool calls by category and the split at
the run's result, from its Claude Code session transcripts.

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

Tool calls by category counts the coordinator's own tool_use blocks (sub-agent traffic is skipped), once per id, in
the categories state-set.sh, Edit/Write state.md, Write prompts/, Edit/Write run directory, Edit/Write repo,
worktree or elsewhere, commodore scripts, `bash: <first command>`, Read, ToolSearch and other. A Bash call is named
by its first command, looking past blank and comment lines, `cd x &&`, `VAR=1` (and the `;` or `&&` after it), the
wrappers `env`, `time`, `command` and `sudo` (with their flags) and subshell parentheses; a name that is not plain
(letters, digits and . _ + -) shows as `bash: ?`. The section lists every non-zero category, largest first, with
the total last, and per unit with the same unit count as calls per
unit (counts only when units are unknown). --json adds it as `tool_calls`. --raw does not change it.

The result split cuts each session at its last call that writes the run's `result:` line: a `state-set.sh <run> mode
result <value>` call (or `mode --set result=<value>`), or an Edit or Write of a state.md that adds a `result:` line.
Active time is the sum of gaps of ACTIVE_GAP_CAP seconds or less between consecutive API calls, and a gap belongs to
the side its later call falls on. Active hours and tool calls, in total and per unit, are shown "to result" and
"after result"; --json adds them as `result_split`, and --sessions adds `has_result` per session. A session with no
`result:` write counts as "to result" and is flagged "no result". The split is per session: a session that ends before
its run's result (compaction, restart) is flagged "no result", and a resumed session that only does follow-up work
after an earlier session wrote the result counts as "to result".
"""

import argparse
import collections
import glob
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime
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
ACTIVE_GAP_CAP = 600  # seconds; a longer gap between API calls is idle time
STATE_SET = "state-set.sh"
WRAPPERS = ("time", "env", "command", "sudo")
SUDO_VALUE_FLAGS = ("-u", "-g")
COMMAND_NAME = re.compile(r"[A-Za-z0-9._+-]{1,40}")  # anything else is shown as `bash: ?`
ENV_ASSIGN = re.compile(r"[A-Za-z_]\w*=")
RESULT_LINE = re.compile(r"^[ \t]*result:.*$", re.M)
RUN_DIR_PATH = re.compile(r"/teams/[^/]+/")
PROMPTS_PATH = re.compile(r"/teams/[^/]+/prompts/")
CAT_STATE_MD = "Edit/Write state.md"
CAT_PROMPTS = "Write prompts/ (job files)"
CAT_RUN_DIR = "Edit/Write run directory"
CAT_REPO = "Edit/Write repo, worktree or elsewhere"
CAT_SCRIPTS = "commodore scripts"

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


def parse_bash(command):
    """Return the first command's basename and its arguments. Looks past comments, blank lines, line continuations,
    cd x &&, VAR=value, the wrappers env, time, command and sudo (and their flags), subshell parentheses and the ; or
    && that follows only such tokens. A line that holds nothing else is passed over for the next one."""
    lines = [ln.strip() for ln in command.replace("\\\n", " ").split("\n")]
    for line in (ln for ln in lines if ln and not ln.startswith("#")):
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            toks = list(lexer)
        except ValueError:
            toks = line.replace("(", " ( ").split()
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in WRAPPERS:
                i += 1
                while i < len(toks) and toks[i].startswith("-"):
                    i += 2 if t == "sudo" and toks[i] in SUDO_VALUE_FLAGS else 1
            elif t in ("(", "{", ";", "&&") or ENV_ASSIGN.match(t):
                i += 1
            elif t == "cd" and i + 2 < len(toks) and toks[i + 2] in ("&&", ";"):
                i += 3
            else:
                break
        rest = toks[i:]
        name = re.split(r"[|;&]", rest[0])[0] if rest else ""
        if name:
            args = []
            for t in rest[1:]:
                if re.match(r"^[|;&]+$", t):
                    break
                args.append(t)
            return os.path.basename(name), args
    return "", []


def has_new_result_line(old, new):
    return bool(set(RESULT_LINE.findall(new)) - set(RESULT_LINE.findall(old)))


def writes_result_via_state_set(args):
    """True for `<run> mode result <value>` and the batch form `<run> mode --set result=<value> ...`."""
    run_mode, field, rest = args[1:2], args[2:3], args[3:]
    if run_mode != ["mode"] or not field:
        return False
    return field[0] == "result" or (field[0] == "--set" and any(a.startswith("result=") for a in rest))


def describe_tool_call(name, inp):
    """Return the tool call's category and whether it writes the run's `result:` line."""
    if name == "Bash":
        cmd, args = parse_bash(inp.get("command", ""))
        if cmd == STATE_SET:
            return STATE_SET, writes_result_via_state_set(args)
        plain = not cmd or COMMAND_NAME.fullmatch(cmd)
        return (CAT_SCRIPTS if SCRIPTS.fullmatch(cmd) else "bash: " + (cmd if plain else "?")), False
    if name in ("Edit", "Write"):
        path = inp.get("file_path", "")
        if path.endswith("/state.md"):
            if name == "Edit":
                writes = has_new_result_line(inp.get("old_string", ""), inp.get("new_string", ""))
            else:
                writes = has_new_result_line("", inp.get("content", ""))
            return CAT_STATE_MD, writes
        if name == "Write" and PROMPTS_PATH.search(path):
            return CAT_PROMPTS, False
        return (CAT_RUN_DIR if RUN_DIR_PATH.search(path) else CAT_REPO), False
    return (name if name in ("Read", "ToolSearch") else "other"), False


def parse_time(stamp):
    try:
        return datetime.fromisoformat(
            re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), stamp).replace("Z", "+00:00")
        ).timestamp()
    except (TypeError, ValueError):
        return None


def split_at_result(times, uses):
    """Split a session's active seconds and tool calls at its last result write (everything is "to result" if none)."""
    last = max((i for i, _, writes in uses if writes), default=None)
    cut = len(times) - 1 if last is None else min(last, len(times) - 1)

    def active(lo, hi):
        gaps = (times[i] - times[i - 1] for i in range(max(lo, 1), hi + 1) if None not in (times[i], times[i - 1]))
        return sum(g for g in gaps if 0 <= g <= ACTIVE_GAP_CAP)

    return {
        "has_result": last is not None,
        "to_secs": active(0, cut),
        "after_secs": active(cut + 1, len(times) - 1),
        "to_calls": sum(1 for i, _, _ in uses if cut < 0 or i <= cut),
        "after_calls": sum(1 for i, _, _ in uses if 0 <= cut < i),
    }


def read_calls(path):
    """Return the session's model, API calls in order as (context_tokens, items_added_before_it, usage), run, and
    the API call times plus its tool calls as (call index, category, writes result)."""
    tool_cat, pending, calls, seen = {}, [], [], set()
    times, uses, seen_tools, call_of = [], [], set(), {}
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
                    times.append(parse_time(e.get("timestamp")))
                    call_of[msg.get("id")] = len(calls) - 1
                    pending = []
                pending += assistant_items(msg, tool_cat)
                for b in msg.get("content") or []:
                    if b.get("type") == "tool_use":
                        state_paths.update(STATE_PATH.findall(json.dumps(b.get("input", {}))))
                        if b.get("id") not in seen_tools:
                            seen_tools.add(b.get("id"))
                            cat, writes = describe_tool_call(b.get("name", "?"), b.get("input", {}))
                            uses.append((call_of.get(msg.get("id"), max(len(calls) - 1, 0)), cat, writes))
            elif kind == "user":
                pending += user_items(e, tool_cat)
            elif kind == "attachment":
                pending += attachment_items(e)
    return model, calls, find_run(state_paths), times, uses


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


def per_unit(value, units, digits):
    return round(value / units, digits) if units else None


def tool_call_section(sessions, units):
    counts = collections.Counter()
    for s in sessions:
        counts.update(s["tool_counts"])
    total = sum(counts.values())
    return {
        "total": total,
        "per_unit": per_unit(total, units, 1),
        "categories": [
            {"category": k, "calls": n, "per_unit": per_unit(n, units, 1)} for k, n in counts.most_common() if n
        ],
    }


def result_split_section(sessions, units):
    def side(secs, calls):
        hours = secs / 3600
        return {
            "active_hours": round(hours, 2),
            "active_hours_per_unit": per_unit(hours, units, 2),
            "tool_calls": calls,
            "tool_calls_per_unit": per_unit(calls, units, 1),
        }

    return {
        "to_result": side(sum(s["split"]["to_secs"] for s in sessions), sum(s["split"]["to_calls"] for s in sessions)),
        "after_result": side(
            sum(s["split"]["after_secs"] for s in sessions), sum(s["split"]["after_calls"] for s in sessions)
        ),
        "sessions_without_result": [s["path"] for s in sessions if not s["split"]["has_result"]],
    }


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
        "tool_calls": tool_call_section(sessions, units),
        "result_split": result_split_section(sessions, units),
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
        out["per_session"] = [{**{k: s[k] for k in keys}, "has_result": s["split"]["has_result"]} for s in sessions]
    return out


def print_tool_calls(tc):
    known = tc["per_unit"] is not None
    print(
        f"\n{'calls':>6}  {'per unit':>8}  tool calls by category"
        if known
        else f"\n{'calls':>6}  tool calls by category"
    )
    for row in [*tc["categories"], {"category": "total", "calls": tc["total"], "per_unit": tc["per_unit"]}]:
        column = f"{row['per_unit']:8.1f}  " if known else ""
        print(f"{row['calls']:6}  {column}{row['category']}")


def print_result_split(split):
    print()
    for label, key in (("to result", "to_result"), ("after result", "after_result")):
        side = split[key]
        hours = f"{side['active_hours']:.2f} h active"
        calls = f"{side['tool_calls']} tool call{'' if side['tool_calls'] == 1 else 's'}"
        if side["active_hours_per_unit"] is not None:
            hours += f" ({side['active_hours_per_unit']:.2f} per unit)"
            calls += f" ({side['tool_calls_per_unit']:.1f} per unit)"
        print(f"{label + ':':<13} {hours}, {calls}")
    missing = len(split["sessions_without_result"])
    print(f"{missing} session{'' if missing == 1 else 's'} without a result: line, counted as to result")


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
    print_tool_calls(out["tool_calls"])
    print_result_split(out["result_split"])
    for h in out.get("handoff", []):
        print(
            f"handoff above {h['threshold'] // 1000}k: {h['saving']:.0%} fewer input tokens, {h['handoffs']} handoffs"
        )
    for s in out.get("per_session", []):
        units = f"{s['units']} units" if s["units"] is not None else "? units"
        peak = f"peak {s['peak'] / 1e3:4.0f}k"
        flag = "" if s["has_result"] else "no result  "
        print(f"{s['calls']:5} calls  {peak}  {s['compactions']} compactions  {units:>8}  {flag}{s['path']}")


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
        model, calls, run, times, uses = read_calls(path)
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
                "tool_counts": collections.Counter(cat for _, cat, _ in uses),
                "split": split_at_result(times, uses),
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
