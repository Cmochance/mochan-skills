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
CLI_PATH = SKILL_ROOT / "scripts" / "agy-statusline"
AGY_STATS_PATH = SKILL_ROOT.parent / "agy-stats" / "scripts" / "agy-stats"

ISOLATED_ENV_KEYS = (
    "NO_COLOR",
    "AGY_STATUSLINE_CONFIG",
    "AGY_STATUSLINE_NO_SNAPSHOT",
    "AGY_STATUSLINE_DEBUG",
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

        # Linked worktree with relative gitdir
        base = self.root / "bare"
        wt_git = base / ".git" / "worktrees" / "wt-alpha"
        wt_git.mkdir(parents=True)
        (wt_git / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
        wt_dir = self.root / "wt-dir"
        wt_dir.mkdir()
        (wt_dir / ".git").write_text(f"gitdir: {os.path.relpath(wt_git, wt_dir)}\n", encoding="utf-8")
        self.assertEqual(sl.detect_worktree({}, str(wt_dir)), ("wt-alpha", True))

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
        out = sl.render({"terminal_width": float("inf"), "workspace": {"current_dir": "/tmp/demo"}}, config=cfg, settings={})
        self.assertNotIn("\n", out)
        out_bool = sl.render({"terminal_width": True, "workspace": {"current_dir": "/tmp/demo"}}, config=sl.DEFAULT_CONFIG, settings={})
        self.assertGreater(sl.display_width(out_bool), 10)  # bool ignored -> falls back to 100, not 1

    def test_sanitization_blocks_newlines_and_terminal_escapes(self) -> None:
        cfg = sl._deep_merge(
            sl.DEFAULT_CONFIG,
            {"separator": " \n· ", "colors": {"path": "\x1b]0;pwn\x07\x1b[31m", "model": "\033[38;5;250m"}},
        )
        payload = {
            "workspace": {"current_dir": "file:///tmp/repo%0Ainjected%1B%5D0%3Bpwn%07"},
            "vcs": {"branch": "feat/\x9b31mred\x1b]52;c;ZGF0YQ==\x07\nline2"},
            "model": "G4\r\x1b[2Kfake",
            "credits": "100\t\x1b]8;;https://evil\x07click\x1b]8;;\x07",
            "terminal_width": 140,
        }
        out = sl.render(payload, config=cfg, settings={}, data_dir=self.data_dir)
        self.assertNotIn("\n", out)
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
            sl.DEFAULT_CONFIG,
            sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": ["worktree"]}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": ["worktree", "path"], "worktree": {"icon": "🌿"}}),
            sl._deep_merge(sl.DEFAULT_CONFIG, {"layout": {"right_margin": 0}}),
        ]
        for cfg in cfgs:
            for base in payloads:
                for width in (140, 100, 84, 64, 48, 30, 20, 12, 5, 4, 2, 1):
                    p = dict(base, terminal_width=width)
                    out = sl.render(p, config=cfg, settings={}, data_dir=self.data_dir)
                    self.assertNotIn("\n", out)
                    self.assertLessEqual(sl.display_width(out), width, f"overflowed at w={width}: {strip_ansi(out)!r}")

    def test_left_right_segment_layout_variants_and_terminal_width_fallbacks(self) -> None:
        base = {
            "workspace": {"current_dir": "/tmp/demo"},
            "worktree": {"name": "wt-1"},
            "cycle_mode": "plan",
            "model": {"display_name": "G4"},
            "terminal_width": 60,
        }
        # Reversed left segments
        rev = strip_ansi(sl.render(base, config=sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": ["worktree", "path"]}), settings={}))
        self.assertTrue(rev.startswith("⎇ wt-1 /tmp/demo"))

        # Empty left -> right aligned
        r_only = strip_ansi(sl.render(base, config=sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": []}), settings={}))
        self.assertTrue(r_only.startswith(" "))
        self.assertIn("plan · G4", r_only)

        # Empty right -> left only
        l_only = strip_ansi(sl.render(base, config=sl._deep_merge(sl.DEFAULT_CONFIG, {"right_segments": []}), settings={}))
        self.assertEqual(l_only, "/tmp/demo ⎇ wt-1")

        # Both empty -> ""
        self.assertEqual(sl.render(base, config=sl._deep_merge(sl.DEFAULT_CONFIG, {"left_segments": [], "right_segments": []}), settings={}), "")

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
        self.assertEqual(len(proc.stdout.splitlines()), 1)

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

        # Valid payload
        sample = json.dumps(cli.SCENARIOS["default"])
        proc = subprocess.run([sys.executable, str(RENDERER_PATH)], input=sample, text=True, capture_output=True, timeout=5, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        plain = strip_ansi(lines[0])
        self.assertIn("Gemini 4 Neon (XHigh)", plain)
        self.assertIn("109k/1M · ⚡89%", plain)
        self.assertTrue((self.data_dir / "cache" / "quota_snapshot.json").is_file())

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
            self.assertEqual(len(p2.stdout.splitlines()), 1)
            self.assertIn("plan · Gemini 4 Fallback", strip_ansi(p2.stdout))


if __name__ == "__main__":
    unittest.main()
