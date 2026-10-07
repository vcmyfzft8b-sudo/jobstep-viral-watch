import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'save_state.sh'


class SaveStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        self.repo = self.root / 'checkout'
        self.git = shutil.which('git')
        subprocess.run([self.git, 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        subprocess.run([self.git, 'init', '-b', 'main', str(self.repo)], check=True, capture_output=True)
        for args in (['config', 'user.name', 'test'], ['config', 'user.email', 'test@example.invalid'],
                     ['remote', 'add', 'origin', str(self.remote)]):
            self.run_git(*args)
        (self.repo / 'state').mkdir()
        (self.repo / 'state' / 'meta.json').write_text('{"version": 1}')
        self.run_git('add', 'state')
        self.run_git('commit', '-m', 'initial')
        self.run_git('push', '-u', 'origin', 'main')
        (self.repo / 'state' / 'meta.json').write_text('{"version": 2}')
        # A credential-like file outside state must not enter the commit.
        (self.repo / '.env').write_text('TEST_SECRET=do-not-commit')
        shim = self.root / 'bin'
        shim.mkdir()
        self.calls = self.root / 'push-count'
        git_shim = shim / 'git'
        git_shim.write_text('#!/usr/bin/env python3\n'
                            'import os, pathlib, subprocess, sys\n'
                            'if sys.argv[1] == "push":\n'
                            ' p = pathlib.Path(os.environ["PUSH_COUNT_FILE"])\n'
                            ' n = int(p.read_text()) + 1 if p.exists() else 1\n'
                            ' p.write_text(str(n))\n'
                            ' if n <= int(os.environ["FAILED_PUSHES"]):\n'
                            '  sys.exit(1)\n'
                            'sys.exit(subprocess.call([os.environ["REAL_GIT"], *sys.argv[1:]]))\n')
        git_shim.chmod(0o755)
        sleep_shim = shim / 'sleep'
        sleep_shim.write_text('#!/bin/sh\nexit 0\n')
        sleep_shim.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(shim) + os.pathsep + os.environ['PATH'],
                    'REAL_GIT': self.git, 'PUSH_COUNT_FILE': str(self.calls)}

    def run_git(self, *args):
        return subprocess.run([self.git, *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def save(self, failures):
        return subprocess.run(['bash', str(SCRIPT)], cwd=self.repo,
                              env={**self.env, 'FAILED_PUSHES': str(failures)}, capture_output=True, text=True)

    def test_transient_push_failure_retries_same_commit_successfully(self):
        result = self.save(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), '3')
        self.assertEqual(self.run_git('rev-parse', 'HEAD'), self.run_git('rev-parse', 'origin/main'))
        self.assertEqual(self.run_git('rev-list', '--count', 'HEAD'), '2')
        self.assertNotIn('.env', self.run_git('ls-tree', '--name-only', 'HEAD'))
        self.assertEqual(json.loads(self.run_git('show', 'origin/main:state/meta.json')), {'version': 2})

    def test_persistent_failure_is_bounded_and_preserves_recovery_state(self):
        result = self.save(99)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls.read_text(), '4')
        self.assertEqual(json.loads((self.repo / 'state' / 'meta.json').read_text()), {'version': 2})
        self.assertEqual(json.loads(self.run_git('show', 'origin/main:state/meta.json')), {'version': 1})
        self.assertNotEqual(self.run_git('rev-parse', 'HEAD'), self.run_git('rev-parse', 'origin/main'))

    def test_no_new_diff_still_pushes_previously_unpushed_commit(self):
        self.assertEqual(self.save(99).returncode, 1)
        self.calls.unlink()
        result = self.save(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_git('rev-list', '--count', 'HEAD'), '2')
        self.assertEqual(self.run_git('rev-parse', 'HEAD'), self.run_git('rev-parse', 'origin/main'))


if __name__ == '__main__':
    unittest.main()
