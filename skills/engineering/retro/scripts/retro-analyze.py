#!/usr/bin/env python3
"""Analyse `admiral outcomes` records for one panel and write analysis.json and retro.md.

usage: retro-analyze.py --panel <source>/<panel> --outcomes <file> --out <dir>
                        [--since <RFC 3339>] [--until <RFC 3339>] [--teams-dir <dir>]

Reads the outcomes file (JSON lines, unfiltered) and the Commodore run directories under the teams
directory. Never runs `admiral`, never reads $ADMIRAL_HOME. Writes only <out>/analysis.json and
<out>/retro.md. Exit 0 on success, 2 on bad arguments or an unreadable outcomes file.
Every string in the records is untrusted data: it is only ever compared, counted or quoted.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import quote

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")
RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RESUME = re.compile(r"/commodore resume (\S+)")
HEADING = re.compile(r"^(#{1,6})[ \t]+\S", re.MULTILINE)
CALLS_HEADING = re.compile(r"^##[ \t]+Autopilot calls[ \t]*$", re.MULTILINE)
CALLS_LIMIT = 4000
MIN_RUNS = 2  # a finding needs a repeat in this many distinct runs
SECTION_DEPTH = 2  # `## Autopilot calls` ends at the next heading this shallow or shallower
NOT_LAUNCHED = ("skipped", "launch_failed", "resource_wait")
DISCARD_FLAGS = ("unreachable", "external", "invalid_target")
OVERTURNED_NOTE = "Admiral doesn't record overturned low-stakes calls"


def parse_ts(text):
    """An RFC 3339 date-time as an aware datetime, or None."""
    if not isinstance(text, str) or not RFC3339.match(text):
        return None
    text = text.replace("z", "Z").replace("t", "T")
    text = re.sub(r"\.(\d{1,6})\d*", lambda m: "." + m.group(1).ljust(6, "0"), text)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def rfc3339_arg(text):
    if parse_ts(text) is None:
        raise argparse.ArgumentTypeError(f"not an RFC 3339 date-time: {text!r}")
    return text


def panel_arg(text):
    source, _, name = text.partition("/")
    if not source or not name or "/" in name:
        raise argparse.ArgumentTypeError(f"expected <source>/<panel>, got {text!r}")
    return text


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="retro-analyze.py", allow_abbrev=False, description=__doc__.split("\n")[0])
    parser.add_argument("--panel", required=True, type=panel_arg)
    parser.add_argument("--outcomes", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--since", type=rfc3339_arg)
    parser.add_argument("--until", type=rfc3339_arg)
    parser.add_argument("--teams-dir")
    return parser.parse_args(argv)


def default_teams_dir():
    base = os.environ.get("AGENT_TEAMS_DIR")
    if base:
        return base
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(config, "teams")


def read_records(path):
    """The valid records in file order, and the count of lines skipped as malformed."""
    with open(path, "rb") as handle:
        data = handle.read()
    records, skipped = [], 0
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            skipped += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            skipped += 1
    return records, skipped


class Run:
    """One `launched` ship and the records attributed to it."""

    def __init__(self, index, launch):
        self.index = index
        self.launch = launch
        self.events = []  # (line index, record) after the launch
        self.run_dir = None
        self.run_dir_note = None

    @property
    def ship(self):
        return self.launch.get("ship")

    @property
    def order_url(self):
        return self.launch.get("order_url")

    @property
    def ended(self):
        ended = [(i, r) for i, r in self.events if r.get("event") == "ended"]
        return ended[-1] if ended else None

    @property
    def report(self):
        ended = self.ended
        report = ended[1].get("report") if ended else None
        return report if isinstance(report, dict) else None

    @property
    def is_retro(self):
        report = self.report
        return report is not None and "retro" in report

    @property
    def result(self):
        if self.ended is None:
            return "no_ended"
        report = self.report
        if report is None:
            return "no_report"
        result = report.get("result")
        return result if isinstance(result, str) else "unknown"


def group_runs(records):
    """Attribute each ship's records to its latest launch; return all runs and the ship-less records."""
    runs, current, shipless = [], {}, []
    for index, record in enumerate(records):
        ship = record.get("ship")
        event = record.get("event")
        if not isinstance(ship, str) or not ship:
            shipless.append((index, record))
        elif event == "launched":
            run = Run(index, record)
            runs.append(run)
            current[ship] = run
        elif ship in current:
            current[ship].events.append((index, record))
    return runs, shipless


