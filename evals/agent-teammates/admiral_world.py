"""Shared fixture for the agent-teammates driver tests: a temp world with a fake `admiral`, `claude`, `tmux` and
`cmux` first on PATH, a team dir with its own team.env, and an environment built from scratch.

The real admiral, claude and tmux live outside the PATH built here (/usr/bin:/bin:/usr/sbin:/sbin), and HOME is a
temp dir, so no test can reach them. Each fake appends one JSON line per call to its log and takes its canned answers
from files in `ctl/`.
"""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = REPO / "skills" / "engineering" / "agent-teammates" / "scripts"
ADMIRAL_DRIVER = SCRIPTS / "drivers" / "admiral"
CLAUDE_DRIVER = SCRIPTS / "drivers" / "claude"

SHIP = "heather-hull"

# `admiral crew` with no arguments, as the build at 992f678 prints it (stderr, exit 2).
USAGE_NEW = (
    (
        "admiral: usage: admiral crew launch --name <name> --dir <dir> [--harness <h>] [--ship <ship>]"
        " [--role <role>] [--arg <value>]... -- <prompt>\n"
    )
    + """       admiral crew send <name> [text] [--ship <ship>]   (text from stdin without an argument)
       admiral crew list [--json] [--ship <ship>]
       admiral crew close <name> [--ship <ship>]
"""
)
# v0.3.0 has no --arg.
USAGE_OLD = USAGE_NEW.replace(" [--arg <value>]...", "")

FAKE_ADMIRAL = """#!{python}
import json, os, sys
ctl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ctl")
def read(name, default=""):
    try:
        return open(os.path.join(ctl, name)).read()
    except OSError:
        return default
args = sys.argv[1:]
stdin = ""
if args[:2] == ["crew", "send"]:
    stdin = sys.stdin.read()
with open(os.path.join(ctl, "admiral.log"), "a") as log:
    log.write(json.dumps({{"argv": args, "stdin": stdin}}) + "\\n")
if args == ["--version"]:
    print("admiral 0.4.0-dev (992f678)")
    sys.exit(0)
if args == ["crew"]:
    sys.stderr.write(read("usage.txt"))
    sys.exit(2)
if args[:2] == ["crew", "list"]:
    sys.stdout.write(read("list.json", "[]"))
    sys.stderr.write(read("list.msg"))
    sys.exit(int(read("list.rc", "0") or 0))
if args[:2] in (["crew", "launch"], ["crew", "send"], ["crew", "close"]):
    sub = args[1]
    sys.stderr.write(read(sub + ".msg"))
    sys.exit(int(read(sub + ".rc", "0") or 0))
sys.stderr.write("fake admiral: unexpected call\\n")
sys.exit(64)
"""

FAKE_CLAUDE = """#!{python}
import json, os, sys
ctl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ctl")
args = sys.argv[1:]
with open(os.path.join(ctl, "claude.log"), "a") as log:
    log.write(json.dumps({{"argv": args, "stdin": ""}}) + "\\n")
if args[:2] == ["agents", "--json"] or args[:1] == ["agents"]:
    try:
        rc = int(open(os.path.join(ctl, "claude-agents.rc")).read() or 0)
    except OSError:
        rc = 0
    if rc == 0:
        print("[]")
    sys.exit(rc)
if "--bg" in args:
    name = args[args.index("-n") + 1] if "-n" in args else "unnamed"
    print("backgrounded \\u00b7 fake-claude-id \\u00b7 " + name)
sys.exit(0)
"""

FAKE_LOGGER = """#!{python}
import json, os, sys
ctl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ctl")
with open(os.path.join(ctl, "{tool}.log"), "a") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "stdin": ""}}) + "\\n")
print("{answer}")
"""


class Result:
    def __init__(self, proc):
        self.code = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr

    @property
    def text(self):
        return self.out + self.err


class World:
    """One temp world per test."""

    def __init__(self, tmp):
        self.root = Path(tmp).resolve()
        self.bin = self.root / "bin"
        self.ctl = self.root / "ctl"
        self.home = self.root / "home"
        self.team = self.root / "team"
        self.work = self.root / "work"
        self.checkout = self.root / "checkout"
        for d in (
            self.bin,
            self.ctl,
            self.home,
            self.team,
            self.work,
            self.checkout,
            self.team / "prompts",
            self.team / "reports",
        ):
            d.mkdir(parents=True, exist_ok=True)
        self.install("admiral", FAKE_ADMIRAL)
        self.install("claude", FAKE_CLAUDE)
        self.install("tmux", FAKE_LOGGER, tool="tmux", answer="%9")
        self.install("cmux", FAKE_LOGGER, tool="cmux", answer="surface:9")
        self.ctl_write("usage.txt", USAGE_NEW)
        self.write_team_env()

    def install(self, name, template, **fmt):
        path = self.bin / name
        path.write_text(template.format(python=sys.executable, **fmt))
        path.chmod(0o755)

    def ctl_write(self, name, text):
        (self.ctl / name).write_text(text)

    def write_team_env(self, harness="claude", extra=()):
        lines = []
        if harness is not None:
            lines.append(f"HARNESS={harness}")
        lines += [
            "REQUIRE_ROLE=1",
            "MODEL_TEST_WRITER=sonnet",
            "MODEL_REVIEWER=haiku",
            f"REPO={self.checkout}",
            *extra,
        ]
        (self.team / "team.env").write_text("\n".join(lines) + "\n")

    def env(self, ship=SHIP, **extra):
        """An environment from scratch: no ADMIRAL_*, TMUX, CMUX_* or CLAUDE_CONFIG_DIR unless a test sets them."""
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "LANG": "en_US.UTF-8",
        }
        if ship is not None:
            env["ADMIRAL_SHIP"] = ship
        env.update(extra)
        return env

    def run(self, script, *args, ship=SHIP, **extra_env):
        if not Path(script).exists():
            # a missing script is a failing assertion on its exit code, not a traceback in every test
            return Result(subprocess.CompletedProcess([str(script)], 127, "", f"{script}: no such file\n"))
        proc = subprocess.run(
            [str(script), *map(str, args)],
            env=self.env(ship, **extra_env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        return Result(proc)

    def prompt(self, name, text="do the job\n"):
        path = self.team / "prompts" / f"{name}.md"
        path.write_text(text)
        return path

    def message(self, text="next job\n"):
        path = self.root / "message.md"
        path.write_text(text)
        return path

    def register(self, name, session_id=None, epoch=None, viewer="-"):
        """A teammates.tsv row as launch-teammate.sh writes it."""
        epoch = int(time.time()) - 600 if epoch is None else epoch
        with open(self.team / "teammates.tsv", "a") as reg:
            reg.write(f"{name} {session_id or name} {epoch} {viewer} {self.work}\n")

    def registry(self):
        path = self.team / "teammates.tsv"
        return [line.split() for line in path.read_text().splitlines()] if path.exists() else []

    def boats(self, *boats):
        self.ctl_write("list.json", json.dumps(list(boats)))

    def calls(self, tool):
        path = self.ctl / f"{tool}.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def admiral(self):
        return [c["argv"] for c in self.calls("admiral")]


def boat(name, state="underway", last_activity=None, transcript=None, role=None):
    """One `admiral crew list --json` element."""
    return {
        "name": name,
        "harness": "claude",
        "dir": "/somewhere",
        "state": state,
        "launched": "2026-10-25T09:00:00Z",
        "last_activity": last_activity,
        "role": role,
        "transcript": transcript,
    }


class WorldCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.w = World(tmp.name)
