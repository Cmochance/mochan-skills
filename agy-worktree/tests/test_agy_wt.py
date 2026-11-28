"""Host-isolated unit tests for agy-wt CLI using real temporary git repositories."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = PLUGIN_ROOT / "scripts" / "agy-wt"
COMMON_PATH = PLUGIN_ROOT / "scripts" / "wt_common.py"
GUARD_PATH = PLUGIN_ROOT / "scripts" / "worktree-guard.py"


def load_module(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


wt_common = load_module("agy_wt_common_testmod", COMMON_PATH)
agy_wt = load_module("agy_wt_cli_testmod", CLI_PATH)
guard = load_module("agy_wt_guard_e2e_testmod", GUARD_PATH)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        text=True,
        capture_output=True,
        check=True,
    )


class AgyWtCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.data_dir = self.root / "agy-data"
        self.data_dir.mkdir(parents=True)
        self.cfg_path = self.root / "agy-worktree.json"
        self.brain_dir = self.data_dir / "brain" / "conv-123"
        logs_dir = self.brain_dir / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True)
        self.transcript = logs_dir / "transcript.jsonl"
        self.transcript_full = logs_dir / "transcript_full.jsonl"
        self.transcript.write_text('{"step_index":0}\n', encoding="utf-8")
        self.transcript_full.write_text('{"step_index":0,"content":"' + ("x" * 200) + '"}\n', encoding="utf-8")

        # Create bare remote + local main repo
        self.bare = self.root / "origin.git"
        self.bare.mkdir()
        git(self.bare, "init", "--bare", "-b", "main")

        self.repo = self.root / "demo-repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Tester")
        (self.repo / ".gitignore").write_text(
            "build/\ndist/\n.venv/\n.pytest_cache/\n__pycache__/\n.dist/\n*.local\n",
            encoding="utf-8",
        )
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore", "README.md")
        git(self.repo, "commit", "-m", "init")
        git(self.repo, "remote", "add", "origin", str(self.bare))
        git(self.repo, "push", "-u", "origin", "main")
        git(self.repo, "remote", "set-head", "origin", "main")

        self._env_patch = mock.patch.dict(
            os.environ,
            {
                "AGY_DATA_DIR": str(self.data_dir),
                "AGY_WORKTREE_CONFIG": str(self.cfg_path),
            },
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self.tmp.cleanup()

    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = agy_wt.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_enter_reuse_status_list_exit_keep_and_dual_watermarks(self) -> None:
        code, out, err = self._run_cli(
            ["enter", "feat/new-ui", "--repo", str(self.repo), "--session", "conv-123", "--json"]
        )
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["action"], "created")
        expected_wt = self.root / "demo-repo-worktree" / "demo-repo-feat-new-ui"
        self.assertEqual(Path(res["worktree_path"]), expected_wt)
        self.assertTrue(expected_wt.is_dir())

        state_file = self.brain_dir / "scratch" / "worktree.json"
        self.assertEqual(stat.S_IMODE(state_file.stat().st_mode), 0o600)

        # Re-entering reuses existing worktree
        code2, out2, err2 = self._run_cli(
            ["enter", "feat/new-ui", "--repo", str(self.repo), "--session", "conv-123", "--json"]
        )
        self.assertEqual(code2, 0, err2)
        self.assertEqual(json.loads(out2)["action"], "reused")

        # Refuses nested worktree inside main repo (F3 bidirectional is_path_within)
        code_nested, _, err_nested = self._run_cli(
            ["enter", "feat/nested", "--repo", str(self.repo), "--path", ".worktrees/nested", "--session", "conv-123"]
        )
        self.assertEqual(code_nested, 1)
        self.assertIn("must not overlap", err_nested)

        # Refuses slug/path collision with existing worktree on a different branch (F7)
        code_col, _, err_col = self._run_cli(
            ["enter", "feat-new-ui", "--repo", str(self.repo), "--session", "conv-123"]
        )
        self.assertEqual(code_col, 1)
        self.assertIn("already a worktree for branch", err_col)

        # Cannot enter main branch itself
        code_main, _, err_main = self._run_cli(["enter", "main", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(code_main, 1)
        self.assertIn("already checked out", err_main)

        # status & list report active worktree
        code_st, out_st, _ = self._run_cli(["status", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(code_st, 0)
        self.assertTrue(json.loads(out_st)["session_active"])

        code_ls, out_ls, _ = self._run_cli(["list", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(code_ls, 0)
        self.assertTrue(any(w["branch"] == "feat/new-ui" and w["session_active"] for w in json.loads(out_ls)))

        # exit records BOTH transcript.jsonl and transcript_full.jsonl watermarks (F15)
        code_ex, out_ex, err_ex = self._run_cli(["exit", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(code_ex, 0, err_ex)
        ex_res = json.loads(out_ex)
        self.assertFalse(ex_res["removed"])
        self.assertEqual(ex_res["exit_transcript_offset"], self.transcript.stat().st_size)
        self.assertEqual(ex_res["exit_transcript_offsets"]["transcript.jsonl"], self.transcript.stat().st_size)
        self.assertEqual(ex_res["exit_transcript_offsets"]["transcript_full.jsonl"], self.transcript_full.stat().st_size)

        # Refuses entering a deleted prunable worktree (F7)
        shutil.rmtree(expected_wt)
        code_prun, _, err_prun = self._run_cli(["enter", "feat/new-ui", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(code_prun, 1)
        self.assertIn("missing/prunable", err_prun)

    def test_enter_post_create_rollback_existing_branches_and_template_validation(self) -> None:
        # 1. post_create_commands receives AGY_WT_* env vars
        env_dump = self.root / "post_create_env.txt"
        self.cfg_path.write_text(
            json.dumps(
                {
                    "enter": {
                        "post_create_commands": [
                            f"printf '%s|%s|%s' \"$AGY_WT_MAIN_DIR\" \"$AGY_WT_PATH\" \"$AGY_WT_BRANCH\" > '{env_dump}'"
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        c1, out1, err1 = self._run_cli(["enter", "feat/pc-ok", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(c1, 0, err1)
        wt1 = Path(json.loads(out1)["worktree_path"])
        self.assertEqual(env_dump.read_text(encoding="utf-8"), f"{self.repo}|{wt1}|feat/pc-ok")

        # 2. Failing post_create_command rolls back newly created worktree cleanly
        self.cfg_path.write_text(json.dumps({"enter": {"post_create_commands": ["exit 42"]}}), encoding="utf-8")
        c2, _, err2 = self._run_cli(["enter", "feat/pc-fail", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(c2, 1)
        self.assertIn("Rolled back", err2)
        self.assertFalse((self.root / "demo-repo-worktree" / "demo-repo-feat-pc-fail").exists())

        # 3. Invalid path_template placeholder & invalid branch_slug_separator raise clean error (exit 1, no traceback)
        self.cfg_path.write_text(json.dumps({"path_template": "../{repo}-{branch}"}), encoding="utf-8")
        c3, _, err3 = self._run_cli(["enter", "feat/bad-tpl", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(c3, 1)
        self.assertIn("Unknown placeholder", err3)

        self.cfg_path.write_text(json.dumps({"branch_slug_separator": "/"}), encoding="utf-8")
        c4, _, err4 = self._run_cli(["enter", "feat/bad-sep", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(c4, 1)
        self.assertIn("Invalid branch_slug_separator", err4)

        # 4. Corrupt JSON config fails closed in CLI (exit 1)
        self.cfg_path.write_text("{bad json", encoding="utf-8")
        c5, _, err5 = self._run_cli(["status", "--repo", str(self.repo)])
        self.assertEqual(c5, 1)
        self.assertIn("Invalid or unreadable config", err5)

    def test_exit_remove_safety_gates_and_cross_repo_isolation(self) -> None:
        # Enter wt1
        c1, out1, err1 = self._run_cli(["enter", "feat/ex1", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(c1, 0, err1)
        wt1 = Path(json.loads(out1)["worktree_path"])

        # Mutually exclusive flags
        cm, _, errm = self._run_cli(["exit", "--remove", "--keep", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(cm, 1)
        self.assertIn("mutually exclusive", errm)

        # Unbound exit in keep mode fails instead of silent no-op (S8)
        cu, _, erru = self._run_cli(["exit", "--repo", str(self.repo)])
        self.assertEqual(cu, 1)
        self.assertIn("no active agy session", erru)

        # Dirty tracked file blocks --remove
        (wt1 / "README.md").write_text("dirty\n", encoding="utf-8")
        cd, _, errd = self._run_cli(["exit", "--remove", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(cd, 1)
        self.assertIn("uncommitted changes", errd)
        (wt1 / "README.md").write_text("hello\n", encoding="utf-8")

        # Untracked Unicode file blocks --remove (git status -z handles non-ASCII cleanly!)
        (wt1 / "中文笔记.txt").write_text("note", encoding="utf-8")
        cut, _, errut = self._run_cli(["exit", "--remove", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(cut, 1)
        self.assertIn("中文笔记.txt", errut)
        (wt1 / "中文笔记.txt").unlink()

        # Dot-dir safe defaults (.venv, .pytest_cache, nested __pycache__) pass, while .dist/ (unsafe dotdir) MUST block (F1!)
        (wt1 / ".venv").mkdir()
        (wt1 / ".venv" / "pyvenv.cfg").write_text("x", encoding="utf-8")
        (wt1 / ".pytest_cache").mkdir()
        (wt1 / ".pytest_cache" / "v").write_text("x", encoding="utf-8")
        (wt1 / "pkg" / "__pycache__").mkdir(parents=True)
        (wt1 / "pkg" / "__pycache__" / "a.pyc").write_text("x", encoding="utf-8")
        (wt1 / ".dist").mkdir()
        (wt1 / ".dist" / "secret").write_text("keep!", encoding="utf-8")

        c_dot, _, err_dot = self._run_cli(["exit", "--remove", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(c_dot, 1)
        self.assertIn(".dist", err_dot)
        self.assertNotIn(".venv", err_dot)
        self.assertNotIn(".pytest_cache", err_dot)
        self.assertNotIn("__pycache__", err_dot)

        # --confirm-ignored removes worktree cleanly
        with mock.patch.object(agy_wt, "_cleanup_macos_app_bundles", return_value=[]):
            c_rm, out_rm, err_rm = self._run_cli(
                ["exit", "--remove", "--confirm-ignored", "--repo", str(self.repo), "--session", "conv-123", "--json"]
            )
        self.assertEqual(c_rm, 0, err_rm)
        self.assertTrue(json.loads(out_rm)["removed"])
        self.assertFalse(wt1.exists())

        # Cross-repo isolation: active on repo A must NOT be clobbered by exit --repo repoB (F5)
        repo_b = self.root / "repo-b"
        repo_b.mkdir()
        git(repo_b, "init", "-b", "main")
        git(repo_b, "config", "user.email", "t@e.com")
        git(repo_b, "config", "user.name", "T")
        (repo_b / "a.txt").write_text("a\n", encoding="utf-8")
        git(repo_b, "add", ".")
        git(repo_b, "commit", "-m", "init")

        self._run_cli(["enter", "feat/repo-a-wt", "--repo", str(self.repo), "--session", "conv-123"])
        c_cross, _, err_cross = self._run_cli(["exit", "--repo", str(repo_b), "--session", "conv-123"])
        self.assertEqual(c_cross, 1)
        self.assertIn("different repository", err_cross)
        st = json.loads((self.brain_dir / "scratch" / "worktree.json").read_text(encoding="utf-8"))
        self.assertEqual(st["state"], "active")

    def test_close_modes_no_remote_delete_already_absent_and_local_only(self) -> None:
        # 1. --no-remote-delete passes Step 6 and marks session exited (F2!)
        c1, out1, err1 = self._run_cli(["enter", "feat/keep-rem", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(c1, 0, err1)
        wt1 = Path(json.loads(out1)["worktree_path"])
        git(wt1, "push", "-u", "origin", "feat/keep-rem")

        with mock.patch.object(agy_wt, "_cleanup_macos_app_bundles", return_value=[]):
            c_nr, out_nr, err_nr = self._run_cli(
                ["close", "--no-remote-delete", "--repo", str(self.repo), "--session", "conv-123", "--json"]
            )
        self.assertEqual(c_nr, 0, err_nr)
        res_nr = json.loads(out_nr)
        self.assertEqual(res_nr["remote_branch_status"], "skipped")
        self.assertFalse(wt1.exists())
        st = json.loads((self.brain_dir / "scratch" / "worktree.json").read_text(encoding="utf-8"))
        self.assertEqual(st["state"], "exited")

        # 2. already-absent remote branch when unrelated suffix branch refs/heads/team/fix exists (F6!)
        c2, out2, err2 = self._run_cli(["enter", "fix", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(c2, 0, err2)
        wt2 = Path(json.loads(out2)["worktree_path"])
        git(wt2, "push", "origin", "HEAD:refs/heads/team/fix")

        with mock.patch.object(agy_wt, "_cleanup_macos_app_bundles", return_value=[]):
            c_abs, out_abs, err_abs = self._run_cli(["close", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(c_abs, 0, err_abs)
        self.assertEqual(json.loads(out_abs)["remote_branch_status"], "already-absent")

        # 3. Local-only repo without origin remote
        local_repo = self.root / "local-only"
        local_repo.mkdir()
        git(local_repo, "init", "-b", "main")
        git(local_repo, "config", "user.email", "t@e.com")
        git(local_repo, "config", "user.name", "T")
        (local_repo / "x.txt").write_text("x\n", encoding="utf-8")
        git(local_repo, "add", ".")
        git(local_repo, "commit", "-m", "init")
        c3, _, err3 = self._run_cli(["enter", "feat/loc", "--repo", str(local_repo), "--session", "conv-123"])
        self.assertEqual(c3, 0, err3)
        with mock.patch.object(agy_wt, "_cleanup_macos_app_bundles", return_value=[]):
            c_loc, out_loc, err_loc = self._run_cli(["close", "--repo", str(local_repo), "--session", "conv-123", "--json"])
        self.assertEqual(c_loc, 0, err_loc)
        self.assertEqual(json.loads(out_loc)["remote_branch_status"], "no-remote")

    def test_hook_hint_e2e_consumption_ttl_and_atomic_symlink_refusal(self) -> None:
        # Simulate PreToolUse hook firing on `agy-wt enter --repo <repo>` from /tmp (non-git cwd!)
        payload = {
            "conversationId": "conv-123",
            "artifactDirectoryPath": str(self.brain_dir / "artifacts"),
            "transcriptPath": str(self.transcript_full),
            "cwd": "/tmp",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": f"agy-wt enter feat/hint-e2e --repo '{self.repo}'"},
            },
        }
        ok, reason = guard.evaluate_payload(payload, config_path=self.cfg_path)
        self.assertTrue(ok, reason)

        # Invoke agy-wt enter WITHOUT --session -> consumes hook-hint and normalizes /artifacts!
        c1, out1, err1 = self._run_cli(["enter", "feat/hint-e2e", "--repo", str(self.repo), "--json"])
        self.assertEqual(c1, 0, err1)
        res1 = json.loads(out1)
        self.assertTrue(res1["session_bound"])
        self.assertEqual(res1["session_bind_source"], "hook-hint")
        self.assertEqual(Path(res1["state_file"]), self.brain_dir / "scratch" / "worktree.json")

        # Hint was consumed (unlinked) so a second read returns None
        self.assertIsNone(wt_common.read_session_hint(self.repo))

        # Expired hint is ignored
        wt_common.write_session_hint(self.repo, {"conversation_id": "conv-123", "brain_dir": str(self.brain_dir)})
        self.assertIsNone(wt_common.read_session_hint(self.repo, max_age_sec=-1.0))

        # atomic_write_private refuses pre-existing symlink
        victim = self.root / "victim.txt"
        victim.write_text("safe", encoding="utf-8")
        link = self.root / "link.json"
        link.symlink_to(victim)
        with self.assertRaises(OSError):
            wt_common.atomic_write_private(link, "pwned")
        self.assertEqual(victim.read_text(encoding="utf-8"), "safe")

    def test_strict_bare_repo_name_and_macos_app_symlink_guard(self) -> None:
        # Bare repo name in strict_main_repos is recognized by strict add (no dup) & strict remove (F7)
        self.cfg_path.write_text(json.dumps({"strict_main_repos": ["demo-repo"]}), encoding="utf-8")
        c_add, out_add, _ = self._run_cli(["strict", "add", str(self.repo)])
        self.assertEqual(c_add, 0)
        self.assertIn("Already", out_add)

        c_rm, out_rm, _ = self._run_cli(["strict", "remove", str(self.repo)])
        self.assertEqual(c_rm, 0)
        self.assertIn("Removed", out_rm)

        # _find_macos_app_bundles skips symlinked .app and symlinked build/ outside wt_path (F4)
        fake_wt = self.root / "fake-wt"
        (fake_wt / "build" / "Demo.app" / "Contents").mkdir(parents=True)
        outside_app = self.root / "External.app"
        (outside_app / "Contents").mkdir(parents=True)
        (fake_wt / "build" / "Linked.app").symlink_to(outside_app)
        outside_dist = self.root / "outside-dist"
        (outside_dist / "Escaped.app" / "Contents").mkdir(parents=True)
        (fake_wt / "dist").symlink_to(outside_dist)

        found = agy_wt._find_macos_app_bundles(fake_wt)
        self.assertEqual([p.name for p in found], ["Demo.app"])

    def test_round2_cli_regressions_norm_safe_rollback_wt_target_foreachref_and_doctor(self) -> None:
        # R2-1: nested src/build/secrets.env and regular file config/build MUST NOT be treated as safe
        (self.repo / ".gitignore").write_text(
            "build/\ndist/\n__pycache__/\nsrc/build/\nconfig/build\n",
            encoding="utf-8",
        )
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-m", "update gitignore")
        git(self.repo, "push", "origin", "main")

        c1, out1, err1 = self._run_cli(["enter", "feat/r2-safe", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(c1, 0, err1)
        wt1 = Path(json.loads(out1)["worktree_path"])
        (wt1 / "src" / "build").mkdir(parents=True)
        (wt1 / "src" / "build" / "secrets.env").write_text("secret", encoding="utf-8")
        (wt1 / "config").mkdir()
        (wt1 / "config" / "build").write_text("regular-file", encoding="utf-8")
        (wt1 / "pkg" / "__pycache__").mkdir(parents=True)
        (wt1 / "pkg" / "__pycache__" / "m.pyc").write_text("pyc", encoding="utf-8")
        st_info = agy_wt._inspect_worktree_status(wt1, wt_common.DEFAULT_CONFIG["exit"]["ignored_safe_dirs"])
        self.assertTrue(any("src/build" in x for x in st_info["ignored_unsafe"]))
        self.assertTrue(any("config/build" in x for x in st_info["ignored_unsafe"]))
        self.assertTrue(any("__pycache__" in x for x in st_info["ignored_safe"]))
        shutil.rmtree(wt1 / "src")
        shutil.rmtree(wt1 / "config")

        # R2-2: post_create_commands failure after creating untracked file force-rolls back worktree AND branch
        self.cfg_path.write_text(
            json.dumps({"enter": {"post_create_commands": ["touch partial.tmp && exit 1"]}}),
            encoding="utf-8",
        )
        c_rb, _, err_rb = self._run_cli(["enter", "feat/r2-rollback", "--repo", str(self.repo), "--session", "conv-123"])
        self.assertEqual(c_rb, 1)
        self.assertIn("Rolled back newly created worktree and branch", err_rb)
        self.assertFalse((self.root / "demo-repo-worktree" / "demo-repo-feat-r2-rollback").exists())
        self.assertNotIn("feat/r2-rollback", git(self.repo, "branch", "--list").stdout)
        self.cfg_path.unlink()

        # R2-3: exit --remove --repo <wtB> removes wtB (NOT session's active wt1) and keeps wt1 bound!
        c2, out2, err2 = self._run_cli(["enter", "feat/r2-wtb", "--repo", str(self.repo), "--json"])
        self.assertEqual(c2, 0, err2)
        wt_b = Path(json.loads(out2)["worktree_path"])
        with mock.patch.object(agy_wt, "_cleanup_macos_app_bundles", return_value=[]):
            c_rm_b, out_rm_b, err_rm_b = self._run_cli(
                ["exit", "--remove", "--repo", str(wt_b), "--session", "conv-123", "--json"]
            )
        self.assertEqual(c_rm_b, 0, err_rm_b)
        self.assertFalse(wt_b.exists())
        self.assertTrue(wt1.is_dir())
        st_after = json.loads((self.brain_dir / "scratch" / "worktree.json").read_text(encoding="utf-8"))
        self.assertEqual(st_after["state"], "active")
        self.assertEqual(Path(st_after["worktree_path"]), wt1)

        # R2-4: +fix branch coexisting with fix does not break Step 6 for-each-ref verification
        git(self.repo, "branch", "+feat/r2-safe", "main")
        with mock.patch.object(agy_wt, "_cleanup_macos_app_bundles", return_value=[]):
            c_cl, _, err_cl = self._run_cli(["close", "--repo", str(self.repo), "--session", "conv-123", "--json"])
        self.assertEqual(c_cl, 0, err_cl)

        # R2-5: cmd_doctor catches raw strict_main_repos type error & invalid per-repo guard.mode
        self.cfg_path.write_text(
            json.dumps({"strict_main_repos": "~/not-a-list", "repos": {"demo": {"guard": {"mode": "bogus"}}}}),
            encoding="utf-8",
        )
        c_doc, out_doc, _ = self._run_cli(["doctor"])
        self.assertEqual(c_doc, 1)
        self.assertIn("strict_main_repos must be a JSON list", out_doc)
        self.assertIn("repos['demo'].guard.mode='bogus'", out_doc)

        # R2-6: read_transcript_offsets picks up extra_tp even when brain_dir default is absent
        custom_tp = self.root / "custom-logs" / "transcript.jsonl"
        custom_tp.parent.mkdir()
        custom_tp.write_text("hello-watermark\n", encoding="utf-8")
        compat_off, off_map = wt_common.read_transcript_offsets(self.root / "missing-brain", extra_tp=custom_tp)
        self.assertEqual(compat_off, custom_tp.stat().st_size)
        self.assertEqual(off_map.get("transcript.jsonl"), custom_tp.stat().st_size)


if __name__ == "__main__":
    unittest.main()