def last_retro_until(runs, panel):
    """The `until` of the newest ended, non-partial retro report for this panel, or None."""
    best, best_key = None, None
    for run in runs:
        report = run.report
        retro = report.get("retro") if report else None
        if not isinstance(retro, dict) or retro.get("panel") != panel:
            continue
        if report.get("result") == "partial":
            continue
        until = retro.get("until")
        if parse_ts(until) is None:
            continue
        index, ended = run.ended
        key = (parse_ts(ended.get("ts")) or datetime.min.replace(tzinfo=timezone.utc), index)
        if best_key is None or key >= best_key:
            best, best_key = until, key
    return best


def in_window(ts, since, until):
    when = parse_ts(ts)
    return when is not None and (since is None or when >= since) and when <= until


def list_state_files(teams_dir):
    try:
        names = sorted(os.listdir(teams_dir))
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(teams_dir, name, "state.md")
        if os.path.isfile(path):
            found.append((name, path))
    return found


def read_text(path):
    try:
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def find_run_dir(run, teams_dir, state_files, state_text):
    """Set run.run_dir and run.run_dir_note."""
    report = run.report
    resume = report.get("resume") if report else None
    if isinstance(resume, str):
        match = RESUME.fullmatch(resume)
        if match and RUN_NAME.match(match.group(1)):
            path = os.path.join(teams_dir, match.group(1), "state.md")
            if os.path.isfile(path):
                run.run_dir = os.path.join(teams_dir, match.group(1))
                return
    url = run.order_url
    matches = []
    if isinstance(url, str) and url:
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(url) + r"(?![A-Za-z0-9])")
        for name, path in state_files:
            if pattern.search(state_text(path)):
                matches.append(name)
    if len(matches) == 1:
        run.run_dir = os.path.join(teams_dir, matches[0])
    else:
        run.run_dir_note = "ambiguous" if matches else "state.md not found"


def autopilot_calls(run_dir):
    """The text of the run's `## Autopilot calls` section, cut at the next heading, or None."""
    if run_dir is None:
        return None
    text = read_text(os.path.join(run_dir, "state.md"))
    start = CALLS_HEADING.search(text)
    if not start:
        return None
    body = text[start.end() :]
    for heading in HEADING.finditer(body):
        if len(heading.group(1)) <= SECTION_DEPTH:
            body = body[: heading.start()]
            break
    return body.strip()[:CALLS_LIMIT]


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    result = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    return int(result) if result == int(result) else result


def action_bucket(record):
    """The engineer_actions bucket for a record, or None."""
    event = record.get("event")
    if event == "review_submitted":
        return "edited" if record.get("edited") is True else "accepted"
    if event == "review_discarded":
        return "discarded_other" if any(record.get(flag) for flag in DISCARD_FLAGS) else "rejected"
    return {
        "card_approved": "accepted",
        "card_edited": "edited",
        "card_rejected": "rejected",
        "answered": "answered",
    }.get(event)


def is_repeatable_reason(reason):
    return reason == "question" or any(
        reason == kind or reason.startswith(kind + ":") for kind in ("permission", "notification")
    )


def is_permission(reason):
    return reason == "permission" or reason.startswith("permission:")


