"""A temp world of copied skills, fake harness drivers and a preflight fixture for the crew-member tests."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC_SKILLS = REPO / "skills" / "engineering"
COPIED = ("commodore", "agent-teammates", "setup-commodore", "run-preflight", "target-evaluation")
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"
NINE = [
    "implementer",
    "test-writer",
    "reviewer",
    "security-reviewer",
    "brief-checker",
    "triager",
    "target-steward",
    "scribe",
    "fix-checker",
]
HAS_SKILL_STUB = """#!/bin/sh
# usage: has-skill <team-dir> <name>: installed when <team-dir>/installed.txt lists the name on a line of its own
grep -qxF -- "$2" "$1/installed.txt" 2>/dev/null
"""


def member_text(name, role, *, pick=None, body=None, skills=None, based_on=None, model=None, extra=""):  # noqa: PLR0913
    """A member file. `body` None gives a one-line body, "" gives none; `skills` None leaves the field out."""
    lines = ["---", f"name: {name}", f"role: {role}", f"pick-me-when: {pick if pick is not None else f'Pick {name}.'}"]
    if based_on is not None:
        lines.append(f"based-on: {based_on}")
    if model is not None:
        lines.append(f"model: {json.dumps(model)}")
    if skills is not None:
        lines.append(f"skills: [{', '.join(skills)}]")
    text = "\n".join(lines) + "\n" + extra + "---\n"
    body = f"Body of {name}." if body is None else body
    return text + (f"\n{body}\n" if body else "")


def split_row(line):
    """The cells of a Markdown table row; an escaped pipe stays inside its cell."""
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]


def parse_table(stdout):
    """(header line, separator line, {role: cells}, [roles in order]) of the cast table on stdout."""
    lines = [ln for ln in stdout.splitlines() if ln.startswith("|")]
    rows, order = {}, []
    for line in lines[2:]:
        cells = split_row(line)
        rows[cells[0]] = cells
        order.append(cells[0])
    return (lines[0] if lines else None), (lines[1] if len(lines) > 1 else None), rows, order


def link(src, dst):
    """Hard-link a shipped file; drivers/ is copied: tests write there, and a link would alter the repo."""
    if "/scripts/drivers/" not in dst:
        try:
            return os.link(src, dst)
        except OSError:
            pass
    return shutil.copy2(src, dst)


def zsh_value(team_env, *names):
    """The values `source team.env` leaves in zsh for `names`, in one call."""
    script = 'source "$1"; shift; for n in "$@"; do print -r -- "${(P)n}"; done'
    done = subprocess.run(
        ["zsh", "-c", script, "_", str(team_env), *names],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": BASE_PATH, "HOME": str(team_env.parent)},
    )
    return done.stdout.splitlines()


class World:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.skills = self.root / "skills"
        self.skills.mkdir()
        for name in COPIED:
            shutil.copytree(
                SRC_SKILLS / name, self.skills / name, ignore=shutil.ignore_patterns("__pycache__"), copy_function=link
            )
        self.crew_py = self.skills / "commodore" / "scripts" / "crew.py"
        self.scripts = self.skills / "commodore" / "scripts"
        self.drivers = self.skills / "agent-teammates" / "scripts" / "drivers"
        self.home = self.root / "home"
        self.xdg = self.root / "xdg"
        self.repo = self.root / "checkout"
        self.run = self.root / "run"
        self.tmp = self.root / "tmp"
        for d in (self.home, self.repo, self.run, self.tmp):
            d.mkdir()
        self.layer_dirs = {
            "user": self.xdg / "commodore" / "crew",
            "repo": self.repo / ".commodore" / "crew",
            "run": self.run / "crew",
            "fleet": self.root / "fleet",
            "admiral-run": self.root / "admiral-run",
        }
        # The real Claude driver's has-skill would read the machine's installed skills: answer from installed.txt.
        self.stub_driver("claude", prefix="/")
        self.team_env()

    def stub_driver(self, name, prefix="/", has_skill=True, list_skills=None):
        """Make drivers/<name> a fake: SKILL_PREFIX (none when `prefix` is None) and the has-skill stub."""
        d = self.drivers / name
        d.mkdir(exist_ok=True)
        lines = ["LIVE_MESSAGING=1", "SEND=tool"] + ([] if prefix is None else [f"SKILL_PREFIX={prefix}"])
        (d / "driver.env").write_text("\n".join(lines) + "\n")
        stub = d / "has-skill"
        if has_skill:
            stub.write_text(HAS_SKILL_STUB)
            stub.chmod(0o755)
        else:
            stub.unlink(missing_ok=True)
        if list_skills is not None:
            lister = d / "list-skills"
            (d / "list.txt").write_text("".join(f"{line}\n" for line in list_skills))
            lister.write_text('#!/bin/sh\ncat "$(dirname "$0")/list.txt"\n')
            lister.chmod(0o755)

    def team_env(self, harness="claude", lines=(), repo=True):
        body = ([f"HARNESS={harness}"] if harness else []) + ([f"REPO={self.repo}"] if repo else []) + list(lines)
        (self.run / "team.env").write_text("\n".join(body) + "\n")

    def install(self, *names):
        (self.run / "installed.txt").write_text("".join(f"{n}\n" for n in names))

    def write_member(self, layer, name, role=None, **kw):
        d = self.layer_dirs[layer]
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.md"
        path.write_text(member_text(name, role or name, **kw))
        return path

    def env(self, **extra):
        env = {
            "PATH": BASE_PATH,
            "HOME": str(self.home),
            "LANG": "en_US.UTF-8",
            "XDG_CONFIG_HOME": str(self.xdg),
            "TMPDIR": str(self.tmp),
        }
        env.update({k: v for k, v in extra.items() if v is not None})
        return env

    def admiral_env(self, **extra):
        return self.env(
            ADMIRAL_SHIP="ship-1",
            ADMIRAL_CREW_DIR=str(self.layer_dirs["fleet"]),
            ADMIRAL_RUN_CREW=str(self.layer_dirs["admiral-run"]),
            **extra,
        )

    def sh(self, cmd, env=None, cwd=None):
        return subprocess.run(
            [str(c) for c in cmd],
            env=env or self.env(),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def cast(self, *args, env=None, run=None):
        return self.sh([self.crew_py, "cast", "--run", run or self.run, *args], env=env)

    def read_json(self, name="cast.json"):
        return json.loads((self.run / name).read_text())


class WorldCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="crew-world-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.w = World(tmp)

    def warns(self, done):
        return [ln for ln in done.stderr.splitlines() if ln.startswith("WARN")]

    def roles_json_warnings(self, done, path):
        return [ln for ln in self.warns(done) if str(path) in ln and "convert-roles.py" in ln]

    def git_init(self, path):
        subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


PREFLIGHT = SRC_SKILLS / "commodore" / "scripts" / "team-preflight.sh"
# The roles and models team-init.sh writes for Claude, in its order.
DEFAULT_ROLES = [
    "MODEL_BRIEF_CHECKER=opus",
    "MODEL_TEST_WRITER=sonnet",
    "MODEL_IMPLEMENTER=sonnet",
    "MODEL_FIX_CHECKER=sonnet",
    "MODEL_REVIEWER=opus",
    "MODEL_SECURITY_REVIEWER=opus",
    "MODEL_TRIAGER=opus",
    "MODEL_TARGET_STEWARD=sonnet",
    "MODEL_SCRIBE=sonnet",
]
# The claude driver's own preflight needs `claude` on PATH and `claude agents --json` to succeed.
FAKE_CLAUDE = """#!/bin/sh
[ "$1" = agents ] && echo "[]"
exit 0
"""
PROBE_STUB = """#!/bin/sh
printf '%s %s\\n' "$1" "$2" >> "$PROBE_LOG"
echo "ADVISOR ON $2"
"""


class PreflightCase(unittest.TestCase):
    """team-preflight.sh against a hand-written team.env, a git checkout and an ADVISOR_PROBE stub that logs."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.team = self.root / "team"
        self.team.mkdir()
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        git = ["git", "-C", str(self.repo)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "config", "user.email", "test@example.com"], check=True)
        subprocess.run([*git, "config", "user.name", "Test"], check=True)
        self.log = self.root / "probe.log"
        self.stub = self.root / "probe-stub"
        self.stub.write_text(PROBE_STUB)
        self.stub.chmod(0o755)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(0o755)

    def team_env(self, *lines, model="sonnet", advisor="opus", roles=DEFAULT_ROLES, harness="claude"):
        body = [
            f"HARNESS={harness}",
            f"REPO={self.repo}",
            "REQUIRED_TOOLS=git",
            "MODE=single",
            f"MODEL={model}",
            f"ADVISOR={advisor}",
            "REQUIRE_ROLE=1",
            *roles,
            *lines,
        ]
        (self.team / "team.env").write_text("\n".join(body) + "\n")

    def run_preflight(self, probe=True, claudecode="1", **extra):
        # Without CLAUDECODE, detect-harness.sh prints nothing and no probe starts at all.
        env = {
            "PATH": f"{self.bin}:{BASE_PATH}",
            "HOME": str(self.home),
            "LANG": "en_US.UTF-8",
            "PROBE_LOG": str(self.log),
            "CLAUDECODE": claudecode,
        }
        if not claudecode:
            del env["CLAUDECODE"]
        if probe:
            env["ADVISOR_PROBE"] = str(self.stub)
        env.update(extra)
        return subprocess.run(
            [str(PREFLIGHT), str(self.team)],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def probed(self):
        """(run-dir, model) for every probe the stub logged, sorted."""
        if not self.log.exists():
            return []
        return sorted(tuple(line.split(" ", 1)) for line in self.log.read_text().splitlines())

    def lines(self, done, prefix):
        return [line for line in done.stdout.splitlines() if line.startswith(prefix)]
