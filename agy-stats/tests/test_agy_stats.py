"""Unit tests for agy-stats."""

from __future__ import annotations

from contextlib import redirect_stderr
from datetime import date, timedelta
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest import mock

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "agy-stats"


def load_module():
    loader = importlib.machinery.SourceFileLoader("agy_stats_mod", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


agy_stats = load_module()


class AgyStatsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_transcript(self, conv_id: str, lines: list[str]) -> Path:
        p = self.data_dir / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def test_collect_usage_and_cache_invalidation(self) -> None:
        today_iso = date.today().isoformat() + "T10:00:00+00:00"
        t_path = self._write_transcript(
            "conv-1",
            [
                json.dumps({"type": "USER_INPUT", "created_at": today_iso}),
                "{malformed json line",
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": today_iso,
                        "model": "gemini-4-hydrogen-medium",
                        "input_tokens": 1000,
                        "cache_read_tokens": 2000,
                        "output_tokens": 500,
                        "tool_calls": [{"name": "read_file"}, {"name": "run_command"}],
                    }
                ),
            ],
        )

        res1 = agy_stats.collect_usage(self.data_dir)
        self.assertEqual(res1["sessions"], 1)
        self.assertEqual(res1["models"]["Gemini 4 Hydrogen"], [1, 1000, 2000, 500, 2])

        cache_file = self.data_dir / "cache" / "usage_stats_cache.json"
        self.assertTrue(cache_file.exists())

        # Append another step -> cache must invalidate because size/mtime changes
        with t_path.open("a", encoding="utf-8") as fp:
            fp.write(
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": today_iso,
                        "model": "gemini-4-carbon-high",
                        "input_tokens": 300,
                        "cache_read_tokens": 0,
                        "output_tokens": 100,
                    }
                )
                + "\n"
            )

        res2 = agy_stats.collect_usage(self.data_dir, exact_models=True)
        self.assertEqual(res2["models"]["gemini-4-hydrogen-medium"], [1, 1000, 2000, 500, 2])
        self.assertEqual(res2["models"]["gemini-4-carbon-high"], [1, 300, 0, 100, 0])

    def test_subagent_and_project_filtering(self) -> None:
        today_iso = date.today().isoformat() + "T12:00:00Z"
        self._write_transcript(
            "main-conv",
            [
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": today_iso,
                        "model": "gemini-4-neon-xhigh",
                        "input_tokens": 500,
                        "cache_read_tokens": 0,
                        "output_tokens": 100,
                    }
                )
            ],
        )
        self._write_transcript(
            "sub-conv",
            [
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": today_iso,
                        "model": "gemini-flash-worker-agy",
                        "input_tokens": 900,
                        "cache_read_tokens": 0,
                        "output_tokens": 200,
                    }
                )
            ],
        )

        db_path = self.data_dir / "conversation_summaries.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE conversation_summaries "
            "(conversation_id TEXT PRIMARY KEY, workspace_uris TEXT, parent_conversation_id TEXT, nesting_depth INTEGER)"
        )
        conn.execute("INSERT INTO conversation_summaries VALUES ('main-conv', 'file:///proj/alpha', '', 0)")
        conn.execute("INSERT INTO conversation_summaries VALUES ('sub-conv', 'file:///proj/beta', 'main-conv', 1)")
        conn.commit()
        conn.close()

        no_sub = agy_stats.collect_usage(self.data_dir, exclude_subagents=True)
        self.assertEqual(no_sub["sessions"], 1)
        self.assertIn("Gemini 4 Neon", no_sub["models"])
        self.assertNotIn("Worker Flash", no_sub["models"])

        proj_filtered = agy_stats.collect_usage(self.data_dir, project_filter="beta")
        self.assertEqual(proj_filtered["sessions"], 1)
        self.assertIn("Worker Flash", proj_filtered["models"])

    def test_render_report_with_by_model_and_quota(self) -> None:
        today_iso = date.today().isoformat() + "T09:00:00Z"
        self._write_transcript(
            "conv-render",
            [
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": today_iso,
                        "model": "gemini-4-hydrogen-high",
                        "input_tokens": 2000,
                        "cache_read_tokens": 4000,
                        "output_tokens": 500,
                    }
                )
            ],
        )
        stats = agy_stats.collect_usage(self.data_dir)
        quota_snap = {
            "updated_at": today_iso,
            "quota": {
                "gemini_5h": {"remaining_fraction": 0.9, "reset_in_seconds": 3600},
                "gemini_weekly": {"remaining_fraction": 0.95, "reset_in_seconds": 86400},
            },
        }
        out = agy_stats.render_report(stats, by_model=True, quota_snapshot=quota_snap)
        self.assertIn("ANTIGRAVITY USAGE & ACTIVITY", out)
        self.assertIn("Activity Heatmap", out)
        self.assertIn("Model Weekly Distribution", out)
        self.assertIn("Model Breakdown", out)
        self.assertIn("Quota Snapshot", out)
        self.assertIn("Gemini 4 Hydrogen", out)

    def _make_fake_stream(self, is_tty: bool) -> io.StringIO:
        class _FakeStream(io.StringIO):
            def isatty(self) -> bool:
                return is_tty

        return _FakeStream()

    def test_main_default_static_mode_even_with_tty(self) -> None:
        today_iso = date.today().isoformat() + "T09:00:00Z"
        self._write_transcript(
            "conv-static",
            [
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": today_iso,
                        "model": "gemini-4-neon-xhigh",
                        "input_tokens": 1200,
                        "cache_read_tokens": 0,
                        "output_tokens": 300,
                    }
                )
            ],
        )
        stdin_tty = self._make_fake_stream(True)
        stdout_tty = self._make_fake_stream(True)
        with (
            mock.patch.object(agy_stats.sys, "stdin", stdin_tty),
            mock.patch.object(agy_stats.sys, "stdout", stdout_tty),
            mock.patch.object(agy_stats, "run_interactive") as mock_interactive,
        ):
            rc = agy_stats.main(["--data-dir", str(self.data_dir)])

        self.assertEqual(rc, 0)
        mock_interactive.assert_not_called()
        out = stdout_tty.getvalue()
        self.assertIn("ANTIGRAVITY USAGE & ACTIVITY", out)
        self.assertIn("Gemini 4 Neon", out)
        self.assertNotIn("[q] quit", out)

    def test_main_with_interactive_enters_tui_on_tty(self) -> None:
        stdin_tty = self._make_fake_stream(True)
        stdout_tty = self._make_fake_stream(True)
        with (
            mock.patch.object(agy_stats.sys, "stdin", stdin_tty),
            mock.patch.object(agy_stats.sys, "stdout", stdout_tty),
            mock.patch.object(agy_stats, "run_interactive", return_value=0) as mock_interactive,
        ):
            rc = agy_stats.main(["--data-dir", str(self.data_dir), "--with-interactive"])

        self.assertEqual(rc, 0)
        mock_interactive.assert_called_once()
        passed_args, passed_dir = mock_interactive.call_args[0]
        self.assertTrue(passed_args.with_interactive)
        self.assertEqual(passed_dir, self.data_dir)

    def test_main_with_interactive_non_tty_returns_error(self) -> None:
        for stdin_is_tty, stdout_is_tty in ((False, False), (False, True), (True, False)):
            with self.subTest(stdin_is_tty=stdin_is_tty, stdout_is_tty=stdout_is_tty):
                stdin_stream = self._make_fake_stream(stdin_is_tty)
                stdout_stream = self._make_fake_stream(stdout_is_tty)
                stderr_stream = io.StringIO()
                with (
                    mock.patch.object(agy_stats.sys, "stdin", stdin_stream),
                    mock.patch.object(agy_stats.sys, "stdout", stdout_stream),
                    mock.patch.object(agy_stats.sys, "stderr", stderr_stream),
                    mock.patch.object(agy_stats, "run_interactive") as mock_interactive,
                ):
                    rc = agy_stats.main(["--data-dir", str(self.data_dir), "--with-interactive"])

                self.assertEqual(rc, 1)
                mock_interactive.assert_not_called()
                self.assertEqual(stdout_stream.getvalue(), "")
                err = stderr_stream.getvalue()
                self.assertIn("--with-interactive", err)
                self.assertIn("TTY", err)

    def test_no_interactive_flag_is_removed(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            agy_stats.build_parser().parse_args(["--no-interactive"])
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("--no-interactive", err.getvalue())

    def _build_rich_stats(self) -> tuple[dict, dict]:
        today = date.today()
        yesterday = today - timedelta(days=1)
        last_week = today - timedelta(days=7)
        self._write_transcript(
            "conv-rich",
            [
                json.dumps({"type": "USER_INPUT", "created_at": today.isoformat() + "T08:00:00Z"}),
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": today.isoformat() + "T08:05:00Z",
                        "model": "gemini-4-hydrogen-medium-long-variant",
                        "input_tokens": 125_000_000,
                        "cache_read_tokens": 980_000_000,
                        "output_tokens": 23_400_000,
                        "tool_calls": [{"name": "read_file"}, {"name": "edit_file"}],
                    }
                ),
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": yesterday.isoformat() + "T09:00:00Z",
                        "model": "gemini-4-carbon-high",
                        "input_tokens": 45_000,
                        "cache_read_tokens": 120_000,
                        "output_tokens": 12_000,
                    }
                ),
                json.dumps(
                    {
                        "type": "PLANNER_RESPONSE",
                        "created_at": last_week.isoformat() + "T10:00:00Z",
                        "model": "gemini-4-neon-xhigh",
                        "input_tokens": 8_000,
                        "cache_read_tokens": 20_000,
                        "output_tokens": 2_000,
                    }
                ),
            ],
        )
        stats = agy_stats.collect_usage(self.data_dir, exact_models=True)
        quota_snap = {
            "updated_at": today.isoformat() + "T09:00:00Z",
            "quota": {
                "gemini_5h": {"remaining_fraction": 0.9, "reset_in_seconds": 3600},
                "gemini_weekly_long_bucket_name": {"remaining_fraction": 0.15, "reset_in_seconds": 90000},
            },
        }
        return stats, quota_snap

    def test_narrow_width_and_columns_never_overflow(self) -> None:
        stats, quota_snap = self._build_rich_stats()
        cases = [
            ("explicit_40", 40, None, 40),
            ("explicit_50", 50, None, 50),
            ("env_columns_40", None, "40", 40),
            ("env_columns_50", None, "50", 50),
            ("ultra_narrow_20", 20, None, 20),
        ]
        for label, explicit_w, env_cols, max_allowed in cases:
            with self.subTest(case=label):
                env_patch = {"COLUMNS": env_cols} if env_cols is not None else {}
                with mock.patch.dict(os.environ, env_patch, clear=False):
                    if env_cols is None and "COLUMNS" in os.environ:
                        os.environ.pop("COLUMNS", None)
                    out = agy_stats.render_report(
                        stats,
                        metric="all-tokens",
                        by_model=True,
                        exact_models=True,
                        exclude_subagents=True,
                        quota_snapshot=quota_snap,
                        interactive_hint=True,
                        width=explicit_w,
                    )
                for idx, line in enumerate(out.splitlines(), start=1):
                    plain = agy_stats.strip_ansi(line)
                    self.assertNotIn("\x1b", plain, f"{label} line {idx} has malformed ANSI: {line!r}")
                    self.assertNotIn("8;5;", plain, f"{label} line {idx} leaked ANSI fragment: {plain!r}")
                    self.assertLessEqual(
                        agy_stats.visible_len(line),
                        max_allowed,
                        f"{label} line {idx} overflowed {max_allowed}: len={agy_stats.visible_len(line)} plain={plain!r}",
                    )
                if label == "ultra_narrow_20":
                    m = re.search(r"\(Last (\d+)w\)", agy_stats.strip_ansi(out))
                    self.assertIsNotNone(m)
                    vis_w = int(m.group(1))
                    self.assertGreaterEqual(vis_w, 4)
                    self.assertLess(vis_w, 8)

    def test_heatmap_and_by_model_ansi_run_length_dedup(self) -> None:
        # Empty stats => every rendered cell in heatmap is level 0 (same ANSI color)
        stats = {"daily": {}, "models": {"Gemini 4 Neon": [1, 100, 0, 50, 0]}, "sessions": 1}
        out = agy_stats.render_report(stats, by_model=True, weeks=26, width=100)
        raw_lines = out.splitlines()

        mon_line = next(l for l in raw_lines if agy_stats.strip_ansi(l).startswith("  Mon  "))
        self.assertEqual(
            mon_line.count(agy_stats.HEAT_LEVELS[0]),
            1,
            f"Expected single ANSI prefix for consecutive empty cells, got: {mon_line!r}",
        )
        self.assertFalse(
            agy_stats.strip_ansi(mon_line).endswith(" "),
            f"Heatmap row should not have trailing spaces: {agy_stats.strip_ansi(mon_line)!r}",
        )

        # Model weekly distribution row (all empty weeks => single HEAT_LEVELS[0] prefix)
        model_grid_line = next(
            l for l in raw_lines if "Gemini 4 Neon" in agy_stats.strip_ansi(l) and "▪" in agy_stats.strip_ansi(l)
        )
        self.assertEqual(
            model_grid_line.count(agy_stats.HEAT_LEVELS[0]),
            1,
            f"Expected single ANSI prefix in by-model row, got: {model_grid_line!r}",
        )
        self.assertFalse(agy_stats.strip_ansi(model_grid_line).endswith(" "))

    def test_heatmap_header_and_legend_wrap_at_narrow_width(self) -> None:
        stats = {"daily": {}, "models": {}, "sessions": 0}

        wide = agy_stats.strip_ansi(agy_stats.render_report(stats, weeks=26, width=100))
        wide_lines = wide.splitlines()
        wide_hdr = next(l for l in wide_lines if "Activity Heatmap" in l)
        self.assertIn("(Last 26w)", wide_hdr)
        self.assertIn("Less", wide_hdr)
        self.assertIn("More", wide_hdr)

        for narrow_w in (40, 50):
            with self.subTest(width=narrow_w):
                narrow = agy_stats.strip_ansi(agy_stats.render_report(stats, weeks=26, width=narrow_w))
                narrow_lines = narrow.splitlines()
                hdr_idx = next(i for i, l in enumerate(narrow_lines) if "Activity Heatmap" in l)
                self.assertNotIn("Less", narrow_lines[hdr_idx])
                self.assertIn("Less", narrow_lines[hdr_idx + 1])
                self.assertIn("More", narrow_lines[hdr_idx + 1])
                self.assertTrue(narrow_lines[hdr_idx + 1].startswith("  Less "))

    def test_width_cli_flag_parsing_and_execution(self) -> None:
        parser = agy_stats.build_parser()
        default_args = parser.parse_args([])
        self.assertIsNone(default_args.width)

        parsed = parser.parse_args(["--width", "40"])
        self.assertEqual(parsed.width, 40)

        for bad in ("0", "-10", "abc"):
            with self.subTest(bad_width=bad):
                err = io.StringIO()
                with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
                    parser.parse_args(["--width", bad])
                self.assertNotEqual(ctx.exception.code, 0)

        self._build_rich_stats()
        stdout_buf = self._make_fake_stream(False)
        with mock.patch.object(agy_stats.sys, "stdout", stdout_buf):
            rc = agy_stats.main(["--data-dir", str(self.data_dir), "--by-model", "--width", "40"])
        self.assertEqual(rc, 0)
        for line in stdout_buf.getvalue().splitlines():
            self.assertLessEqual(agy_stats.visible_len(line), 40)


if __name__ == "__main__":
    unittest.main()