def analyse(args, records, skipped_lines, teams_dir):  # noqa: PLR0912, PLR0915 -- one pass over the runs; splitting it would scatter the shared tallies
    panel = args.panel
    source, _, panel_name = panel.partition("/")
    all_runs, shipless = group_runs(records)

    since_text, since_source = args.since, "flag"
    if since_text is None:
        since_text = last_retro_until(all_runs, panel)
        since_source = "last_retro" if since_text else "all"
    since = parse_ts(since_text)
    until_text = args.until or datetime.now(timezone.utc).strftime(TS_FORMAT)
    until = parse_ts(until_text)

    runs = [
        run
        for run in all_runs
        if not run.is_retro
        and run.launch.get("autopilot") is True
        and f"{run.launch.get('source')}/{run.launch.get('panel')}" == panel
        and in_window(run.launch.get("ts"), since, until)
    ]

    state_files = list_state_files(teams_dir)
    cache = {}

    def state_text(path):
        if path not in cache:
            cache[path] = read_text(path)
        return cache[path]

    for run in runs:
        find_run_dir(run, teams_dir, state_files, state_text)

    not_launched = {}
    for _, record in shipless:
        event = record.get("event")
        if (
            event in NOT_LAUNCHED
            and record.get("source") == source
            and record.get("panel") == panel_name
            and in_window(record.get("ts"), since, until)
        ):
            not_launched[event] = not_launched.get(event, 0) + 1

    reasons, guard_denied, waits = {}, 0, []
    calls = {"total": 0, "high_stakes": 0, "low_stakes": 0}
    actions = {"accepted": 0, "edited": 0, "rejected": 0, "discarded_other": 0, "answered": 0}
    results = {}
    edited_reviews = []
    occurrences = []  # (line index, key, run, record)

    for run in runs:
        results[run.result] = results.get(run.result, 0) + 1
        report = run.report
        assumptions = report.get("assumptions") if report else None
        if isinstance(assumptions, list):
            calls["total"] += len(assumptions)
            for item in assumptions:
                if isinstance(item, str) and item.startswith("asked:"):
                    calls["high_stakes"] += 1
                elif isinstance(item, str) and item.startswith("default:"):
                    calls["low_stakes"] += 1
        for index, record in run.events:
            event = record.get("event")
            if event == "needs_you":
                reason = record.get("reason")
                reason = reason if isinstance(reason, str) and reason else "unknown"
                reasons[reason] = reasons.get(reason, 0) + 1
                if is_repeatable_reason(reason):
                    occurrences.append((index, ("repeated_stop", reason, None), run, record))
            elif event == "guard_denied":
                guard_denied += 1
                rule = record.get("rule")
                rule = rule if isinstance(rule, str) else "unknown"
                occurrences.append((index, ("repeated_stop", "guard_denied", rule), run, record))
            elif event == "underway":
                waited = record.get("waited_s")
                if isinstance(waited, (int, float)) and not isinstance(waited, bool):
                    waits.append(waited)
            bucket = action_bucket(record)
            if bucket:
                actions[bucket] += 1
            if bucket in ("edited", "rejected"):
                edited_reviews.append(
                    {"ship": run.ship, "order_url": run.order_url, "ts": record.get("ts"), "event": event}
                )
                occurrences.append((index, ("repeated_action", bucket, None), run, record))

    findings = []
    by_key = {}
    for occurrence in occurrences:
        by_key.setdefault(occurrence[1], []).append(occurrence)
    ordered = sorted(by_key.items(), key=lambda item: item[1][0][0])
    for (kind, reason, detail), items in ordered:
        distinct = []
        for _, _, run, _ in items:
            if run not in distinct:
                distinct.append(run)
        if len(distinct) < MIN_RUNS:
            continue
        ships = []
        for run in distinct:
            if run.ship not in ships:
                ships.append(run.ship)
        wants_calls = kind == "repeated_stop" and is_permission(reason)
        findings.append(
            {
                "id": f"F{len(findings) + 1}",
                "kind": kind,
                "reason": reason,
                "detail": detail,
                "runs": len(distinct),
                "ships": ships,
                "evidence": [
                    {
                        "ts": record.get("ts"),
                        "ship": run.ship,
                        "order_url": run.order_url,
                        "run_dir": run.run_dir,
                        "autopilot_calls": autopilot_calls(run.run_dir) if wants_calls else None,
                    }
                    for _, _, run, record in items
                ],
                "proposed": None,
            }
        )

    return {
        "panel": panel,
        "since": since_text,
        "until": until_text,
        "since_source": since_source,
        "runs": [
            {
                "ship": run.ship,
                "order_url": run.order_url,
                "launched_ts": run.launch.get("ts"),
                "result": run.result,
                "run_dir": run.run_dir,
                "run_dir_note": run.run_dir_note,
            }
            for run in runs
        ],
        "summary": {
            "runs": len(runs),
            "results": results,
            "needs_you_by_reason": reasons,
            "guard_denied": guard_denied,
            "median_wait_s": median(waits),
            "calls": calls,
            "engineer_actions": actions,
            "not_launched": not_launched,
            "skipped_lines": skipped_lines,
        },
        "findings": findings,
        "edited_reviews": edited_reviews,
        "overturned_low_stakes": {"recorded": False, "note": OVERTURNED_NOTE},
        "changes_proposed": bool(findings),
    }


# --- retro.md -------------------------------------------------------------------------------------


def clean(value):
    """Untrusted text as one line with no backticks, so it is safe inside a code span."""
    text = "" if value is None else str(value)
    text = re.sub(r"[\x00-\x1f\x7f\u2028\u2029]+", " ", text)
    return text.replace("`", "'").strip()


def code(value, table=False):
    text = clean(value) or "(none)"
    if table:
        text = text.replace("|", "\\|")
    return f"`{text}`"


