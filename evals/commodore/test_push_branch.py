"""push-branch.sh with an expected sha pushes only while the remote branch is still at that sha."""

import subprocess
import tempfile
import unittest
from pathlib import Path

PUSH = Path(__file__).resolve().parents[2] / "skills" / "engineering" / "commodore" / "scripts" / "push-branch.sh"


class ExpectedShaLease(unittest.TestCase):
    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.remote, self.work, self.run = root / "remote.git", root / "work", root / "run"
        self.git("init", "-q", "--bare", str(self.remote), cwd=root)
        self.git("init", "-q", "-b", "b", str(self.work), cwd=root)
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            self.git("config", k, v, cwd=self.work)
        self.git("remote", "add", "origin", str(self.remote), cwd=self.work)
        self.git("commit", "-q", "--allow-empty", "-m", "one", cwd=self.work)
        self.git("push", "-q", "origin", "b", cwd=self.work)
        self.pushed = self.git("rev-parse", "HEAD", cwd=self.work)
        self.git("commit", "-q", "--amend", "--allow-empty", "-m", "one, rewritten", cwd=self.work)
        self.run.mkdir()
        (self.run / "team.env").write_text("")
        (self.run / "worktrees.tsv").write_text(f"u1\tb\t{self.work}\n")

    def push(self, *extra):
        return subprocess.run(
            [str(PUSH), str(self.run), "b", *extra], capture_output=True, text=True, check=False
        ).returncode

    def test_a_stale_expected_sha_refuses_the_push(self):
        self.assertNotEqual(self.push("0" * 40), 0)
        self.assertEqual(self.git("rev-parse", "b", cwd=self.remote), self.pushed)

    def test_the_recorded_head_lets_the_push_through(self):
        self.assertEqual(self.push(self.pushed), 0)
        self.assertEqual(self.git("rev-parse", "b", cwd=self.remote), self.git("rev-parse", "HEAD", cwd=self.work))

    def test_a_malformed_sha_is_refused(self):
        self.assertEqual(self.push("HEAD"), 5)


if __name__ == "__main__":
    unittest.main()
