"""Host-isolated unit tests for agy-worktree PreToolUse guard hook (worktree-guard.py)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
GUARD_PATH = PLUGIN_ROOT / "scripts" / "worktree-guard.py"


def load_module(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


guard = load_module("agy_wt_guard_testmod", GUARD_PATH)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


class WorktreeGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.data_dir = self.root / "agy-data"
        self.brain_dir = self.data_dir / "brain" / "conv-guard-1"
        (self.brain_dir / "scratch").mkdir(parents=True)
        self.cfg_path = self.root / "agy-worktree.json"

        # Strict main repo + linked worktree
        self.strict_repo = self.root / "strict-app"
        self.strict_repo.mkdir()
        git(self.strict_repo, "init", "-b", "main")
        git(self.strict_repo, "config", "user.email", "t@e.com")
        git(self.strict_repo, "config", "user.name", "T")
        (self.strict_repo / "Sources").mkdir()
        (self.strict_repo / "Sources" / "App.swift").write_text("struct App {}\n", encoding="utf-8")
        (self.strict_repo / "docs").mkdir()
        (self.strict_repo / "docs" / "notes.md").write_text("hi\n", encoding="utf-8")
        (self.strict_repo / "env.local").write_text("tracked\n", encoding="utf-8")
        (self.strict_repo / "git" / "info").mkdir(parents=True)
        (self.strict_repo / "git" / "info" / "exclude").write_text("tracked\n", encoding="utf-8")
        (self.strict_repo / ".gitignore").write_text("build/\n", encoding="utf-8")
        git(self.strict_repo, "add", ".")
        git(self.strict_repo, "commit", "-m", "init")
        (self.strict_repo / ".git" / "info" / "exclude").write_text("local-notes.md\n", encoding="utf-8")

        self.wt_dir = self.root / "strict-app-worktree" / "strict-app-feat-x"
        self.wt_dir.parent.mkdir(parents=True)
        git(self.strict_repo, "worktree", "add", "-b", "feat/x", str(self.wt_dir), "main")

        # Unlisted normal repo
        self.normal_repo = self.root / "normal-repo"
        self.normal_repo.mkdir()
        git(self.normal_repo, "init", "-b", "main")
        git(self.normal_repo, "config", "user.email", "t@e.com")
        git(self.normal_repo, "config", "user.name", "T")
        (self.normal_repo / "README.md").write_text("ok\n", encoding="utf-8")
        git(self.normal_repo, "add", ".")
        git(self.normal_repo, "commit", "-m", "init")

        self.protected_ext = self.root / "user-account-data"
        self.protected_ext.mkdir()

        self.cfg_path.write_text(
            json.dumps(
                {
                    "strict_main_repos": [str(self.strict_repo)],
                    "repos": {
                        str(self.strict_repo): {
                            "allow_main_paths": [".git/info/exclude", "docs/*.md", "notes/", ".env.local"],
                            "protected_paths": [".build", "build/app-bin", str(self.protected_ext)],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        self._env_patch = mock.patch.dict(
            os.environ,
            {"AGY_DATA_DIR": str(self.data_dir), "AGY_WORKTREE_CONFIG": str(self.cfg_path)},
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self.tmp.cleanup()

    def _payload(self, tool_name: str, args: dict, cwd: Path | None = None) -> dict:
        return {
            "conversationId": "conv-guard-1",
            "artifactDirectoryPath": str(self.brain_dir),
            "cwd": str(cwd or self.strict_repo),
            "toolCall": {"name": tool_name, "args": args},
        }

    def test_strict_main_file_writes_allow_paths_dotfile_and_dotgit_protection(self) -> None:
        # Tracked & brand-new unignored files -> DENIED
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "Sources" / "App.swift")}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("write_file", {"Path": str(self.strict_repo / "Sources" / "New.swift")}),
                config_path=self.cfg_path,
            )[0]
        )

        # Dotfile allow_main_paths MUST NOT strip leading dots (F1!)
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "env.local")}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "git" / "info" / "exclude")}),
                config_path=self.cfg_path,
            )[0]
        )

        # .git/config and .git/hooks/* are DENIED while .git/info/exclude is ALLOWED (F10!)
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / ".git" / "config")}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("write_file", {"Path": str(self.strict_repo / ".git" / "hooks" / "pre-commit")}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / ".git" / "info" / "exclude")}),
                config_path=self.cfg_path,
            )[0]
        )

        # Non-.git/ allow_main_paths globs and dir prefixes work
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "docs" / "notes.md")}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("write_file", {"Path": str(self.strict_repo / "notes" / "todo.txt")}),
                config_path=self.cfg_path,
            )[0]
        )

        # Ignored local file & build/ -> ALLOWED; linked worktree -> ALLOWED; normal repo -> ALLOWED
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("write_file", {"Path": str(self.strict_repo / "local-notes.md")}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.wt_dir / "Sources" / "App.swift")}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.normal_repo / "README.md")}, cwd=self.normal_repo),
                config_path=self.cfg_path,
            )[0]
        )

    def test_macos_apfs_case_insensitivity_and_symlink_repo_parity(self) -> None:
        # Symlinked repo path is still matched as strict_main_repo
        repo_link = self.root / "strict-link"
        repo_link.symlink_to(self.strict_repo)
        ok_sym, _ = guard.evaluate_payload(
            self._payload("edit_file", {"Path": str(repo_link / "Sources" / "App.swift")}, cwd=repo_link),
            config_path=self.cfg_path,
        )
        self.assertFalse(ok_sym)

        if sys.platform == "darwin":
            alt_case_repo = self.root / "STRICT-APP"
            if alt_case_repo.exists():
                ok_alt, _ = guard.evaluate_payload(
                    self._payload("edit_file", {"Path": str(alt_case_repo / "Sources" / "App.swift")}, cwd=alt_case_repo),
                    config_path=self.cfg_path,
                )
                self.assertFalse(ok_alt, "APFS alternate-case repo path must not bypass guard")

                ok_redir, _ = guard.evaluate_payload(
                    self._payload("run_command", {"CommandLine": "echo bad > sources/app.swift"}),
                    config_path=self.cfg_path,
                )
                self.assertFalse(ok_redir, "APFS alternate-case redirection must not overwrite tracked file")

    def test_shell_git_redirection_and_wrapper_bypasses_plus_false_positives(self) -> None:
        blocked_cmds = [
            "git commit -m 'bad'",
            "git add Sources/App.swift",
            "git checkout -b feat/oops",
            "git switch -c feat/oops",
            "git merge feat/x",
            "git rebase origin/main",
            "git reset --hard HEAD~1",
            "git stash",
            "git pull",
            "git pull --ff-only --no-ff",
            "git pull --ff-only --rebase",
            "git push origin main",
            "git push origin --delete main",
            "git push origin --delete refs/heads/main",
            "git push origin :main",
            "git push origin :refs/heads/main",
            "git branch -D main",
            "git branch -m main moved",
            "git branch feat/direct",
            # Shell wrappers, subshells, comments, background &, |& (F9)
            "echo hi # don't touch\ngit commit -m x",
            "'git' commit -m x # don't",
            "env git commit -m x",
            "command git commit -m x",
            "time git commit -m x",
            "exec git commit -m x",
            "! git commit -m x",
            "(git commit -m x)",
            "{ git commit -m x; }",
            "true & git commit -m x",
            "echo hi |& git commit -m x",
            f"cd '{self.wt_dir}' && cd - && git commit -m x",
            f"cd -- '{self.strict_repo}' && git commit -m x",
            # Explicit --git-dir and GIT_DIR from /tmp (F11)
            f"GIT_DIR='{self.strict_repo}/.git' git commit -m x",
            f"git --git-dir='{self.strict_repo}/.git' commit -m x",
            # Redirection bypasses (F10)
            "echo bad > Sources/App.swift",
            "echo bad >> Sources/App.swift",
            "echo bad >| Sources/App.swift",
            "echo bad >& Sources/App.swift",
            'echo bad > "Sources/App".swift',
            r"echo bad > Sources/\App.swift",
            "cat > Sources/NewFile.swift",
            "echo bad > .git/config",
        ]
        for cmd in blocked_cmds:
            ok, _ = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}, cwd=self.strict_repo),
                config_path=self.cfg_path,
            )
            self.assertFalse(ok, f"Expected BLOCK for: {cmd}")

        # Cross-directory mutation starting from linked worktree targeting strict main
        for cmd in (
            f"git -C '{self.strict_repo}' commit -m x",
            f"GIT_DIR='{self.strict_repo}/.git' git commit -m x",
            f"cd '{self.strict_repo}' && git reset --hard",
        ):
            ok, _ = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}, cwd=self.wt_dir),
                config_path=self.cfg_path,
            )
            self.assertFalse(ok, f"Expected BLOCK from wt cwd for: {cmd}")

        # Legitimate commands MUST be ALLOWED (including 6-step closeout & fd dups & combined flags)
        allowed_cmds = [
            "git status",
            "git diff --quiet origin/main feat/x --",
            "git fetch --prune",
            "git pull --ff-only",
            "git pull --ff-only origin main",
            "git worktree list",
            f"git worktree remove '{self.wt_dir}'",
            "git branch -a",
            "git branch -av",
            "git branch 2>&1",
            "git branch -v 2>&1",
            "git branch -D feat/x",
            "git branch -D -- feat/x",
            "git push origin --delete feat/x",
            "git push origin :feat/x",
            "git push origin :feat/x 2>&1",
            "make install",
            "echo local-notes.md >> .git/info/exclude",
            'echo "a > Sources/App.swift"',
            f"git -C '{self.wt_dir}' add -A && git -C '{self.wt_dir}' commit -m 'ok'",
            f"cd '{self.wt_dir}' && git push -u origin feat/x",
        ]
        for cmd in allowed_cmds:
            ok, reason = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}),
                config_path=self.cfg_path,
            )
            self.assertTrue(ok, f"Expected ALLOW for {cmd!r}, got denied: {reason}")

    def test_worktree_install_block_and_no_false_positive_on_commit_or_grep(self) -> None:
        # Blocked install variants inside linked worktree
        for cmd in (
            f"make -C '{self.wt_dir}' install",
            f"gmake -C '{self.wt_dir}' install",
            f"env make -C '{self.wt_dir}' install",
            f"cd '{self.wt_dir}' && make install",
            f"cd -P '{self.wt_dir}' && make install",
            f"(cd '{self.wt_dir}' && make install)",
        ):
            ok, _ = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}),
                config_path=self.cfg_path,
            )
            self.assertFalse(ok, f"Expected BLOCK for worktree install: {cmd}")

        # Must NOT falsely block git commit / rg / echo mentioning "make install" inside worktree (F8!)
        for cmd in (
            f"cd '{self.wt_dir}' && git commit -m 'docs: warn against make install in worktree'",
            f"cd '{self.wt_dir}' && rg 'make install' README.md",
            f"cd '{self.wt_dir}' && echo 'run make install after merge'",
            f"make -C '{self.wt_dir}' build && make -C '{self.wt_dir}' test",
        ):
            ok, reason = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}),
                config_path=self.cfg_path,
            )
            self.assertTrue(ok, f"Expected ALLOW for {cmd!r}, got denied: {reason}")

    def test_protected_paths_and_per_repo_guard_modes_and_fail_closed(self) -> None:
        # protected_paths blocks rm on .build, build/app-bin, parent build/, and external ~/.fake dir (F21)
        for cmd in (
            "rm -rf .build",
            "rm -f build/app-bin",
            "rm -rf build",
            f"rm -rf '{self.protected_ext}'",
        ):
            ok, _ = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}),
                config_path=self.cfg_path,
            )
            self.assertFalse(ok, f"Expected protected_paths BLOCK for: {cmd}")
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": "rm -rf /tmp/unrelated-junk"}),
                config_path=self.cfg_path,
            )[0]
        )

        # Per-repo guard.mode="active-only" allows strict_repo when inactive, blocks when active (F13)
        cfg_ao = self.root / "cfg-active-only.json"
        cfg_ao.write_text(
            json.dumps(
                {
                    "strict_main_repos": [str(self.strict_repo)],
                    "repos": {str(self.strict_repo): {"guard": {"mode": "active-only"}}},
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "Sources" / "App.swift")}),
                config_path=cfg_ao,
            )[0]
        )

        # Activate worktree -> now blocked under active-only; deleting worktree dir recovers fail-open
        state_file = self.brain_dir / "scratch" / "worktree.json"
        state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "state": "active",
                    "main_dir": str(self.strict_repo),
                    "worktree_path": str(self.wt_dir),
                    "branch": "feat/x",
                }
            ),
            encoding="utf-8",
        )
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "Sources" / "App.swift")}),
                config_path=cfg_ao,
            )[0]
        )

        # Per-repo guard.enabled=false disables even worktree install blocking (F13)
        cfg_off = self.root / "cfg-off.json"
        cfg_off.write_text(
            json.dumps(
                {
                    "strict_main_repos": [str(self.strict_repo)],
                    "repos": {str(self.strict_repo): {"guard": {"enabled": False}}},
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "Sources" / "App.swift")}),
                config_path=cfg_off,
            )[0]
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": f"make -C '{self.wt_dir}' install"}),
                config_path=cfg_off,
            )[0]
        )

        # Corrupt JSON config fails closed on mutating tools (S1)
        cfg_bad = self.root / "cfg-bad.json"
        cfg_bad.write_text("{broken", encoding="utf-8")
        ok_bad, reason_bad = guard.evaluate_payload(
            self._payload("edit_file", {"Path": str(self.normal_repo / "README.md")}, cwd=self.normal_repo),
            config_path=cfg_bad,
        )
        self.assertFalse(ok_bad)
        self.assertIn("config error", reason_bad)

        # Null nested dict `"guard": null` does NOT crash or disable protection (S2/X11)
        cfg_null = self.root / "cfg-null.json"
        cfg_null.write_text(
            json.dumps({"strict_main_repos": [str(self.strict_repo)], "guard": None, "exit": None}),
            encoding="utf-8",
        )
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("edit_file", {"Path": str(self.strict_repo / "Sources" / "App.swift")}),
                config_path=cfg_null,
            )[0]
        )

        # _git_is_tracked fails closed on fatal git exit code 128 (S3)
        self.assertTrue(guard._git_is_tracked(self.root / "nonexistent-dir-xyz", "README.md"))

    def test_session_hint_only_fires_on_real_agy_wt_exec_and_honors_repo_flag(self) -> None:
        # Unrelated commands mentioning agy-wt MUST NOT write/overwrite hint (F16!)
        hint_file = guard.wt.hint_dir_path() / f"{guard.wt.repo_hash(self.strict_repo)}.json"
        hint_file.unlink(missing_ok=True)
        guard.evaluate_payload(
            self._payload("run_command", {"CommandLine": "ls -la ~/.local/bin/agy-wt && rg agy-wt README.md"}),
            config_path=self.cfg_path,
        )
        self.assertIsNone(guard.wt.read_session_hint(self.strict_repo))

        # Real `agy-wt enter --repo <normal_repo>` from strict_repo writes hint under normal_repo hash!
        guard.evaluate_payload(
            self._payload("run_command", {"CommandLine": f"agy-wt enter feat/other --repo '{self.normal_repo}'"}),
            config_path=self.cfg_path,
        )
        hint = guard.wt.read_session_hint(self.normal_repo, consume=True)
        self.assertIsNotNone(hint)
        self.assertEqual(hint["conversation_id"], "conv-guard-1")

    def test_round2_regressions_heredoc_subshell_wrappers_tilde_fifo_and_dotdot(self) -> None:
        # GC-01: FIFO must not hang resolve_path_safe
        fifo = self.root / "test.fifo"
        os.mkfifo(fifo)
        self.assertEqual(guard.wt.resolve_path_safe(fifo).name, "test.fifo")

        # GC-02: ~notes.txt, ~$temp.docx, cd ~- must not raise RuntimeError / fail closed
        for pld in (
            self._payload("write_file", {"Path": "~notes.txt"}, cwd=Path("/tmp")),
            self._payload("run_command", {"CommandLine": "rm -f '~$temp.docx'"}, cwd=Path("/tmp")),
            self._payload("run_command", {"CommandLine": "cd ~- && git status"}, cwd=self.strict_repo),
        ):
            ok, reason = guard.evaluate_payload(pld, config_path=self.cfg_path)
            self.assertTrue(ok, f"Unexpected deny on tilde literal: {reason}")

        # GC-03: '..' over nonexistent segments must not bypass allow_main_paths, protected_paths, or wt boundary
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": "echo bad > notes/noexist/../../Sources/App.swift"}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": "rm -rf noexist/../.build"}),
                config_path=self.cfg_path,
            )[0]
        )
        self.assertFalse(
            guard.evaluate_payload(
                self._payload(
                    "run_command",
                    {"CommandLine": f"echo bad > noexist/../../../strict-app/Sources/App.swift"},
                    cwd=self.wt_dir,
                ),
                config_path=self.cfg_path,
            )[0]
        )

        # GC-04 & GC-05: heredocs, [[ > ]], (( > )), $(( > )), <<<, --format/--sort MUST be allowed
        for cmd in (
            "python3 - <<'EOF'\nif x > y:\n    print(1)\nEOF",
            "cat <<'EOF'\n> quoted note\nEOF",
            '[[ "$ver" > "1.0" ]] && echo ok',
            "if (( count > 0 )); then echo ok; fi",
            "echo $(( 5 > 3 ))",
            'git branch <<< ""',
            "git branch --format '%(refname:short)'",
            "git branch --sort -committerdate",
            f"(cd '{self.wt_dir}' && echo ok) && make install",
        ):
            ok, reason = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}, cwd=self.strict_repo),
                config_path=self.cfg_path,
            )
            self.assertTrue(ok, f"False positive on {cmd!r}: {reason}")

        # GC-04 & GC-06: heredoc commit & gh pr create & python3 -c & command -v inside worktree ALLOWED
        for cmd in (
            "git commit -F - <<'EOF'\ndocs: remind users to run make install\nEOF",
            'gh pr create --body "Please make sure to install deps"',
            'gh pr create --body "Run make install after merge"',
            'python3 -c \'print("make install")\'',
            "command -v make install >/dev/null",
            'if true; then echo "make install"; fi',
        ):
            ok, reason = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}, cwd=self.wt_dir),
                config_path=self.cfg_path,
            )
            self.assertTrue(ok, f"False positive in worktree on {cmd!r}: {reason}")

        # GC-05, GC-07, GC-08, GC-09: real bypasses MUST be blocked
        for cmd in (
            "exec 3<> Sources/App.swift",
            "echo bad >>| Sources/App.swift",
            "echo bad >! Sources/App.swift",
            "(cd /tmp && ls) && git commit -m x",
            "cd /tmp | git commit -m x",
            "if true; then git commit -m x; fi",
            "for x in 1; do rm -rf .build; done",
            'env -S "git commit -m x"',
            "env -P /usr/bin git commit -m x",
            "command -v cd && git commit -m x",
        ):
            ok, _ = guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": cmd}, cwd=self.strict_repo),
                config_path=self.cfg_path,
            )
            self.assertFalse(ok, f"Bypass allowed for: {cmd}")

        # env -C <strict_repo> from /tmp blocked
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": f"env -C '{self.strict_repo}' git commit -m x"}, cwd=Path("/tmp")),
                config_path=self.cfg_path,
            )[0]
        )

        # make -j install, make -l install, sh -c 'make install' in worktree blocked (GC-07)
        for cmd in ("make -j install", "make -l install", "sh -c 'make install'"):
            self.assertFalse(
                guard.evaluate_payload(
                    self._payload("run_command", {"CommandLine": cmd}, cwd=self.wt_dir),
                    config_path=self.cfg_path,
                )[0],
                f"Expected worktree install BLOCK for: {cmd}",
            )

        # GC-09 quoted path ending with ')' + GC-10 $TMPDIR skip & shorthand disable
        prot_paren = self.root / "prot(1)"
        prot_paren.mkdir()
        cfg_p = self.root / "cfg-paren.json"
        cfg_p.write_text(json.dumps({"protected_paths": [str(prot_paren)]}), encoding="utf-8")
        self.assertFalse(
            guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": f'rm -rf "{prot_paren}"'}, cwd=self.root),
                config_path=cfg_p,
            )[0]
        )
        self.assertTrue(
            guard.evaluate_payload(
                self._payload("run_command", {"CommandLine": 'rm -rf "$TMPDIR/scratch"'}, cwd=prot_paren),
                config_path=cfg_p,
            )[0]
        )

        # GC-13 & GC-14: repo dir containing braces & deep_merge null boolean protection
        brace_repo = self.root / "{app}"
        brace_repo.mkdir()
        rendered = guard.wt.render_worktree_path(brace_repo, "feat/x", guard.wt.DEFAULT_CONFIG)
        self.assertTrue(str(rendered).endswith("{app}-feat-x"))
        self.assertTrue(guard.wt.deep_merge(guard.wt.DEFAULT_CONFIG, {"guard": {"enabled": None}})["guard"]["enabled"])
        self.assertEqual(guard.wt.strip_rel_prefix("/./.git/info/exclude"), ".git/info/exclude")


if __name__ == "__main__":
    unittest.main()