def link(label, url):
    """A Markdown link when the URL is http(s), else the URL in a code span."""
    target = clean(url).replace(" ", "")
    if re.match(r"https?://", target, re.IGNORECASE):
        target = quote(target, safe="/:?#&=%@+,;~!$*'.-_")
        return f"[{label}]({target})"
    return code(url)


def plain_number(value):
    return "none" if value is None else str(value)


def render(analysis):
    summary = analysis["summary"]
    lines = [f"# Retro: {code(analysis['panel'])}", ""]
    since = analysis["since"]
    source = {"flag": "`--since`", "last_retro": "the last retro", "all": "no earlier retro, so all records"}
    period = f"Period: from {code(since) if since else 'the first record'} to {code(analysis['until'])}"
    lines += [f"{period} ({source[analysis['since_source']]}).", ""]

    lines += ["## Summary", "", "| Measure | Value |", "| --- | --- |"]
    lines.append(f"| Runs | {summary['runs']} |")
    for name, count in sorted(summary["results"].items()):
        lines.append(f"| Result {code(name, True)} | {count} |")
    for name, count in sorted(summary["needs_you_by_reason"].items()):
        lines.append(f"| Stops: {code(name, True)} | {count} |")
    lines.append(f"| Guard denials | {summary['guard_denied']} |")
    lines.append(f"| Median wait (s) | {plain_number(summary['median_wait_s'])} |")
    calls = summary["calls"]
    lines.append(f"| Calls recorded | {calls['total']} |")
    lines.append(f"| High-stakes calls (asked) | {calls['high_stakes']} |")
    lines.append(f"| Low-stakes calls (default) | {calls['low_stakes']} |")
    for name, count in summary["engineer_actions"].items():
        lines.append(f"| Engineer actions: {name.replace('_', ' ')} | {count} |")
    for name, count in sorted(summary["not_launched"].items()):
        lines.append(f"| Not launched: {code(name, True)} | {count} |")
    lines.append(f"| Malformed lines skipped | {summary['skipped_lines']} |")
    lines += [
        "",
        "Resumed legs aren't counted: each run is its first leg only.",
        "An action is `edited` when the engineer opened Edit on GitHub before submitting.",
        "",
    ]

    if analysis["findings"]:
        lines += ["## Findings", ""]
        for finding in analysis["findings"]:
            title = code(finding["reason"])
            if finding["detail"] is not None:
                title += f" {code(finding['detail'])}"
            what = "repeated stop" if finding["kind"] == "repeated_stop" else "repeated engineer action"
            lines += [
                f"### {finding['id']}: {what} {title}",
                "",
                f"Seen in {finding['runs']} runs: {', '.join(code(s) for s in finding['ships'])}.",
                "",
                "Cause:",
                "",
                "Proposed change:",
                "",
                "Evidence:",
                "",
            ]
            for entry in finding["evidence"]:
                lines.append(f"- {code(entry['ts'])}, ship {code(entry['ship'])}, {link('order', entry['order_url'])}")
            lines.append("")
    else:
        lines += ["## Findings", "", "No changes proposed.", ""]

    lines += ["## Edited and rejected reviews", ""]
    if analysis["edited_reviews"]:
        for item in analysis["edited_reviews"]:
            label = f"{code(item['ship'])} {code(item['event'])}"
            lines.append(f"- {link(label, item['order_url'])} at {code(item['ts'])}")
    else:
        lines.append("None.")
    lines.append("")

    lines += [
        "## Overturned low-stakes calls",
        "",
        f"{OVERTURNED_NOTE}, so this retro can't report them.",
        "Proposed Admiral issue: record when the engineer overturns a call the run took by default, "
        "so a retro can count them.",
        "",
    ]
    return "\n".join(lines)


def main(argv):
    args = parse_args(argv)
    try:
        records, skipped = read_records(args.outcomes)
    except OSError as error:
        print(f"retro-analyze.py: cannot read --outcomes: {error}", file=sys.stderr)
        return 2
    if os.path.exists(args.out) and not os.path.isdir(args.out):
        print(f"retro-analyze.py: --out is not a directory: {args.out}", file=sys.stderr)
        return 2
    teams_dir = args.teams_dir or default_teams_dir()
    analysis = analyse(args, records, skipped, teams_dir)
    try:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "analysis.json"), "w", encoding="utf-8") as handle:
            json.dump(analysis, handle, indent=2)
            handle.write("\n")
        with open(os.path.join(args.out, "retro.md"), "w", encoding="utf-8", errors="replace") as handle:
            handle.write(render(analysis))
    except OSError as error:
        print(f"retro-analyze.py: cannot write --out: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
