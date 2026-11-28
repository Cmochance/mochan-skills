"""Comprehensive, host-isolated unit tests for agy-statusline renderer and CLI."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parent.parent
RENDERER_PATH = SKILL_ROOT / "scripts" / "statusline.py"
PET_PATH = SKILL_ROOT / "scripts" / "pet.py"
CLI_PATH = SKILL_ROOT / "scripts" / "agy-statusline"
AGY_STATS_PATH = SKILL_ROOT.parent / "agy-stats" / "scripts" / "agy-stats"

ISOLATED_ENV_KEYS = (
    "NO_COLOR",
    "AGY_STATUSLINE_CONFIG",
    "AGY_STATUSLINE_NO_SNAPSHOT",
    "AGY_STATUSLINE_DEBUG",
    "AGY_STATUSLINE_PET",
    "AGY_STATUSLINE_PET_FRAME",
    "AGY_DATA_DIR",
    "COLUMNS",
)


def load_module(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


sl = load_module("agy_statusline_renderer_testmod", RENDERER_PATH)
pet = load_module("agy_statusline_pet_testmod", PET_PATH)
cli = load_module("agy_statusline_cli_testmod", CLI_PATH)


def strip_ansi(text: str) -> str:
    return sl.ANSI_RE.sub("", text)


def clean_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ISOLATED_ENV_KEYS}
    if extra:
        env.update(extra)
    return env


class IsolatedTestCase(unittest.TestCase):
    """Base test case isolating host env vars and skill_root/config.local.json."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "agy-data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.fake_skill_root = self.root / "fake-skill"
        self.fake_skill_root.mkdir(parents=True, exist_ok=True)

        clean_env = clean_subprocess_env()
        self._env_patch = mock.patch.dict(os.environ, clean_env, clear=True)
        self._env_patch.start()
        self._sl_root_patch = mock.patch.object(sl, "skill_root", return_value=self.fake_skill_root)
        self._sl_root_patch.start()
        self._cli_sl_root_patch = mock.patch.object(cli.renderer, "skill_root", return_value=self.fake_skill_root)
        self._cli_sl_root_patch.start()
        self._cli_root_patch = mock.patch.object(cli, "SKILL_ROOT", self.fake_skill_root)
        self._cli_root_patch.start()

    def tearDown(self) -> None:
        self._cli_root_patch.stop()
        self._cli_sl_root_patch.stop()
        self._sl_root_patch.stop()
        self._env_patch.stop()
        self.tmp.cleanup()


class StatuslineRendererTest(IsolatedTestCase):
    def test_display_width_cjk_emoji_vs16_zwj_and_nfd_truncation(self) -> None:
        self.assertEqual(sl.display_width("\033[38;5;111mhello\033[0m"), 5)
        self.assertEqual(sl.display_width("中文abc"), 7)
        self.assertEqual(sl.display_width("e\u0301"), 1)
        self.assertEqual(sl.display_width("⚡"), 2)
        self.assertEqual(sl.display_width("⚡89%"), 5)
        self.assertEqual(sl.display_width("中文⚡89%"), 9)
        self.assertEqual(sl.display_width("⚡\ufe0f"), 2)
        self.assertEqual(sl.display_width("1\ufe0f\u20e3"), 1)
        self.assertEqual(sl.display_width("👩‍💻"), 2)

        self.assertEqual(sl.truncate_left_ellipsis("中文目录测试", 7), "…录测试")
        self.assertEqual(sl.truncate_left_ellipsis("中文", 2), "…")
        self.assertEqual(sl.truncate_left_ellipsis("abc", 1), "…")
        self.assertEqual(sl.truncate_left_ellipsis("abc", 0), "")
        # NFD combining mark must never detach onto leading ellipsis
        self.assertEqual(sl.truncate_left_ellipsis("cafe\u0301x", 2), "…x")
        self.assertEqual(sl.truncate_left_ellipsis("xa\u0301bc", 3), "…bc")

    def test_resolve_project_dir_uri_unquote_and_deleted_cwd(self) -> None:
        d = sl.resolve_project_dir({"workspace": {"current_dir": "file:///Users/demo/my%20repo/%E4%B8%AD%E6%96%87"}})
        self.assertEqual(d, "/Users/demo/my repo/中文")
        d2 = sl.resolve_project_dir({"cwd": "file://localhost/tmp/dir#1"})
        self.assertEqual(d2, "/tmp/dir#1")
        with mock.patch("os.getcwd", side_effect=FileNotFoundError("deleted")):
            self.assertEqual(sl.resolve_project_dir({}), "")

    def test_normalize_home_and_shorten_path_options(self) -> None:
        home = str(Path.home())
        self.assertEqual(sl.normalize_home(home), "~")
        self.assertEqual(sl.normalize_home(f"{home}/a/b"), "~/a/b")
        self.assertEqual(sl.normalize_home(f"{home}2/a"), f"{home}2/a")
        self.assertEqual(sl.normalize_home(f"{home}/a", enabled=False), f"{home}/a")
        self.assertEqual(sl.shorten_path("~/alpha/beta/project", 15, abbreviate_parents=True), "~/a/b/project")
        self.assertEqual(sl.shorten_path("~/alpha/beta/project", 15, abbreviate_parents=False), "…/beta/project")

    def test_detect_worktree_main_detached_linked_and_submodule(self) -> None:
        repo = self.root / "main-repo"
        git_dir = repo / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/feat/abc\n", encoding="utf-8")
        sub = repo / "src" / "pkg"
        sub.mkdir(parents=True)
        self.assertEqual(sl.detect_worktree({}, str(sub)), ("feat/abc", False))

        (git_dir / "HEAD").write_text("abcdef1234567890\n", encoding="utf-8")
        self.assertEqual(sl.detect_worktree({}, str(repo)), ("abcdef1", False))

        # Linked worktree with relative gitdir: default label="branch", optional label="name"
        base = self.root / "bare"
        wt_git = base / ".git" / "worktrees" / "wt-alpha"
        wt_git.mkdir(parents=True)
        (wt_git / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
        (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
        wt_dir = self.root / "wt-dir"
        wt_dir.mkdir()
        (wt_dir / ".git").write_text(f"gitdir: {os.path.relpath(wt_git, wt_dir)}\n", encoding="utf-8")
        self.assertEqual(sl.detect_worktree({}, str(wt_dir)), ("topic", True))
        cfg_name = sl._deep_merge(sl.DEFAULT_CONFIG, {"worktree": {"label": "name"}})
        self.assertEqual(sl.detect_worktree({}, str(wt_dir), cfg=cfg_name), ("wt-alpha", True))

        # Submodule inside an ancestor directory literally named "worktrees" must NOT be flagged linked
        sub_parent = self.root / "worktrees" / "projA"
        sub_git = sub_parent / ".git" / "modules" / "libfoo"
        sub_git.mkdir(parents=True)
        (sub_git / "HEAD").write_text("ref: refs/heads/v1\n", encoding="utf-8")
        submod_dir = sub_parent / "libfoo"
        submod_dir.mkdir(parents=True)
        (submod_dir / ".git").write_text(f"gitdir: {os.path.relpath(sub_git, submod_dir)}\n", encoding="utf-8")
        self.assertEqual(sl.detect_worktree({}, str(submod_dir)), ("v1", False))

        # Corrupt .git file with NUL byte must not crash
        corrupt = self.root / "corrupt-repo"
        corrupt.mkdir()
        (corrupt / ".git").write_text("gitdir: bad\x00path\n", encoding="utf-8")
        name, linked = sl.detect_worktree({}, str(corrupt))
        self.assertEqual((name, linked), ("corrupt-repo", False))

    def test_layer1_session_worktree_and_layer2_transcript_probe(self) -> None:
        # Build a main repo + same-repo linked worktree + unrelated repo linked worktree
        main_repo = self.root / "myrepo"
        (main_repo / ".git").mkdir(parents=True)
        (main_repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

        wt_git = main_repo / ".git" / "worktrees" / "myrepo-feat-ui"
        wt_git.mkdir(parents=True)
        (wt_git / "HEAD").write_text("ref: refs/heads/feat/ui\n", encoding="utf-8")
        (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
        wt_dir = self.root / "myrepo-worktree" / "myrepo-feat-ui"
        (wt_dir / "src").mkdir(parents=True)
        (wt_dir / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")

        other_repo = self.root / "other-repo"
        (other_repo / ".git").mkdir(parents=True)
        (other_repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        other_wt_git = other_repo / ".git" / "worktrees" / "other-feat"
        other_wt_git.mkdir(parents=True)
        (other_wt_git / "HEAD").write_text("ref: refs/heads/feat/other\n", encoding="utf-8")
        (other_wt_git / "commondir").write_text("../..\n", encoding="utf-8")
        other_wt_dir = self.root / "other-wt"
        other_wt_dir.mkdir()
        (other_wt_dir / ".git").write_text(f"gitdir: {other_wt_git}\n", encoding="utf-8")

        cid = "test-conv-001"
        brain_conv = self.data_dir / "brain" / cid
        scratch = brain_conv / "scratch"
        logs_dir = brain_conv / ".system_generated" / "logs"
        scratch.mkdir(parents=True)
        logs_dir.mkdir(parents=True)
        transcript = logs_dir / "transcript.jsonl"

        # Layer 1 active worktree.json takes precedence and suppresses main repo's vcs.dirty
        (scratch / "worktree.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "state": "active",
                    "main_dir": str(main_repo),
                    "worktree_path": str(wt_dir),
                    "worktree_name": "myrepo-feat-ui",
                    "branch": "feat/ui",
                }
            ),
            encoding="utf-8",
        )
        payload = {
            "session_id": cid,
            "transcript_path": str(transcript),
            "workspace": {"current_dir": str(main_repo)},
            "vcs": {"branch": "main", "dirty": True},
            "model": {"display_name": "G4"},
            "terminal_width": 120,
        }
        rendered_l1 = strip_ansi(sl.render(payload, config=sl.DEFAULT_CONFIG, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ feat/ui", rendered_l1)
        self.assertNotIn("⎇ ~feat/ui", rendered_l1)
        self.assertNotIn("feat/ui*", rendered_l1)

        # Switching workspace to other_repo rejects myrepo's worktree.json (commondir mismatch)
        payload_other = dict(payload, workspace={"current_dir": str(other_repo)})
        self.assertEqual(sl.detect_worktree(payload_other, str(other_repo), cfg=sl.DEFAULT_CONFIG, data_dir=self.data_dir), ("main", False))

        # Layer 2 transcript probe with real agy double-JSON-encoded tool_calls args
        (scratch / "worktree.json").unlink()
        line1 = json.dumps(
            {
                "step_index": 1,
                "tool_calls": [
                    {"name": "edit_file", "args": {"Path": json.dumps(str(wt_dir / "src" / "app.py"))}},
                    {"name": "read_file", "args": {"Path": json.dumps(str(other_wt_dir / "README.md"))}},
                ],
            }
        )
        transcript.write_text(line1 + "\n", encoding="utf-8")
        rendered_l2 = strip_ansi(sl.render(payload, config=sl.DEFAULT_CONFIG, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ ~feat/ui", rendered_l2)
        self.assertTrue((scratch / "wt_probe_cache.json").is_file())

        # Appending non-tool text preserves previously detected linked worktree via incremental cache
        with open(transcript, "a", encoding="utf-8") as fp:
            fp.write(json.dumps({"step_index": 2, "content": "plain reply"}) + "\n")
        rendered_l2_cached = strip_ansi(sl.render(payload, config=sl.DEFAULT_CONFIG, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ ~feat/ui", rendered_l2_cached)

        # Exited state with exit_transcript_offset blocks re-detecting pre-exit transcript lines
        offset_now = transcript.stat().st_size
        (scratch / "worktree.json").write_text(
            json.dumps({"version": 1, "state": "exited", "exit_transcript_offset": offset_now}),
            encoding="utf-8",
        )
        rendered_exited = strip_ansi(sl.render(payload, config=sl.DEFAULT_CONFIG, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ main*", rendered_exited)
        self.assertNotIn("feat/ui", rendered_exited)

        # New tool call AFTER exit_transcript_offset IS detected on exact line boundary
        with open(transcript, "a", encoding="utf-8") as fp:
            fp.write(
                json.dumps(
                    {
                        "step_index": 3,
                        "tool_calls": [
                            {"name": "run_command", "args": {"CommandLine": json.dumps(f"git -C '{wt_dir}' status")}}
                        ],
                    }
                )
                + "\n"
            )
        rendered_reentered = strip_ansi(sl.render(payload, config=sl.DEFAULT_CONFIG, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ ~feat/ui", rendered_reentered)

        # Disabling auto_detect_from_transcript suppresses Layer 2
        cfg_no_auto = sl._deep_merge(sl.DEFAULT_CONFIG, {"worktree": {"auto_detect_from_transcript": False}})
        rendered_no_auto = strip_ansi(sl.render(payload, config=cfg_no_auto, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ main*", rendered_no_auto)

        # Deleting worktree directory clears stale Layer 2 detection immediately
        import shutil

        shutil.rmtree(wt_dir)
        rendered_deleted = strip_ansi(sl.render(payload, config=sl.DEFAULT_CONFIG, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ main*", rendered_deleted)

    def test_layer2_partial_line_over_64kb_switch_dual_watermarks_and_edge_cases(self) -> None:
        main_repo = self.root / "bigrepo"
        (main_repo / ".git").mkdir(parents=True)
        (main_repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

        def make_wt(wt_name: str, branch: str, folder: str) -> Path:
            wt_git = main_repo / ".git" / "worktrees" / wt_name
            wt_git.mkdir(parents=True)
            (wt_git / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
            (wt_git / "commondir").write_text("../..\n", encoding="utf-8")
            wt_d = self.root / folder
            (wt_d / "src").mkdir(parents=True)
            (wt_d / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")
            return wt_d

        wt_a = make_wt("bigrepo-feat-a", "feat/a", "bigrepo-worktree/wt-a")
        wt_b = make_wt("bigrepo-feat-b", "feat/b", "bigrepo-worktree/it's wt-b")

        cid = "conv-edge-1"
        brain_conv = self.data_dir / "brain" / cid
        scratch = brain_conv / "scratch"
        logs_dir = brain_conv / ".system_generated" / "logs"
        scratch.mkdir(parents=True)
        logs_dir.mkdir(parents=True)
        transcript = logs_dir / "transcript.jsonl"
        transcript_full = logs_dir / "transcript_full.jsonl"

        payload = {
            "artifactDirectoryPath": str(brain_conv / "artifacts"),
            "transcript_path": str(transcript_full),  # statusline prefers compact transcript.jsonl sibling
            "workspace": {"current_dir": str(main_repo)},
            "model": {"display_name": "G4"},
            "terminal_width": 120,
        }

        # 1. Partial non-newline-terminated JSONL line must NOT be dropped on next render (F17)
        full_line_a = json.dumps(
            {"step_index": 1, "tool_calls": [{"name": "edit_file", "args": {"Path": json.dumps(str(wt_a / "src" / "x.py"))}}]}
        ) + "\n"
        transcript.write_bytes(full_line_a[:40].encode("utf-8"))
        transcript_full.write_text("x" * 1000 + "\n", encoding="utf-8")
        self.assertEqual(sl.detect_worktree(payload, str(main_repo), cfg=sl.DEFAULT_CONFIG, data_dir=self.data_dir), ("main", False))
        # Now flush remainder of line
        transcript.write_bytes(full_line_a.encode("utf-8"))
        self.assertEqual(sl.detect_worktree(payload, str(main_repo), cfg=sl.DEFAULT_CONFIG, data_dir=self.data_dir), ("feat/a", True))

        # 2. label="name" and auto_prefix="" in Layer 2 (including cache hit)
        cfg_name_nopfx = sl._deep_merge(sl.DEFAULT_CONFIG, {"worktree": {"label": "name", "auto_prefix": ""}})
        rendered_np = strip_ansi(sl.render(payload, config=cfg_name_nopfx, settings={}, data_dir=self.data_dir))
        self.assertIn("⎇ bigrepo-feat-a", rendered_np)
        self.assertNotIn("~bigrepo-feat-a", rendered_np)

        # 3. >64KB mid-line seek + worktree A -> worktree B switch + shell path regex edge cases (F18, T5)
        padding_line = json.dumps({"step_index": 2, "content": "p" * 70_000}) + "\n"
        switch_line = json.dumps(
            {
                "step_index": 3,
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": f'git -C "{wt_b}" status && cd {wt_a}&& true'}}
                ],
            }
        ) + "\n"
        with open(transcript, "a", encoding="utf-8") as fp:
            fp.write(padding_line)
            fp.write(switch_line)
        # Reversed path extraction inspects wt_a first? Check that wt_b (apostrophe + spaces in double quotes) is extracted cleanly!
        cands = sl._extract_candidate_paths_from_tool_call(
            {"name": "run_command", "args": {"CommandLine": f'git -C "{wt_b}" status'}}
        )
        self.assertIn(str(wt_b), cands)
        self.assertIn(str(wt_a), sl._extract_candidate_paths_from_tool_call({"name": "run_command", "args": {"CommandLine": f"cd {wt_a}&& make"}}))
        self.assertIn(str(wt_a), sl._extract_candidate_paths_from_tool_call({"name": "run_command", "args": {"CommandLine": f"git -C{wt_a} status"}}))
        self.assertIn(str(wt_a), sl._extract_candidate_paths_from_tool_call({"name": "run_command", "args": {"CommandLine": f"PATH={wt_a}:/usr/bin make"}}))
        self.assertIn(str(wt_b / "run.sh"), sl._extract_candidate_paths_from_tool_call({"name": "run_command", "args": {"CommandLine": f'"{wt_b}/run.sh"'}}))

        # Append a clean wt_b-only tool call past >64KB padding and verify A -> B switch
        with open(transcript, "a", encoding="utf-8") as fp:
            fp.write(
                json.dumps(
                    {"step_index": 4, "tool_calls": [{"name": "run_command", "args": {"CommandLine": f'git -C "{wt_b}" status'}}]}
                )
                + "\n"
            )
        self.assertEqual(sl.detect_worktree(payload, str(main_repo), cfg=sl.DEFAULT_CONFIG, data_dir=self.data_dir), ("feat/b", True))

        # 4. Dual per-file exit_transcript_offsets: transcript_full.jsonl offset > transcript.jsonl size MUST NOT blind Layer 2 (F15!)
        (scratch / "worktree.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "state": "exited",
                    "common_dir": str(main_repo / ".git"),
                    "exit_transcript_offset": transcript.stat().st_size,
                    "exit_transcript_offsets": {
                        "transcript.jsonl": transcript.stat().st_size,
                        "transcript_full.jsonl": transcript.stat().st_size * 5,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(sl.detect_worktree(payload, str(main_repo), cfg=sl.DEFAULT_CONFIG, data_dir=self.data_dir), ("main", False))
        # Append 1 tiny line to transcript.jsonl -> immediately detected because compact watermark is matched!
        with open(transcript, "a", encoding="utf-8") as fp:
            fp.write(
                json.dumps({"step_index": 5, "tool_calls": [{"name": "edit_file", "args": {"Path": json.dumps(str(wt_a / "src" / "y.py"))}}]})
                + "\n"
            )
        self.assertEqual(sl.detect_worktree(payload, str(main_repo), cfg=sl.DEFAULT_CONFIG, data_dir=self.data_dir), ("feat/a", True))

        # 5. Cross-repo exited watermark does NOT suppress another repo (F19e)
        other_repo = self.root / "other2"
        (other_repo / ".git").mkdir(parents=True)
        (other_repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        _, wm = sl._load_session_worktree(scratch, other_repo / ".git", "branch", transcript)
        self.assertEqual(wm, 0)

        # 6. NUL bytes in current_dir or transcript_path never crash (F19a)
        bad_payload = {"workspace": {"current_dir": "/tmp/bad\x00dir/sub"}, "transcript_path": "/tmp/bad\x00.jsonl", "terminal_width": 80}
        out_bad = sl.render(bad_payload, config=sl.DEFAULT_CONFIG, settings={}, data_dir=self.data_dir, no_pet=True)
        self.assertNotIn("\n", out_bad)

        # 7. Symlinked main repo path resolves Layer 1 cleanly
        repo_sym = self.root / "bigrepo-link"
        repo_sym.symlink_to(main_repo)
        (scratch / "worktree.json").write_text(
            json.dumps({"version": 1, "state": "active", "main_dir": str(main_repo), "worktree_path": str(wt_a), "branch": "feat/a"}),
            encoding="utf-8",
        )
        sym_payload = dict(payload, workspace={"current_dir": str(repo_sym)})
        self.assertEqual(sl.detect_worktree(sym_payload, str(repo_sym), cfg=sl.DEFAULT_CONFIG, data_dir=self.data_dir), ("feat/a", True))

        # 8. Round-2 fixes: watermark non-leakage, 0-byte compact fallback, and escaped/compound command paths
        self.assertEqual(
            sl._resolve_exit_watermark(
                {"exit_transcript_offset": 50_000, "exit_transcript_offsets": {"transcript_full.jsonl": 50_000}},
                transcript,
            ),
            0,
        )
        # Empty compact transcript.jsonl falls back to non-empty transcript_full.jsonl
        empty_logs = self.root / "empty-logs"
        empty_logs.mkdir()
        (empty_logs / "transcript.jsonl").write_text("", encoding="utf-8")
        (empty_logs / "transcript_full.jsonl").write_text('{"step_index":0}\n', encoding="utf-8")
        self.assertEqual(sl._select_preferred_transcript(empty_logs).name, "transcript_full.jsonl")

        # Nested escaped quotes, compound quoted cmd starting with '/', and backslash-escaped space
        self.assertIn(
            str(wt_a),
            sl._extract_candidate_paths_from_tool_call(
                {"name": "run_command", "args": {"CommandLine": f'sh -c "git -C \\"{wt_a}\\" status"'}}
            ),
        )
        self.assertIn(
            str(wt_a),
            sl._extract_candidate_paths_from_tool_call(
                {"name": "run_command", "args": {"CommandLine": f'bash -c "/bin/echo hi && cd {wt_a} && make"'}}
            ),
        )
        escaped_space_wt = str(wt_b).replace("'", "\\'").replace(" ", "\\ ")
        self.assertIn(
            str(wt_b),
            sl._extract_candidate_paths_from_tool_call(
                {"name": "run_command", "args": {"CommandLine": f"cd {escaped_space_wt} && make"}}
            ),
        )

    def test_permission_cycle_mode_default_fallback_and_colors(self) -> None:
        cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {})
        pal = sl.build_palette(cfg)

        p_plan = sl.format_permission({"cycle_mode": "plan"}, {}, cfg, pal)
        self.assertEqual(strip_ansi(p_plan), "plan")
        self.assertIn(pal["sky"], p_plan)

        p_edits = sl.format_permission({"cycle_mode": "accept-edits"}, {}, cfg, pal)
        self.assertEqual(strip_ansi(p_edits), "accept-edits")
        self.assertIn(pal["yellow"], p_edits)

        p_auto = sl.format_permission({"cycle_mode": "auto"}, {}, cfg, pal)
        self.assertEqual(strip_ansi(p_auto), "auto")
        self.assertIn(pal["amber"], p_auto)

        p_sandbox = sl.format_permission({"sandbox": {"enabled": True}}, {}, cfg, pal)
        self.assertEqual(strip_ansi(p_sandbox), "sandbox")
        self.assertIn(pal["green"], p_sandbox)

        p_settings = sl.format_permission({}, {"agentMode": "ask"}, cfg, pal)
        self.assertEqual(strip_ansi(p_settings), "ask")
        self.assertIn(pal["green"], p_settings)

        # Omitted cycle_mode defaults safely to "default" in green (not amber "auto")
        p_def = sl.format_permission({}, {}, cfg, pal)
        self.assertEqual(strip_ansi(p_def), "default")
        self.assertIn(pal["green"], p_def)

    def test_model_name_effort_and_settings_fallback(self) -> None:
        self.assertEqual(
            sl.resolve_model_name({"model": {"id": "gemini-4-neon", "display_name": "Gemini 4 Neon", "effort": "high"}}, {}),
            "Gemini 4 Neon (high)",
        )
        # Do not duplicate effort when display_name already contains it
        self.assertEqual(
            sl.resolve_model_name({"model": {"display_name": "Gemini 4 Neon (XHigh)", "effort": "xhigh"}}, {}),
            "Gemini 4 Neon (XHigh)",
        )
        # Explicit "model": null falls back to settings.json (real agy emits null before model load)
        self.assertEqual(sl.resolve_model_name({"model": None}, {"model": "Gemini 4 Carbon"}), "Gemini 4 Carbon")
        self.assertEqual(sl.resolve_model_name({"model": None}, {}), "--")

    def test_context_window_variants_aliases_and_no_cumulative_fallback(self) -> None:
        cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {})
        pal = sl.build_palette(cfg)

        out1 = sl.format_context_window({"context_window": {"used_tokens": 109_000, "context_window_size": 1_048_576}}, cfg, pal)
        self.assertEqual(strip_ansi(out1), "109k/1M")
        self.assertIn(pal["teal"], out1)

        # Supports both cache_read_input_tokens and cache_read_tokens aliases
        out2 = sl.format_context_window(
            {"context_window": {"current_usage": {"input_tokens": 650_000, "cache_read_tokens": 50_000}, "max_tokens": 1_000_000}},
            cfg,
            pal,
        )
        self.assertEqual(strip_ansi(out2), "700k/1M")
        self.assertIn(pal["amber"], out2)

        # Zeroed current_usage defers to non-zero used_percentage (never contradictory red 0/1M)
        out3 = sl.format_context_window(
            {"context_window": {"context_window_size": 1_000_000, "used_percentage": 88, "current_usage": {"input_tokens": 0, "cache_read_input_tokens": 0}}},
            cfg,
            pal,
        )
        self.assertEqual(strip_ansi(out3), "880k/1M")
        self.assertIn(pal["red"], out3)

        # Cumulative total_input_tokens must NOT be displayed as current occupancy
        out4 = sl.format_context_window(
            {"context_window": {"context_window_size": 1_000_000, "total_input_tokens": 2_500_000}},
            cfg,
            pal,
        )
        self.assertEqual(strip_ansi(out4), "--")

        # format_tokens boundary 999_500 -> "1M" (not "1000k")
        self.assertEqual(sl.format_tokens(999_500), "1M")
        self.assertEqual(sl.format_tokens(1_048_576), "1M")
        self.assertEqual(sl.format_tokens(1_500_000), "1.5M")
        self.assertEqual(sl.format_tokens(45_200), "45.2k")
        self.assertEqual(sl.format_tokens(0), "0")

    def test_cache_hit_rates_colors_styles_and_placement(self) -> None:
        cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {})
        pal = sl.build_palette(cfg)

        hi = sl.format_cache_hit(
            {"context_window": {"current_usage": {"input_tokens": 12_000, "cache_read_input_tokens": 97_000, "cache_creation_input_tokens": 0}}},
            cfg,
            pal,
        )
        self.assertEqual(strip_ansi(hi), "⚡89%")
        self.assertIn(pal["green"], hi)

        mid = sl.format_cache_hit(
            {"context_window": {"current_usage": {"input_tokens": 30_000, "cache_creation_input_tokens": 20_000, "cache_read_input_tokens": 50_000}}},
            cfg,
            pal,
        )
        self.assertEqual(strip_ansi(mid), "⚡50%")
        self.assertIn(pal["amber"], mid)

        # cache_creation-only turn produces ⚡0% (not ⚡--)
        create_only = sl.format_cache_hit(
            {"context_window": {"current_usage": {"cache_creation_input_tokens": 5_000}}},
            cfg,
            pal,
        )
        self.assertEqual(strip_ansi(create_only), "⚡0%")
        self.assertIn(pal["muted"], create_only)

        # total_in == 0 -> ⚡--
        empty_zero = sl.format_cache_hit(
            {"context_window": {"current_usage": {"input_tokens": 0, "cache_read_input_tokens": 0}}},
            cfg,
            pal,
        )
        self.assertEqual(strip_ansi(empty_zero), "⚡--")

        cfg_hide = sl._deep_merge(sl.DEFAULT_CONFIG, {"cache": {"hide_when_empty": True}})
        self.assertEqual(sl.format_cache_hit({}, cfg_hide, pal), "")

        cfg_tok = sl._deep_merge(sl.DEFAULT_CONFIG, {"cache": {"icon": "c:", "style": "tokens"}})
        self.assertEqual(
            strip_ansi(sl.format_cache_hit({"context_window": {"current_usage": {"input_tokens": 10_000, "cache_read_tokens": 90_000}}}, cfg_tok, pal)),
            "c:90k",
        )
        cfg_both = sl._deep_merge(sl.DEFAULT_CONFIG, {"cache": {"style": "both"}})
        self.assertEqual(
            strip_ansi(sl.format_cache_hit({"context_window": {"current_usage": {"input_tokens": 10_000, "cache_read_input_tokens": 90_000}}}, cfg_both, pal)),
            "⚡90%(90k)",
        )
        self.assertEqual(strip_ansi(sl.format_cache_hit({"context_window": {"cache_hit_percentage": 75}}, cfg_both, pal)), "⚡75%")

        rendered = strip_ansi(
            sl.render(
                {
                    "workspace": {"current_dir": "/tmp/demo"},
                    "cycle_mode": "auto",
                    "model": {"display_name": "Gemini 4 Neon"},
                    "context_window": {
                        "context_window_size": 1_048_576,
                        "current_usage": {"input_tokens": 12_000, "cache_read_input_tokens": 97_000},
                    },
                    "quota": {"gemini-5h": {"remaining_fraction": 0.94}},
                    "terminal_width": 110,
                },
                config=sl.DEFAULT_CONFIG,
                settings={},
                data_dir=self.data_dir,
            )
        )
        self.assertIn("109k/1M · ⚡89% · 94%", rendered)

    def test_quota_variants_disabled_remaining_amount_and_countdown(self) -> None:
        cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {})
        pal = sl.build_palette(cfg)

        # Disabled bucket must be ignored even if remaining_fraction=0
        quota_payload = {
            "quota": {
                "gemini-disabled": {"remaining_fraction": 0.0, "disabled": True},
                "gemini-weekly": {"remaining_fraction": 0.66, "reset_in_seconds": 400000},
                "gemini-5h": {"remaining_fraction": 0.15, "reset_in_seconds": 5400},
                "3p-5h": {"remaining_fraction": 0.90, "reset_in_seconds": 10000},
                "3p-weekly": {"remaining_fraction": 0.80, "reset_in_seconds": 200000},
            }
        }
        g_out = sl.format_quota_or_credits(quota_payload, "Gemini 4 Neon (XHigh)", cfg, pal)
        self.assertEqual(strip_ansi(g_out), "5h 15%(1h30m) · 7d 66%")
        self.assertIn(pal["red"], g_out)

        c_out = sl.format_quota_or_credits(quota_payload, "Claude Opus 4.6", cfg, pal)
        self.assertEqual(strip_ansi(c_out), "5h 90% · 7d 80%")
        self.assertIn(pal["green"], c_out)

        # Unknown model "--" must NOT filter out 3p buckets
        unk_out = sl.format_quota_or_credits(
            {"quota": {"gemini-5h": {"remaining_fraction": 0.9}, "3p-5h": {"remaining_fraction": 0.4}}},
            "--",
            cfg,
            pal,
        )
        self.assertIn("90%", strip_ansi(unk_out))
        self.assertIn("40%", strip_ansi(unk_out))

        # List-shaped quota + argon sorting (5h -> 7d -> argon -> custom)
        list_q = {
            "quota": [
                {"id": "custom-bucket", "remaining_percentage": 80},
                {"name": "gemini-argon", "remaining_fraction": 0.70},
                {"bucket": "gemini-weekly", "remaining_fraction": 0.60},
                {"name": "gemini-5h", "remaining_fraction": 0.55},
            ]
        }
        cfg_nofilter = sl._deep_merge(sl.DEFAULT_CONFIG, {"quota": {"filter_by_model": False}})
        self.assertEqual(
            strip_ansi(sl.format_quota_or_credits(list_q, "Gemini 4 Neon", cfg_nofilter, pal)),
            "5h 55% · 7d 60% · argon 70% · custom-bucket 80%",
        )

        # Single flat bucket dict + amber
        single_out = sl.format_quota_or_credits({"quota": {"remaining_percentage": 45}}, "Gemini 4", cfg, pal)
        self.assertEqual(strip_ansi(single_out), "45%")
        self.assertIn(pal["amber"], single_out)

        # remaining_amount bucket (positive green & exhausted red)
        amt_ok = sl.format_quota_or_credits({"quota": {"g1-credits": {"remaining_amount": 500}}}, "Gemini 4", cfg, pal)
        self.assertEqual(strip_ansi(amt_ok), "g1-credits 500")
        self.assertIn(pal["green"], amt_ok)
        amt_zero = sl.format_quota_or_credits({"quota": {"g1-credits": {"remaining_amount": 0, "reset_in_seconds": 3600}}}, "Gemini 4", cfg, pal)
        self.assertEqual(strip_ansi(amt_zero), "g1-credits 0(1h)")
        self.assertIn(pal["red"], amt_zero)

        # format_countdown units & guards
        self.assertEqual(sl.format_countdown(86400), "1d")
        self.assertEqual(sl.format_countdown(90000), "1d1h")
        self.assertEqual(sl.format_countdown(3600), "1h")
        self.assertEqual(sl.format_countdown(5400), "1h30m")
        self.assertEqual(sl.format_countdown(1800), "30m")
        self.assertEqual(sl.format_countdown(10), "1m")
        for bad in (0, -5, None, True, "60", float("nan"), float("inf")):
            self.assertEqual(sl.format_countdown(bad), "")

    def test_non_finite_floats_and_bool_guards_never_crash(self) -> None:
        cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {"layout": {"right_margin": float("nan"), "min_gap": float("inf")}})
        pal = sl.build_palette(cfg)
        self.assertEqual(sl.extract_pct({"remaining_fraction": float("nan")}), None)
        self.assertEqual(sl.extract_pct({"remaining_percentage": float("inf")}), None)
        self.assertEqual(strip_ansi(sl.format_quota_or_credits({"credits": float("nan")}, "G4", cfg, pal)), "--")
        self.assertEqual(
            strip_ansi(sl.format_context_window({"context_window": {"context_window_size": float("inf"), "used_tokens": 100}}, cfg, pal)),
            "--",
        )
        self.assertEqual(
            strip_ansi(sl.format_context_window({"context_window": {"context_window_size": 1000, "used_percentage": float("nan")}}, cfg, pal)),
            "--",
        )
        self.assertEqual(sl.format_tokens(float("nan")), "0")
        out = sl.render({"terminal_width": float("inf"), "workspace": {"current_dir": "/tmp/demo"}}, config=cfg, settings={}, no_pet=True)
        self.assertNotIn("\n", out)
        out_bool = sl.render({"terminal_width": True, "workspace": {"current_dir": "/tmp/demo"}}, config=sl.DEFAULT_CONFIG, settings={})
        self.assertGreater(sl.display_width(out_bool.splitlines()[-1]), 10)  # bool ignored -> falls back to 100, not 1

    def test_sanitization_blocks_newlines_and_terminal_escapes(self) -> None:
        cfg = sl._deep_merge(
            sl.DEFAULT_CONFIG,
            {
                "separator": " \n· ",
                "colors": {"path": "\x1b]0;pwn\x07\x1b[31m", "model": "\033[38;5;250m"},
                "pet": {"name": "mochi\x1b]0;pwn\x07\nline2"},
            },
        )
        payload = {
            "workspace": {"current_dir": "file:///tmp/repo%0Ainjected%1B%5D0%3Bpwn%07"},
            "vcs": {"branch": "feat/\x9b31mred\x1b]52;c;ZGF0YQ==\x07\nline2"},
            "model": "G4\r\x1b[2Kfake",
            "credits": "100\t\x1b]8;;https://evil\x07click\x1b]8;;\x07",
            "terminal_width": 140,
        }
        out_single = sl.render(payload, config=cfg, settings={}, data_dir=self.data_dir, no_pet=True)
        self.assertNotIn("\n", out_single)
        out = sl.render(payload, config=cfg, settings={}, data_dir=self.data_dir)
        self.assertEqual(len(out.splitlines()), 6)
        self.assertNotIn("\r", out)
        self.assertNotIn("\t", out)
        self.assertNotIn("\x1b]", out)
        self.assertNotIn("\x9b", out)
        self.assertNotIn("\x07", out)

    def test_narrow_width_never_overflows_including_cjk_emoji_and_extreme_widths(self) -> None:
        payloads = [
            {
                "workspace": {"current_dir": "/Users/demo/extremely/deeply/nested/project/directory/mochan-skills"},
                "worktree": {"name": "feature/very-long-worktree-branch-name"},
                "vcs": {"dirty": True},
                "cycle_mode": "auto",
                "agent_state": "tool_use",
                "subagents": [{"name": "r", "status": "running"}],
                "model": {"display_name": "Gemini 4 Neon (XHigh)"},
                "context_window": {
                    "context_window_size": 1_048_576,
                    "current_usage": {"input_tokens": 12_000, "cache_read_input_tokens": 97_000},
                },
                "quota": {"gemini-5h": {"remaining_fraction": 0.88}, "gemini-weekly": {"remaining_fraction": 0.61}},
            },
            {
                "workspace": {"current_dir": "/Users/demo/项目/中文目录/中文工程名"},
                "vcs": {"branch": "功能/状态栏", "dirty": True},
                "cycle_mode": "plan",
                "agent_state": "working",
                "model": {"display_name": "Gemini 4 Neon"},
                "context_window": {
                    "context_window_size": 1_048_576,
                    "current_usage": {"input_tokens": 10_000, "cache_read_input_tokens": 90_000},
                },
                "quota": {"gemini-5h": {"remaining_fraction": 0.91}},
            },
            # Non-git directory
            {"workspace": {"current_dir": "/tmp/myproject"}, "cycle_mode": "auto", "model": "G4"},
        ]
        cfgs = [
            sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"enabled": False}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"enabled": True, "style": "pixel", "align": "right", "name": "墨酱小紫猫超长名字测试"}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"enabled": True, "style": "pixel", "align": "left", "species": "prism", "name": "墨酱小紫猫超长名字测试"}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"enabled": True, "style": "ascii", "align": "right"}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"enabled": True, "style": "inline", "align": "right"}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"enabled": True, "style": "inline", "align": "left"}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": ["worktree"], "pet": {"enabled": False}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": ["worktree", "path"], "worktree": {"icon": "🌿"}, "pet": {"enabled": False}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"layout": {"right_margin": 0}, "pet": {"enabled": False}}),
        ]
        for cfg in cfgs:
            pet_enabled = cfg["pet"]["enabled"]
            pet_style = cfg["pet"]["style"]
            for base in payloads:
                for width in (140, 100, 84, 64, 48, 30, 24, 20, 19, 16, 12, 5, 4, 2, 1):
                    p = dict(base, terminal_width=width)
                    out = sl.render(p, config=cfg, settings={}, data_dir=self.data_dir)
                    lines = out.splitlines()
                    if not pet_enabled or pet_style == "inline" or width < 20:
                        self.assertEqual(len(lines), 1, f"expected single line at w={width}: {out!r}")
                    else:
                        self.assertEqual(len(lines), 6, f"expected 6 lines at w={width}: {out!r}")
                    for ln in lines:
                        self.assertLessEqual(sl.display_width(ln), width, f"overflowed at w={width}: {strip_ansi(ln)!r}")

    def test_left_right_segment_layout_variants_and_terminal_width_fallbacks(self) -> None:
        base = {
            "workspace": {"current_dir": "/tmp/demo"},
            "worktree": {"name": "wt-1"},
            "cycle_mode": "plan",
            "model": {"display_name": "G4"},
            "terminal_width": 60,
        }
        # Reversed left segments
        rev = strip_ansi(sl.render(base, config=sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": ["worktree", "path"]}), settings={}, no_pet=True))
        self.assertTrue(rev.startswith("⎇ wt-1 /tmp/demo"))

        # Empty left -> right aligned
        r_only = strip_ansi(sl.render(base, config=sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": []}), settings={}, no_pet=True))
        self.assertTrue(r_only.startswith(" "))
        self.assertIn("plan · G4", r_only)

        # Empty right -> left only
        l_only = strip_ansi(sl.render(base, config=sl._deep_merge(sl.DEFAULT_CONFIG, {"right_segments": []}), settings={}, no_pet=True))
        self.assertEqual(l_only, "/tmp/demo ⎇ wt-1")

        # Both empty -> "" when pet off; 5 pet rows when pet on
        empty_cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": [], "right_segments": []})
        self.assertEqual(sl.render(base, config=empty_cfg, settings={}, no_pet=True), "")
        self.assertEqual(len(sl.render(base, config=empty_cfg, settings={}).splitlines()), 5)

        # COLUMNS env fallback & 0-col PTY fallback
        with mock.patch.dict(os.environ, {"COLUMNS": "72"}):
            self.assertEqual(sl.resolve_terminal_width({}), 72)
        with mock.patch("os.get_terminal_size", return_value=os.terminal_size((0, 24))):
            self.assertEqual(sl.resolve_terminal_width({"terminal_width": "bad"}), 100)

    def test_config_precedence_deep_clone_and_palette_guards(self) -> None:
        # Deep merge must not alias DEFAULT_CONFIG nested dicts/lists
        cfg = sl.load_config(data_dir=self.data_dir)
        cfg["colors"]["path"] = 99
        cfg["left_segments"].append("extra")
        self.assertEqual(sl.DEFAULT_CONFIG["colors"], {})
        self.assertEqual(sl.DEFAULT_CONFIG["left_segments"], ["path", "worktree"])

        # Precedence: AGY_STATUSLINE_CONFIG > config.local.json > <data_dir>/statusline.json > defaults
        global_cfg = self.data_dir / "statusline.json"
        global_cfg.write_text(json.dumps({"theme": "minimal", "separator": " / "}), encoding="utf-8")
        self.assertEqual(sl.resolve_config_path(self.data_dir), global_cfg)
        self.assertEqual(sl.load_config(self.data_dir)["separator"], " / ")

        local_cfg = self.fake_skill_root / "config.local.json"
        local_cfg.write_text(json.dumps({"separator": " | "}), encoding="utf-8")
        self.assertEqual(sl.resolve_config_path(self.data_dir), local_cfg)
        self.assertEqual(sl.load_config(self.data_dir)["separator"], " | ")

        env_cfg = self.root / "env_cfg.json"
        env_cfg.write_text(json.dumps({"separator": " :: "}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_CONFIG": str(env_cfg)}):
            self.assertEqual(sl.resolve_config_path(self.data_dir), env_cfg)
            self.assertEqual(sl.load_config(self.data_dir)["separator"], " :: ")

        # Malformed JSON falls back cleanly to defaults
        local_cfg.write_text("{broken", encoding="utf-8")
        self.assertEqual(sl.load_config(self.data_dir)["separator"], " · ")

        # Palette normalization guards
        pal = sl.build_palette(
            {"theme": "Tokyo-Night", "colors": {"path": 117, "model": True, "sep": 300, "reset": "BAD", "amber": "not-sgr"}}
        )
        self.assertEqual(pal["path"], "\033[38;5;117m")
        self.assertEqual(pal["reset"], sl.RESET)
        self.assertEqual(pal["amber"], sl.THEMES["tokyo-night"]["amber"])
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(sl.build_palette(sl.DEFAULT_CONFIG)["path"], "")

    def test_quota_snapshot_atomic_0600_guard_and_agy_stats_compat(self) -> None:
        payload = {
            "quota": {
                "gemini-5h": {"remaining_fraction": 0.92, "reset_in_seconds": 12000},
                "gemini-weekly": {"remaining_fraction": 0.71, "reset_in_seconds": 360000},
                "gemini-disabled": {"remaining_fraction": 0.0, "disabled": True},
                "g1-credits": {"remaining_amount": 250},
            }
        }
        sl.write_quota_snapshot(payload, data_dir=self.data_dir, cfg=sl.DEFAULT_CONFIG)
        snap_path = self.data_dir / "cache" / "quota_snapshot.json"
        self.assertTrue(snap_path.is_file())
        self.assertEqual(stat.S_IMODE(snap_path.stat().st_mode), 0o600)

        # Unusable / all-disabled quota must NOT clobber existing valid snapshot
        before = snap_path.read_text(encoding="utf-8")
        sl.write_quota_snapshot({"quota": {"error": "unavailable"}}, data_dir=self.data_dir, cfg=sl.DEFAULT_CONFIG)
        sl.write_quota_snapshot({"quota": {"x": {"remaining_fraction": 0.5, "disabled": True}}}, data_dir=self.data_dir, cfg=sl.DEFAULT_CONFIG)
        self.assertEqual(snap_path.read_text(encoding="utf-8"), before)

        if AGY_STATS_PATH.is_file():
            stats_mod = load_module("agy_stats_compat_mod", AGY_STATS_PATH)
            loaded = stats_mod.load_quota_snapshot(self.data_dir)
            self.assertIsNotNone(loaded)
            rendered = [stats_mod.strip_ansi(line) for line in stats_mod.render_quota_section(loaded, effective_w=80)]
            self.assertTrue(any("gemini-5h" in line for line in rendered))
            self.assertTrue(any("g1-credits" in line and "250" in line for line in rendered))
            self.assertFalse(any("gemini-disabled" in line for line in rendered))

        # Respect AGY_STATUSLINE_NO_SNAPSHOT=1 and write_snapshot=False
        snap_path.unlink()
        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_NO_SNAPSHOT": "1"}):
            sl.write_quota_snapshot(payload, data_dir=self.data_dir, cfg=sl.DEFAULT_CONFIG)
        self.assertFalse(snap_path.exists())
        sl.write_quota_snapshot(payload, data_dir=self.data_dir, cfg={"quota": {"write_snapshot": False}})
        self.assertFalse(snap_path.exists())

    def test_debug_dump_atomic_0600_refuses_symlinks_and_disabled_flags(self) -> None:
        dump_file = self.root / "debug.json"
        # Pre-existing 0644 file must be atomically replaced with 0600
        dump_file.write_text("old", encoding="utf-8")
        os.chmod(dump_file, 0o644)
        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_DEBUG": str(dump_file)}):
            sl.write_debug_dump('{"hello":"world"}')
        self.assertEqual(dump_file.read_text(encoding="utf-8"), '{"hello":"world"}')
        self.assertEqual(stat.S_IMODE(dump_file.stat().st_mode), 0o600)

        # Refuses pre-planted symlink
        victim = self.root / "victim.txt"
        victim.write_text("untouched", encoding="utf-8")
        sym = self.root / "debug-link.json"
        sym.symlink_to(victim)
        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_DEBUG": str(sym)}):
            sl.write_debug_dump("pwned")
        self.assertEqual(victim.read_text(encoding="utf-8"), "untouched")

        # Explicit disable flags do not create a file named "0" or "false"
        for off in ("0", "false", "no"):
            with mock.patch.dict(os.environ, {"AGY_STATUSLINE_DEBUG": off}):
                sl.write_debug_dump("nope")
            self.assertFalse(Path(off).exists())


class StatuslineCliTest(IsolatedTestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_install_preserves_0600_extra_statusline_keys_symlinks_and_prior_bak(self) -> None:
        real_settings = self.root / "dotfiles" / "settings.json"
        real_settings.parent.mkdir(parents=True)
        original = {
            "colorScheme": "tokyo night",
            "model": "Gemini 4 Neon (XHigh)",
            "statusLine": {"type": "command", "command": "old.py", "enabled": False, "padding": 1, "stack_with_default": True},
            "trustedWorkspaces": ["/tmp/a"],
        }
        real_settings.write_text(json.dumps(original, indent=2), encoding="utf-8")
        os.chmod(real_settings, 0o600)

        settings_link = self.data_dir / "settings.json"
        settings_link.symlink_to(real_settings)
        legacy = self.data_dir / "statusline.py"
        legacy.write_text("#!/usr/bin/env python3\nprint('old')\n", encoding="utf-8")

        code, out, err = self._run_cli(["install", "--data-dir", str(self.data_dir), "--command", str(RENDERER_PATH)])
        self.assertEqual(code, 0, err)
        self.assertIn("Installed statusLine", out)
        self.assertTrue(settings_link.is_symlink())
        self.assertEqual(stat.S_IMODE(real_settings.stat().st_mode), 0o600)

        updated = json.loads(real_settings.read_text(encoding="utf-8"))
        self.assertEqual(updated["trustedWorkspaces"], ["/tmp/a"])
        self.assertEqual(updated["statusLine"]["padding"], 1)
        self.assertTrue(updated["statusLine"]["stack_with_default"])
        self.assertEqual(updated["statusLine"]["command"], str(RENDERER_PATH))
        self.assertTrue(updated["statusLine"]["enabled"])
        self.assertFalse(legacy.exists())
        self.assertTrue((self.data_dir / "statusline.py.legacy.bak").is_file())

        first_bak = self.data_dir / "settings.json.bak"
        self.assertTrue(first_bak.is_file())
        self.assertEqual(stat.S_IMODE(first_bak.stat().st_mode), 0o600)
        first_bak_content = first_bak.read_text(encoding="utf-8")

        # Second install must NOT overwrite the original settings.json.bak
        code2, _, err2 = self._run_cli(["install", "--data-dir", str(self.data_dir), "--command", str(RENDERER_PATH)])
        self.assertEqual(code2, 0, err2)
        self.assertEqual(first_bak.read_text(encoding="utf-8"), first_bak_content)
        self.assertGreaterEqual(len(list(self.data_dir.glob("settings.json.*.bak"))), 1)

    def test_install_link_legacy_respects_data_dir_and_dry_run_and_no_self_archive(self) -> None:
        # --dry-run makes zero changes
        code_d, out_d, _ = self._run_cli(["install", "--data-dir", str(self.data_dir), "--link-legacy", "--dry-run"])
        self.assertEqual(code_d, 0)
        self.assertIn("Dry run", out_d)
        self.assertFalse((self.data_dir / "settings.json").exists())
        self.assertFalse((self.data_dir / "statusline.py").exists())

        # --link-legacy sets command to <data-dir>/statusline.py (NOT hardcoded ~/.gemini/...)
        code_l, _, err_l = self._run_cli(["install", "--data-dir", str(self.data_dir), "--link-legacy"])
        self.assertEqual(code_l, 0, err_l)
        legacy = self.data_dir / "statusline.py"
        self.assertTrue(legacy.is_symlink())
        self.assertEqual(legacy.resolve(), RENDERER_PATH)
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["statusLine"]["command"], cli.shell_quote_path(legacy))

        # Running symlinked statusline.py resolves config.local.json at skill root
        proc = subprocess.run(
            [str(legacy)],
            input=json.dumps(cli.SCENARIOS["default"]),
            text=True,
            capture_output=True,
            timeout=5,
            env=clean_subprocess_env({"AGY_DATA_DIR": str(self.data_dir), "AGY_STATUSLINE_NO_SNAPSHOT": "1"}),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(proc.stdout.splitlines()), 6)

        proc_off = subprocess.run(
            [str(legacy)],
            input=json.dumps(cli.SCENARIOS["default"]),
            text=True,
            capture_output=True,
            timeout=5,
            env=clean_subprocess_env(
                {"AGY_DATA_DIR": str(self.data_dir), "AGY_STATUSLINE_NO_SNAPSHOT": "1", "AGY_STATUSLINE_PET": "0"}
            ),
        )
        self.assertEqual(proc_off.returncode, 0, proc_off.stderr)
        self.assertEqual(len(proc_off.stdout.splitlines()), 1)

        # Installing with --command pointing via resolved alias to standalone legacy must NOT archive itself
        alt_dir = self.root / "alt-agy"
        alt_dir.mkdir()
        standalone = alt_dir / "statusline.py"
        standalone.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
        os.chmod(standalone, 0o755)
        code_same, _, err_same = self._run_cli(["install", "--data-dir", str(alt_dir), "--command", str(standalone.resolve())])
        self.assertEqual(code_same, 0, err_same)
        self.assertTrue(standalone.is_file())

    def test_ensure_executable_matches_read_bits_and_backup_collision_safety(self) -> None:
        f600 = self.root / "priv.py"
        f600.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        os.chmod(f600, 0o600)
        self.assertTrue(cli.ensure_executable(f600))
        self.assertEqual(stat.S_IMODE(f600.stat().st_mode), 0o700)

        f640 = self.root / "grp.py"
        f640.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        os.chmod(f640, 0o640)
        self.assertTrue(cli.ensure_executable(f640))
        self.assertEqual(stat.S_IMODE(f640.stat().st_mode), 0o750)

        # Same-second backup_legacy_file calls produce distinct files
        leg = self.data_dir / "statusline.py"
        created = []
        for idx in range(3):
            leg.write_text(f"v{idx}", encoding="utf-8")
            created.append(cli.backup_legacy_file(leg))
        self.assertEqual(len(set(created)), 3)
        self.assertEqual([p.read_text(encoding="utf-8") for p in created], ["v0", "v1", "v2"])

    def test_shell_quoting_and_command_parsing(self) -> None:
        spaced = Path("/tmp/my dir/statusline.py")
        quoted = cli.shell_quote_path(spaced)
        self.assertEqual(quoted, "'/tmp/my dir/statusline.py'")
        err, parsed_path, is_direct = cli.parse_shell_command(quoted)
        self.assertIsNone(err)
        self.assertEqual(parsed_path, spaced)
        self.assertTrue(is_direct)

        err2, parsed_py, is_direct2 = cli.parse_shell_command("AGY_X=1 python3 '/tmp/my dir/statusline.py'")
        self.assertIsNone(err2)
        self.assertEqual(parsed_py, spaced)
        self.assertFalse(is_direct2)

        # Home path with spaces keeps ~ unquoted so POSIX sh expands it
        home_spaced = Path.home() / "My Projects" / "statusline.py"
        q_home = cli.shell_quote_path(home_spaced)
        self.assertTrue(q_home.startswith("~/"))
        self.assertIn("'My Projects/statusline.py'", q_home)

    def test_read_settings_strict_and_uninstall_edge_cases(self) -> None:
        settings_path = self.data_dir / "settings.json"

        # 0-byte file rejected (not treated as valid {})
        settings_path.write_text("", encoding="utf-8")
        code, _, err = self._run_cli(["install", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 1)
        self.assertIn("malformed", err)

        # Malformed JSON rejected
        settings_path.write_text("{bad", encoding="utf-8")
        code2, _, err2 = self._run_cli(["uninstall", "--data-dir", str(self.data_dir)])
        self.assertEqual(code2, 1)
        self.assertIn("malformed", err2)

        # PermissionError distinct from malformed
        with mock.patch.object(cli, "read_settings_strict", side_effect=PermissionError("denied")):
            code_p, _, err_p = self._run_cli(["install", "--data-dir", str(self.data_dir)])
            self.assertEqual(code_p, 1)
            self.assertIn("Permission denied", err_p)
            self.assertNotIn("malformed", err_p)

        # Valid uninstall preserves command/padding on disable, removes block on --remove, no-ops on --dry-run
        settings_path.write_text(
            json.dumps({"model": "M", "statusLine": {"type": "command", "command": str(RENDERER_PATH), "enabled": True, "padding": 2}}),
            encoding="utf-8",
        )
        code_dr, _, _ = self._run_cli(["uninstall", "--data-dir", str(self.data_dir), "--dry-run"])
        self.assertEqual(code_dr, 0)
        self.assertTrue(json.loads(settings_path.read_text(encoding="utf-8"))["statusLine"]["enabled"])

        code_dis, _, _ = self._run_cli(["uninstall", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_dis, 0)
        parsed = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertFalse(parsed["statusLine"]["enabled"])
        self.assertEqual(parsed["statusLine"]["command"], str(RENDERER_PATH))
        self.assertEqual(parsed["statusLine"]["padding"], 2)

        code_rm, _, _ = self._run_cli(["uninstall", "--data-dir", str(self.data_dir), "--remove"])
        self.assertEqual(code_rm, 0)
        self.assertNotIn("statusLine", json.loads(settings_path.read_text(encoding="utf-8")))

    def test_preview_config_debug_json_input_and_width_validation(self) -> None:
        # Missing/malformed --config fails fast with exit 1
        code_bad_cfg, _, err_bad_cfg = self._run_cli(["preview", "--config", str(self.root / "missing.json"), "--data-dir", str(self.data_dir)])
        self.assertEqual(code_bad_cfg, 1)
        self.assertIn("not found", err_bad_cfg)

        # Negative --width rejected by argparse
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()):
                cli.main(["preview", "--width", "-10"])
        self.assertEqual(cm.exception.code, 2)

        # Valid custom --config applied
        custom_cfg = self.root / "custom.json"
        custom_cfg.write_text(json.dumps({"separator": " || "}), encoding="utf-8")
        code_ok, out_ok, err_ok = self._run_cli(
            ["preview", "--scenario", "default", "--config", str(custom_cfg), "--width", "100", "--no-color", "--data-dir", str(self.data_dir)]
        )
        self.assertEqual(code_ok, 0, err_ok)
        self.assertIn(" || ", out_ok)
        self.assertNotIn("OVERFLOW!", out_ok)

        # --from-debug uses live settings.json fallback & handles bad terminal_width
        (self.data_dir / "settings.json").write_text(json.dumps({"model": "Gemini 4 Live", "agentMode": "plan"}), encoding="utf-8")
        dbg = self.root / "dump.json"
        dbg.write_text(json.dumps({"terminal_width": "bad"}), encoding="utf-8")
        code_dbg, out_dbg, err_dbg = self._run_cli(["preview", "--from-debug", str(dbg), "--no-color", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_dbg, 0, err_dbg)
        self.assertIn("plan · Gemini 4 Live", out_dbg)

        # --json-input - reads stdin cleanly
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"workspace": {"current_dir": "/tmp/stdin-demo"}, "cycle_mode": "plan"}))):
            code_in, out_in, err_in = self._run_cli(["preview", "--json-input", "-", "--width", "90", "--no-color", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_in, 0, err_in)
        self.assertIn("stdin-demo", out_in)

    def test_status_and_doctor_matrix_and_no_snapshot_pollution(self) -> None:
        # Missing settings -> doctor fails cleanly (Check 2 skipped on unreadable/missing)
        code_m, out_m, _ = self._run_cli(["doctor", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_m, 1)
        self.assertIn("settings.json not found", out_m)
        self.assertNotIn("missing statusLine block", out_m)

        # Directory configured as statusLine.command -> rejected by status and doctor
        (self.data_dir / "settings.json").write_text(
            json.dumps({"statusLine": {"type": "command", "command": str(self.data_dir), "enabled": True}}),
            encoding="utf-8",
        )
        code_dir_s, out_dir_s, _ = self._run_cli(["status", "--json", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_dir_s, 0)
        st_json = json.loads(out_dir_s)
        self.assertFalse(st_json["command_exists"])
        self.assertFalse(st_json["command_executable"])

        code_dir_d, out_dir_d, _ = self._run_cli(["doctor", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_dir_d, 1)
        self.assertIn("not a file", out_dir_d)

        # Corrupt quota_snapshot.json surfaced in both status text and doctor
        snap_path = self.data_dir / "cache" / "quota_snapshot.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text("{corrupt", encoding="utf-8")
        code_st_txt, out_st_txt, _ = self._run_cli(["status", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_st_txt, 0)
        self.assertIn("Quota snapshot   : ERROR", out_st_txt)
        snap_path.unlink()

        # Non-string theme in config emits WARN (not malformed JSON crash)
        (self.data_dir / "statusline.json").write_text(json.dumps({"theme": ["minimal"]}), encoding="utf-8")
        code_i, _, err_i = self._run_cli(["install", "--data-dir", str(self.data_dir), "--command", f"python3 {cli.shell_quote_path(RENDERER_PATH)}"])
        self.assertEqual(code_i, 0, err_i)
        code_ok_d, out_ok_d, err_ok_d = self._run_cli(["doctor", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_ok_d, 0, f"{out_ok_d}\n{err_ok_d}")
        self.assertIn("theme must be a string", out_ok_d)
        self.assertIn("Renderer smoke passed", out_ok_d)
        self.assertFalse(snap_path.exists())

    def test_init_config_protects_existing_and_dangling_symlinks(self) -> None:
        (self.fake_skill_root / "config.example.json").write_text('{"theme": "tokyo-night"}\n', encoding="utf-8")

        # Dangling symlink must NOT be followed without --force
        outside = self.root / "outside.json"
        local = self.fake_skill_root / "config.local.json"
        local.symlink_to(outside)
        code_sym, out_sym, _ = self._run_cli(["init-config"])
        self.assertEqual(code_sym, 0)
        self.assertIn("already exists", out_sym)
        self.assertFalse(outside.exists())

        # --force replaces symlink with regular file without creating outside target
        code_f, _, _ = self._run_cli(["init-config", "--force"])
        self.assertEqual(code_f, 0)
        self.assertTrue(local.is_file() and not local.is_symlink())
        self.assertFalse(outside.exists())

    def test_renderer_subprocess_e2e_valid_and_malformed_stdin(self) -> None:
        (self.data_dir / "settings.json").write_text(json.dumps({"model": "Gemini 4 Fallback", "agentMode": "plan"}), encoding="utf-8")
        env = clean_subprocess_env({"AGY_DATA_DIR": str(self.data_dir)})

        # Valid payload (default pet ON -> 5 pet rows + 1 bar row)
        sample = json.dumps(cli.SCENARIOS["default"])
        proc = subprocess.run([sys.executable, str(RENDERER_PATH)], input=sample, text=True, capture_output=True, timeout=5, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 6)
        plain = strip_ansi(lines[-1])
        self.assertIn("Gemini 4 Neon (XHigh)", plain)
        self.assertIn("109k/1M · ⚡89%", plain)
        self.assertTrue((self.data_dir / "cache" / "quota_snapshot.json").is_file())

        # Valid payload with AGY_STATUSLINE_PET=0 -> strict 1-line bar
        proc_off = subprocess.run(
            [sys.executable, str(RENDERER_PATH)],
            input=sample,
            text=True,
            capture_output=True,
            timeout=5,
            env=clean_subprocess_env(
                {"AGY_DATA_DIR": str(self.data_dir), "AGY_STATUSLINE_NO_SNAPSHOT": "1", "AGY_STATUSLINE_PET": "0"}
            ),
        )
        self.assertEqual(proc_off.returncode, 0, proc_off.stderr)
        self.assertEqual(len(proc_off.stdout.splitlines()), 1)

        # Empty, malformed, and non-dict stdin never crash and fall back to settings.json
        for bad_in in ("", "{malformed", "[]", "null"):
            p2 = subprocess.run(
                [sys.executable, str(RENDERER_PATH)],
                input=bad_in,
                text=True,
                capture_output=True,
                timeout=5,
                env=clean_subprocess_env({"AGY_DATA_DIR": str(self.data_dir), "AGY_STATUSLINE_NO_SNAPSHOT": "1"}),
            )
            self.assertEqual(p2.returncode, 0, f"failed for {bad_in!r}: {p2.stderr}")
            self.assertEqual(p2.stderr, "")
            self.assertEqual(len(p2.stdout.splitlines()), 6)
            self.assertIn("plan · Gemini 4 Fallback", strip_ansi(p2.stdout.splitlines()[-1]))


class PetRendererAndCliTest(IsolatedTestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_sprite_geometry_colors_and_ascii_widths(self) -> None:
        valid_pixels = set(pet.PIXEL_COLORS.keys()) | {".", " "}
        expected_states = ("idle", "working", "tool_use", "confirm", "error", "sleep")
        self.assertEqual(pet.SPECIES_LIST, ("gemini", "prism"))
        for st in expected_states:
            px_frames = pet.GEMINI_PIXEL_FRAMES[st]
            self.assertGreaterEqual(len(px_frames), 2, f"{st} needs >= 2 animation frames")
            for f_idx, grid in enumerate(px_frames):
                self.assertEqual(len(grid), 10, f"{st}[{f_idx}] must have 10 pixel rows")
                for r_idx, row in enumerate(grid):
                    self.assertEqual(len(row), 16, f"{st}[{f_idx}] row {r_idx} must be 16 cols")
                    self.assertTrue(set(row).issubset(valid_pixels), f"invalid pixel in {st}[{f_idx}]: {row!r}")

            asc_frames = pet.GEMINI_ASCII_FRAMES[st]
            self.assertGreaterEqual(len(asc_frames), 2)
            for f_idx, rows in enumerate(asc_frames):
                self.assertEqual(len(rows), 5, f"ascii {st}[{f_idx}] must have 5 rows")
                for r_idx, row in enumerate(rows):
                    self.assertEqual(sl.display_width(row), 16, f"ascii {st}[{f_idx}] row {r_idx} width != 16: {row!r}")

            inl_frames = pet.GEMINI_INLINE_FRAMES[st]
            self.assertGreaterEqual(len(inl_frames), 2)
            for face in inl_frames:
                self.assertGreaterEqual(sl.display_width(face), 6)
                self.assertLessEqual(sl.display_width(face), 9)

    def test_pet_toggle_config_env_and_lazy_import(self) -> None:
        payload = {"workspace": {"current_dir": "/tmp/demo"}, "model": "G4", "terminal_width": 100}
        cfg_off = sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"enabled": False}})
        with mock.patch.object(sl, "_load_pet_module", side_effect=AssertionError("should not load pet when off")):
            out_off = sl.render(payload, config=cfg_off, settings={})
        self.assertEqual(len(out_off.splitlines()), 1)

        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_PET": "off"}):
            with mock.patch.object(sl, "_load_pet_module", side_effect=AssertionError("env off must skip import")):
                out_env_off = sl.render(payload, config=sl.DEFAULT_CONFIG, settings={})
        self.assertEqual(len(out_env_off.splitlines()), 1)

        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_PET": "1"}):
            out_env_on = sl.render(payload, config=cfg_off, settings={})
        self.assertEqual(len(out_env_on.splitlines()), 6)

    def test_pet_mood_state_machine_and_subagent_badge(self) -> None:
        cfg = sl.DEFAULT_CONFIG
        self.assertEqual(pet.resolve_pet_mood({"agent_state": "error"}, cfg), ("error", ""))
        self.assertEqual(pet.resolve_pet_mood({"agent_state": "tool_use", "tool_confirmation_pending": True}, cfg), ("confirm", ""))
        self.assertEqual(
            pet.resolve_pet_mood(
                {
                    "agent_state": "tool_use",
                    "subagents": [{"status": "running"}, {"status": "completed"}, {"status": "running"}],
                },
                cfg,
            ),
            ("tool_use", "+2 sub"),
        )
        self.assertEqual(pet.resolve_pet_mood({"agent_state": "working"}, cfg), ("working", ""))
        self.assertEqual(pet.resolve_pet_mood({"agent_state": "initializing"}, cfg), ("working", ""))
        self.assertEqual(pet.resolve_pet_mood({"agent_state": "reviewing"}, cfg), ("reviewing", ""))
        self.assertEqual(pet.resolve_pet_mood({"context_window": {"used_percentage": 90.0}}, cfg), ("tired", ""))
        self.assertEqual(pet.resolve_pet_mood({"quota": {"g-5h": {"remaining_fraction": 0.12}}}, cfg), ("hungry", ""))
        self.assertEqual(pet.resolve_pet_mood({"agent_state": "idle", "context_window": {}}, cfg), ("sleep", ""))
        self.assertEqual(
            pet.resolve_pet_mood({"agent_state": "idle", "context_window": {"current_usage": {"input_tokens": 100}}}, cfg),
            ("idle", ""),
        )
        # NaN/inf thresholds & payload values never crash
        bad_cfg = sl._deep_merge(cfg, {"thresholds": {"context_critical_pct": float("nan"), "quota_warn_pct": float("inf")}})
        self.assertEqual(pet.resolve_pet_mood({"context_window": {"used_percentage": float("nan")}}, bad_cfg), ("idle", ""))

    def test_styles_alignment_positions_animation_and_no_color(self) -> None:
        payload = {
            "workspace": {"current_dir": "/tmp/demo"},
            "agent_state": "working",
            "model": "G4",
            "terminal_width": 90,
        }
        pal_color = sl.build_palette(sl.DEFAULT_CONFIG)
        pal_plain = sl.build_palette(sl.DEFAULT_CONFIG, no_color=True)

        # Default right alignment: every pet line aligns flush to target_width (90 - 2 = 88)
        out_default = sl.render(payload, config=sl.DEFAULT_CONFIG, settings={})
        default_lines = out_default.splitlines()
        self.assertEqual(len(default_lines), 6)
        for ln in default_lines[:5]:
            self.assertEqual(sl.display_width(ln), 88)
        self.assertIn("─╮", strip_ansi(default_lines[1]))
        self.assertIn("╰─", strip_ansi(default_lines[2]))

        # Animation frame switches over time when animate=True, stays fixed when animate=False
        f0 = pet.render_pet_lines(payload, sl.DEFAULT_CONFIG, pal_color, 90, target_width=88, now=0.0)
        f1 = pet.render_pet_lines(payload, sl.DEFAULT_CONFIG, pal_color, 90, target_width=88, now=0.5)
        self.assertNotEqual(f0, f1)
        static_cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"animate": False}})
        self.assertEqual(
            pet.render_pet_lines(payload, static_cfg, pal_color, 90, target_width=88, now=0.0),
            pet.render_pet_lines(payload, static_cfg, pal_color, 90, target_width=88, now=0.5),
        )

        # AGY_STATUSLINE_PET_FRAME pins deterministic frame
        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_PET_FRAME": "1"}):
            self.assertEqual(pet.render_pet_lines(payload, sl.DEFAULT_CONFIG, pal_color, 90, target_width=88, now=0.0), f1)

        # Position below places bar first, pet rows after
        below_cfg = sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"position": "below", "species": "prism"}})
        out_below = sl.render(payload, config=below_cfg, settings={})
        lines_below = out_below.splitlines()
        self.assertEqual(len(lines_below), 6)
        self.assertIn("/tmp/demo", strip_ansi(lines_below[0]))
        self.assertIn("prism", strip_ansi(lines_below[2]))

        # Prism palette produces distinct RGB values from standard lavender gemini
        gem_lines = pet.render_pet_lines(payload, sl.DEFAULT_CONFIG, pal_color, 90, target_width=88, now=0.0)
        prism_lines = pet.render_pet_lines(
            payload, sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"species": "prism"}}), pal_color, 90, target_width=88, now=0.0
        )
        self.assertNotEqual(gem_lines, prism_lines)

        # NO_COLOR emits zero ANSI escape codes across all variants, styles, and alignments
        for sp in pet.SPECIES_LIST:
            for st in pet.STYLES_LIST:
                for al in pet.ALIGNS_LIST:
                    c = sl._deep_merge(sl.DEFAULT_CONFIG, {"pet": {"species": sp, "style": st, "align": al}})
                    out = sl.render(payload, config=c, settings={}, no_color=True)
                    self.assertNotIn("\x1b", out, f"ANSI leak in no_color mode for {sp}/{st}/{al}")
                    for ln in out.splitlines():
                        self.assertLessEqual(sl.display_width(ln), 90)
                    if st == "inline":
                        self.assertEqual(len(out.splitlines()), 1)
                    else:
                        self.assertEqual(len(out.splitlines()), 6)

        # Half-block monochrome fallback still renders 5 sprite lines
        mono = pet.render_pet_lines(payload, sl.DEFAULT_CONFIG, pal_plain, 90, target_width=88, now=0.0)
        self.assertEqual(len(mono), 5)
        self.assertTrue(all("\x1b" not in ln for ln in mono))

    def test_pet_cli_toggle_customize_demo_and_config_preservation(self) -> None:
        local_cfg = self.fake_skill_root / "config.local.json"
        local_cfg.write_text(json.dumps({"theme": "minimal", "separator": " | "}), encoding="utf-8")

        # Toggle off -> preserves unrelated config keys
        code, out, err = self._run_cli(["pet", "off", "--data-dir", str(self.data_dir)])
        self.assertEqual(code, 0, err)
        self.assertIn("OFF", out)
        saved = json.loads(local_cfg.read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], "minimal")
        self.assertEqual(saved["separator"], " | ")
        self.assertFalse(saved["pet"]["enabled"])

        # Toggle flips False -> True; test --data-dir BEFORE sub-action too
        code_t, out_t, err_t = self._run_cli(["pet", "--data-dir", str(self.data_dir), "toggle"])
        self.assertEqual(code_t, 0, err_t)
        self.assertIn("ON", out_t)
        self.assertTrue(json.loads(local_cfg.read_text(encoding="utf-8"))["pet"]["enabled"])

        # Species, style, align, position, name, bubble, animate
        for argv in (
            ["pet", "species", "prism", "--data-dir", str(self.data_dir)],
            ["pet", "style", "inline", "--data-dir", str(self.data_dir)],
            ["pet", "align", "left", "--data-dir", str(self.data_dir)],
            ["pet", "position", "below", "--data-dir", str(self.data_dir)],
            ["pet", "name", "墨酱\x1b]0;bad\x07", "--data-dir", str(self.data_dir)],
            ["pet", "bubble", "off", "--data-dir", str(self.data_dir)],
            ["pet", "animate", "off", "--data-dir", str(self.data_dir)],
        ):
            c, _, e = self._run_cli(argv)
            self.assertEqual(c, 0, f"failed {argv}: {e}")

        code_s, out_s, _ = self._run_cli(["pet", "status", "--json", "--data-dir", str(self.data_dir)])
        self.assertEqual(code_s, 0)
        info = json.loads(out_s)
        self.assertTrue(info["enabled"])
        self.assertEqual(info["species"], "prism")
        self.assertEqual(info["style"], "inline")
        self.assertEqual(info["align"], "left")
        self.assertEqual(info["position"], "below")
        self.assertEqual(info["name"], "墨酱")
        self.assertFalse(info["show_bubble"])
        self.assertFalse(info["animate"])

        # Name --clear resets custom name
        c_clr, _, _ = self._run_cli(["pet", "name", "--clear", "--data-dir", str(self.data_dir)])
        self.assertEqual(c_clr, 0)
        self.assertEqual(json.loads(local_cfg.read_text(encoding="utf-8"))["pet"]["name"], "")

        # Demo static gallery & single variant
        c_all, out_all, err_all = self._run_cli(["pet", "demo", "--species", "all", "--static", "--no-color", "--data-dir", str(self.data_dir)])
        self.assertEqual(c_all, 0, err_all)
        for sp in pet.SPECIES_LIST:
            self.assertIn(f"[{sp}", out_all)
        c_one, out_one, err_one = self._run_cli(["pet", "demo", "--species", "gemini", "--style", "ascii", "--static", "--no-color", "--data-dir", str(self.data_dir)])
        self.assertEqual(c_one, 0, err_one)
        self.assertIn("[gemini · working]", out_one)

        # Preview --no-pet overrides even when AGY_STATUSLINE_PET=1 is set in env
        with mock.patch.dict(os.environ, {"AGY_STATUSLINE_PET": "1"}):
            c_prev, out_prev, err_prev = self._run_cli(
                ["preview", "--scenario", "working", "--no-pet", "--no-color", "--width", "100", "--data-dir", str(self.data_dir)]
            )
        self.assertEqual(c_prev, 0, err_prev)
        self.assertNotIn("OVERFLOW!", out_prev)
        self.assertEqual(len(out_prev.strip().splitlines()), 2)

        # If only <data_dir>/statusline.json exists (no config.local.json), pet mutates it instead of shadowing
        local_cfg.unlink()
        global_cfg = self.data_dir / "statusline.json"
        global_cfg.write_text(json.dumps({"theme": "tokyo-night"}), encoding="utf-8")
        c_glob, _, err_glob = self._run_cli(["pet", "off", "--data-dir", str(self.data_dir)])
        self.assertEqual(c_glob, 0, err_glob)
        self.assertFalse(local_cfg.exists())
        self.assertFalse(json.loads(global_cfg.read_text(encoding="utf-8"))["pet"]["enabled"])


if __name__ == "__main__":
    unittest.main()
