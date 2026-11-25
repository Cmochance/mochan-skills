import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "linear-index" / "scripts" / "linear-idx"


class LinearIdxCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.index_dir = self.tmp_dir / "idx"
        self.cfg_path = self.tmp_dir / "config.json"
        self.cfg_path.write_text(
            json.dumps(
                {
                    "workspace": "test-ws",
                    "default_team": "CHX",
                    "index_dir": str(self.index_dir),
                    "stale_hours": 24,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_cli(
        self,
        *args: str,
        input_text: str | None = None,
        use_default_cfg: bool = True,
        extra_env: dict[str, str] | None = None,
        exe: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(exe or SCRIPT_PATH)] if exe is None else [str(exe)]
        if use_default_cfg:
            cmd.extend(["--config", str(self.cfg_path)])
        cmd.extend(args)
        env = dict(os.environ)
        env.pop("LINEAR_INDEX_DIR", None)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            cwd=str(self.tmp_dir),
            env=env,
            check=False,
        )

    def test_status_uninitialized_fresh_stale_and_corrupt_fallback(self) -> None:
        # 1. UNINITIALIZED (text + --json)
        r_txt = self.run_cli("status")
        self.assertEqual(r_txt.returncode, 0, r_txt.stderr)
        self.assertIn("freshness: UNINITIALIZED", r_txt.stdout)

        r_json = self.run_cli("status", "--json")
        self.assertEqual(r_json.returncode, 0, r_json.stderr)
        data = json.loads(r_json.stdout)
        self.assertEqual(data["freshness"], "UNINITIALIZED")
        self.assertIsNone(data["last_sync"])
        self.assertIsNone(data["age_hours"])
        self.assertEqual(data["default_team"], "CHX")
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["open"], 0)
        self.assertEqual(data["archived"], 0)

        # Search on UNINITIALIZED exits 0 cleanly
        r_uninit_search = self.run_cli("search", "anything")
        self.assertEqual(r_uninit_search.returncode, 0)
        self.assertTrue(r_uninit_search.stdout.startswith("# index: UNINITIALIZED ("))

        # 2. FRESH (after upsert)
        page = self.tmp_dir / "p1.json"
        page.write_text(
            json.dumps(
                {
                    "issues": [
                        {
                            "id": "CHX-1",
                            "title": "Alpha",
                            "status": "In Progress",
                            "statusType": "started",
                            "updatedAt": "2026-11-25T10:00:00Z",
                        }
                    ],
                    "hasNextPage": False,
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("upsert", "--rebuild", str(page)).returncode, 0)

        r_fresh = self.run_cli("status", "--json")
        self.assertEqual(r_fresh.returncode, 0)
        fresh = json.loads(r_fresh.stdout)
        self.assertEqual(fresh["freshness"], "FRESH")
        self.assertLessEqual(fresh["age_hours"], 0.2)
        self.assertEqual(fresh["total"], 1)
        self.assertEqual(fresh["open"], 1)
        self.assertEqual(fresh["by_team"], {"CHX": 1})
        self.assertEqual(fresh["by_statusType"], {"started": 1})

        r_fresh_txt = self.run_cli("status")
        self.assertEqual(r_fresh_txt.returncode, 0)
        self.assertIn("freshness: FRESH", r_fresh_txt.stdout)

        # 3. STALE (> 24h, +00:00 format)
        meta_path = self.index_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        old_dt = datetime.now(timezone.utc) - timedelta(hours=30)
        meta["last_sync"] = old_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        r_stale = self.run_cli("status", "--json")
        self.assertEqual(r_stale.returncode, 0)
        stale = json.loads(r_stale.stdout)
        self.assertEqual(stale["freshness"], "STALE")
        self.assertGreaterEqual(stale["age_hours"], 29.9)

        r_stale_txt = self.run_cli("status")
        self.assertIn("freshness: STALE", r_stale_txt.stdout)

        # 4. Future timestamp anomaly -> STALE
        future_dt = datetime.now(timezone.utc) + timedelta(hours=5)
        meta["last_sync"] = future_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.assertEqual(json.loads(self.run_cli("status", "--json").stdout)["freshness"], "STALE")

        # 5. Corrupted meta.json falls back to scanning issues.jsonl
        meta_path.write_text("{corrupt json", encoding="utf-8")
        r_corrupt = self.run_cli("status", "--json")
        self.assertEqual(r_corrupt.returncode, 0)
        self.assertIn("WARNING", r_corrupt.stderr)
        recovered = json.loads(r_corrupt.stdout)
        self.assertEqual(recovered["freshness"], "STALE")
        self.assertEqual(recovered["total"], 1)
        self.assertEqual(recovered["open"], 1)

        # 6. Valid JSON object in meta.json with corrupted field types falls back cleanly (no traceback)
        meta_path.write_text(
            json.dumps(
                {
                    "last_sync": "2026-11-25T10:00:00Z",
                    "total": "bad",
                    "archived": None,
                    "open": True,
                    "by_team": "not-a-dict",
                    "by_statusType": [],
                }
            ),
            encoding="utf-8",
        )
        r_bad_types = self.run_cli("status", "--json")
        self.assertEqual(r_bad_types.returncode, 0, r_bad_types.stderr)
        self.assertIn("WARNING", r_bad_types.stderr)
        self.assertNotIn("Traceback", r_bad_types.stderr)
        recovered_types = json.loads(r_bad_types.stdout)
        self.assertEqual(recovered_types["total"], 1)
        self.assertEqual(recovered_types["open"], 1)
        self.assertEqual(recovered_types["by_team"], {"CHX": 1})

        # 7. Invalid stale_hours (negative / NaN / Inf / bool) fails cleanly with CliError
        for bad_stale in (-1, "NaN", "Infinity", True):
            bad_cfg = self.tmp_dir / "bad_cfg.json"
            bad_cfg.write_text(
                json.dumps({"index_dir": str(self.index_dir), "stale_hours": bad_stale}),
                encoding="utf-8",
            )
            r_bad_cfg = self.run_cli(
                "status", "--config", str(bad_cfg), use_default_cfg=False
            )
            self.assertEqual(r_bad_cfg.returncode, 1)
            self.assertIn("Invalid stale_hours", r_bad_cfg.stderr)
            self.assertNotIn("Traceback", r_bad_cfg.stderr)

    def test_upsert_rebuild_multipage_normalization_sort_and_pagination_warning(self) -> None:
        # No input -> exit 2
        r_no_in = self.run_cli("upsert")
        self.assertEqual(r_no_in.returncode, 2)

        long_desc = "Line1\r\n\tLine2   Line3 " + ("x" * 600)
        p1 = self.tmp_dir / "page1.json"
        p2 = self.tmp_dir / "page2.json"

        # Page 1: MCP object with hasNextPage=True (dict fields)
        p1.write_text(
            json.dumps(
                {
                    "issues": [
                        {
                            "id": " chx-10 ",
                            "team": {"key": "IGNORED", "name": "Full Team Name"},
                            "title": "First issue",
                            "status": {"name": "In Progress"},
                            "statusType": "Started",
                            "priority": {"name": "High"},
                            "labels": [{"name": "Bug"}, "Security", ""],
                            "project": {"name": "Colab ComfyUI"},
                            "projectMilestone": {"name": "M1 Followup"},
                            "description": long_desc,
                            "updatedAt": "2026-11-20T08:00:00Z",
                            "url": "https://linear.app/issue/CHX-10",
                        },
                        {
                            "id": "   ",
                            "title": "Empty ID skipped",
                        },
                    ],
                    "hasNextPage": True,
                    "cursor": "cur_page_1",
                }
            ),
            encoding="utf-8",
        )

        # Page 2: MCP object with hasNextPage=True on LAST input -> triggers WARNING
        p2.write_text(
            json.dumps(
                {
                    "issues": [
                        {
                            "id": "MOC-20",
                            "team": "Mochan Team",
                            "title": None,
                            "status": "Todo",
                            "statusType": "unstarted",
                            "priority": "Medium",
                            "labels": ["Infra"],
                            "project": "Skills",
                            "milestone": "Q4",
                            "description": None,
                            "desc": "Fallback\tdesc\nline",
                            "updatedAt": "2026-11-24T12:00:00Z",
                        },
                        {
                            "id": "NOHYPHEN1",
                            "team": {"key": "OPS", "name": "Operations"},
                            "title": "No hyphen ID uses team.key",
                            "status": "Backlog",
                            "statusType": "backlog",
                            "updatedAt": "2026-11-24T12:00:00Z",
                        },
                    ],
                    "hasNextPage": True,
                    "cursor": "cur_page_2",
                }
            ),
            encoding="utf-8",
        )

        res = self.run_cli("upsert", "--rebuild", str(p1), str(p2))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(
            "WARNING: last input reports hasNextPage=true (cursor=cur_page_2)",
            res.stderr,
        )

        rows = [
            json.loads(line)
            for line in (self.index_dir / "issues.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # Descending order by (updatedAt, id): NOHYPHEN1 > MOC-20 (same updatedAt, 'N' > 'M'), then CHX-10 (normalized uppercase)
        self.assertEqual([r["id"] for r in rows], ["NOHYPHEN1", "MOC-20", "CHX-10"])

        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["CHX-10"]["team"], "CHX")
        self.assertEqual(by_id["CHX-10"]["status"], "In Progress")
        self.assertEqual(by_id["CHX-10"]["statusType"], "started")
        self.assertEqual(by_id["CHX-10"]["priority"], "High")
        self.assertEqual(by_id["CHX-10"]["labels"], ["Bug", "Security"])
        self.assertEqual(by_id["CHX-10"]["project"], "Colab ComfyUI")
        self.assertEqual(by_id["CHX-10"]["milestone"], "M1 Followup")
        self.assertEqual(len(by_id["CHX-10"]["desc"]), 500)
        self.assertNotIn("\n", by_id["CHX-10"]["desc"])
        self.assertNotIn("\t", by_id["CHX-10"]["desc"])
        self.assertTrue(by_id["CHX-10"]["desc"].startswith("Line1 Line2 Line3 "))

        self.assertEqual(by_id["MOC-20"]["team"], "MOC")
        self.assertEqual(by_id["MOC-20"]["title"], "")
        self.assertEqual(by_id["MOC-20"]["milestone"], "Q4")
        self.assertEqual(by_id["MOC-20"]["desc"], "Fallback desc line")
        self.assertEqual(by_id["NOHYPHEN1"]["team"], "OPS")

        # Verify no warning when final page has hasNextPage=False
        p2_done = self.tmp_dir / "page2_done.json"
        p2_done.write_text(json.dumps({"issues": [], "hasNextPage": False}), encoding="utf-8")
        res_clean = self.run_cli("upsert", str(p1), str(p2_done))
        self.assertEqual(res_clean.returncode, 0)
        self.assertNotIn("WARNING", res_clean.stderr)

    def test_incremental_upsert_preserves_legacy_backfills_team_and_supports_stdin(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        # Seed legacy issues.jsonl WITHOUT 'team' field
        legacy_rows = [
            {
                "id": "CHX-1",
                "title": "Legacy untouched",
                "status": "Backlog",
                "statusType": "backlog",
                "updatedAt": "2026-10-01T00:00:00Z",
                "archivedAt": None,
                "desc": "old one",
            },
            {
                "id": "chx-2",
                "title": "Legacy to overwrite",
                "status": "Todo",
                "statusType": "unstarted",
                "updatedAt": "2026-10-02T00:00:00Z",
                "archivedAt": None,
                "desc": "old two",
            },
        ]
        (self.index_dir / "issues.jsonl").write_text(
            "\n".join(json.dumps(r) for r in legacy_rows) + "\n",
            encoding="utf-8",
        )

        # Incremental upsert via --stdin using JSONL (overwriting CHX-2 case-insensitively + adding MOC-3)
        stdin_jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "id": "CHX-2",
                        "title": "Updated title",
                        "status": "Done",
                        "statusType": "completed",
                        "updatedAt": "2026-11-25T09:00:00Z",
                        "description": "new two",
                    }
                ),
                "",
                json.dumps(
                    {
                        "id": "MOC-3",
                        "title": "Brand new",
                        "status": "Triage",
                        "statusType": "triage",
                        "updatedAt": "2026-11-25T11:00:00Z",
                        "description": "new three",
                    }
                ),
            ]
        )
        res = self.run_cli("upsert", "--stdin", input_text=stdin_jsonl)
        self.assertEqual(res.returncode, 0, res.stderr)

        rows = [
            json.loads(line)
            for line in (self.index_dir / "issues.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual([r["id"] for r in rows], ["MOC-3", "CHX-2", "CHX-1"])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["CHX-1"]["team"], "CHX")
        self.assertEqual(by_id["CHX-1"]["title"], "Legacy untouched")
        self.assertEqual(by_id["CHX-2"]["title"], "Updated title")
        self.assertEqual(by_id["CHX-2"]["statusType"], "completed")

    def test_search_filters_archive_visibility_open_states_and_outputs(self) -> None:
        seed = self.tmp_dir / "seed.json"
        seed.write_text(
            json.dumps(
                [
                    {
                        "id": "CHX-1",
                        "title": "Triage tunnel drop",
                        "status": "Triage",
                        "statusType": "triage",
                        "project": "Colab ComfyUI",
                        "milestone": "Followup",
                        "labels": ["Bug", "Network"],
                        "description": "ssh proxy disconnected",
                        "updatedAt": "2026-11-25T07:00:00Z",
                    },
                    {
                        "id": "CHX-2",
                        "title": "Backlog watchdog",
                        "status": "Backlog",
                        "statusType": "backlog",
                        "project": "Colab ComfyUI",
                        "milestone": "Followup",
                        "labels": ["Feature"],
                        "description": "idle timer 30m",
                        "updatedAt": "2026-11-25T06:00:00Z",
                    },
                    {
                        "id": "MOC-3",
                        "title": "Unstarted linear cli",
                        "status": "Todo",
                        "statusType": "unstarted",
                        "project": "mochan-skills",
                        "milestone": "Q4",
                        "labels": ["CLI"],
                        "description": "multi team index",
                        "updatedAt": "2026-11-25T05:00:00Z",
                    },
                    {
                        "id": "MOC-4",
                        "title": "Started x-read tier3",
                        "status": "In Progress",
                        "statusType": "started",
                        "project": "mochan-skills",
                        "milestone": "Q4",
                        "labels": ["CLI", "Auth"],
                        "description": "cookie isolation",
                        "updatedAt": "2026-11-25T04:00:00Z",
                    },
                    {
                        "id": "CHX-5",
                        "title": "Completed build dmg",
                        "status": "Done",
                        "statusType": "completed",
                        "project": "Colab ComfyUI",
                        "milestone": "v0.1",
                        "labels": ["Release"],
                        "description": "strip=false fix",
                        "updatedAt": "2026-11-25T03:00:00Z",
                    },
                    {
                        "id": "CHX-6",
                        "title": "Canceled experiment",
                        "status": "Canceled",
                        "statusType": "canceled",
                        "updatedAt": "2026-11-25T02:00:00Z",
                    },
                    {
                        "id": "CHX-7",
                        "title": "Duplicate report",
                        "status": "Duplicate",
                        "statusType": "duplicate",
                        "updatedAt": "2026-11-25T01:00:00Z",
                    },
                    {
                        "id": "CHX-8",
                        "title": "Archived open-looking issue",
                        "status": "In Progress",
                        "statusType": "started",
                        "project": "Colab ComfyUI",
                        "description": "ssh archived secret keyword",
                        "archivedAt": "2026-11-24T00:00:00Z",
                        "updatedAt": "2026-11-25T08:00:00Z",
                    },
                ]
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("upsert", "--rebuild", str(seed)).returncode, 0)

        # 1. --id hits archived issue by default
        r_id = self.run_cli("search", "--id", "chx-8,moc-3", "--json")
        self.assertEqual(r_id.returncode, 0)
        d_id = json.loads(r_id.stdout)
        self.assertEqual([i["id"] for i in d_id["issues"]], ["CHX-8", "MOC-3"])

        # 2. Normal keyword search excludes archived by default; --include-archived includes it
        r_kw = json.loads(self.run_cli("search", "ssh", "--json").stdout)
        self.assertEqual([i["id"] for i in r_kw["issues"]], ["CHX-1"])

        r_kw_arch = json.loads(self.run_cli("search", "ssh", "--include-archived", "--json").stdout)
        self.assertEqual([i["id"] for i in r_kw_arch["issues"]], ["CHX-8", "CHX-1"])

        # 3. Multi-word AND vs --any OR
        r_and = json.loads(self.run_cli("search", "tunnel", "proxy", "--json").stdout)
        self.assertEqual([i["id"] for i in r_and["issues"]], ["CHX-1"])

        r_and_miss = json.loads(self.run_cli("search", "tunnel", "cookie", "--json").stdout)
        self.assertEqual(r_and_miss["issues"], [])

        r_or = json.loads(self.run_cli("search", "tunnel", "cookie", "--any", "--json").stdout)
        self.assertEqual([i["id"] for i in r_or["issues"]], ["CHX-1", "MOC-4"])

        # 4. --team, --default-team / --team default, --project, --milestone, --label, --status-type
        r_team = json.loads(self.run_cli("search", "--team", "moc", "--json").stdout)
        self.assertEqual([i["id"] for i in r_team["issues"]], ["MOC-3", "MOC-4"])

        r_def_team = json.loads(self.run_cli("search", "--default-team", "--open", "--json").stdout)
        self.assertEqual([i["id"] for i in r_def_team["issues"]], ["CHX-1", "CHX-2"])

        r_def_alias = json.loads(self.run_cli("search", "--team", "default", "--open", "--json").stdout)
        self.assertEqual([i["id"] for i in r_def_alias["issues"]], ["CHX-1", "CHX-2"])

        no_team_cfg = self.tmp_dir / "no_team_cfg.json"
        no_team_cfg.write_text(json.dumps({"index_dir": str(self.index_dir)}), encoding="utf-8")
        r_no_def = self.run_cli(
            "search", "--default-team", "--config", str(no_team_cfg), use_default_cfg=False
        )
        self.assertEqual(r_no_def.returncode, 1)
        self.assertIn("default_team is not configured", r_no_def.stderr)

        r_proj = json.loads(self.run_cli("search", "--project", "comfyui", "--milestone", "followup", "--json").stdout)
        self.assertEqual([i["id"] for i in r_proj["issues"]], ["CHX-1", "CHX-2"])

        r_lbl = json.loads(self.run_cli("search", "--label", "auth", "--json").stdout)
        self.assertEqual([i["id"] for i in r_lbl["issues"]], ["MOC-4"])

        r_st = json.loads(self.run_cli("search", "--status-type", "completed,canceled", "--json").stdout)
        self.assertEqual([i["id"] for i in r_st["issues"]], ["CHX-5", "CHX-6"])

        # 5. --open includes triage|backlog|unstarted|started and excludes completed|canceled|duplicate + archived
        r_open = json.loads(self.run_cli("search", "--open", "--include-archived", "--json").stdout)
        self.assertEqual([i["id"] for i in r_open["issues"]], ["CHX-1", "CHX-2", "MOC-3", "MOC-4"])

        # 6. Text header + TSV + --desc + --limit
        r_tsv = self.run_cli("search", "--team", "MOC", "--desc", "--limit", "1")
        self.assertEqual(r_tsv.returncode, 0)
        lines = r_tsv.stdout.splitlines()
        self.assertTrue(lines[0].startswith("# index: FRESH ("))
        self.assertIn("matched=2/8, returned=1", lines[0])
        self.assertEqual(
            lines[1],
            "MOC-3\tMOC\tTodo\tmochan-skills\tUnstarted linear cli\tmulti team index",
        )

        # Negative --limit errors cleanly
        self.assertEqual(self.run_cli("search", "--limit", "-1").returncode, 2)

    def test_mark_archived_and_unarchive_updates_meta_counts(self) -> None:
        seed = self.tmp_dir / "seed.json"
        seed.write_text(
            json.dumps(
                [
                    {"id": "CHX-1", "title": "One", "statusType": "started", "updatedAt": "2026-11-25T02:00:00Z"},
                    {"id": "MOC-2", "title": "Two", "statusType": "triage", "updatedAt": "2026-11-25T01:00:00Z"},
                ]
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("upsert", "--rebuild", str(seed)).returncode, 0)

        r_arch = self.run_cli("mark-archived", "chx-1", "MISSING-99")
        self.assertEqual(r_arch.returncode, 0)
        self.assertIn("WARNING", r_arch.stderr)
        self.assertIn("MISSING-99", r_arch.stderr)

        st_after = json.loads(self.run_cli("status", "--json").stdout)
        self.assertEqual(st_after["total"], 2)
        self.assertEqual(st_after["archived"], 1)
        self.assertEqual(st_after["open"], 1)

        r_unarch = self.run_cli("mark-archived", "CHX-1", "--unarchive")
        self.assertEqual(r_unarch.returncode, 0)
        st_restored = json.loads(self.run_cli("status", "--json").stdout)
        self.assertEqual(st_restored["archived"], 0)
        self.assertEqual(st_restored["open"], 2)

    def test_symlink_resolves_skill_root_config_and_env_override(self) -> None:
        # Build an isolated skill tree in tmp_dir to verify Path(__file__).resolve().parent.parent
        fake_skill = self.tmp_dir / "skill_copy"
        fake_scripts = fake_skill / "scripts"
        fake_scripts.mkdir(parents=True)
        copied_script = fake_scripts / "linear-idx"
        shutil.copy2(SCRIPT_PATH, copied_script)
        copied_script.chmod(0o755)

        sym_index_dir = self.tmp_dir / "symlink_idx"
        (fake_skill / "config.local.json").write_text(
            json.dumps(
                {
                    "workspace": "sym-ws",
                    "default_team": "SYM",
                    "index_dir": str(sym_index_dir),
                    "stale_hours": 12,
                }
            ),
            encoding="utf-8",
        )

        bin_dir = self.tmp_dir / "bin"
        bin_dir.mkdir()
        symlink_exe = bin_dir / "linear-idx"
        symlink_exe.symlink_to(copied_script)

        res = self.run_cli("status", "--json", use_default_cfg=False, exe=symlink_exe)
        self.assertEqual(res.returncode, 0, res.stderr)
        info = json.loads(res.stdout)
        self.assertEqual(info["default_team"], "SYM")
        self.assertEqual(info["index_dir"], str(sym_index_dir))

        # Verify LINEAR_INDEX_DIR env override and subcommand --index-dir override
        env_idx = self.tmp_dir / "env_idx"
        res_env = self.run_cli(
            "status",
            "--json",
            use_default_cfg=False,
            exe=symlink_exe,
            extra_env={"LINEAR_INDEX_DIR": str(env_idx)},
        )
        self.assertEqual(json.loads(res_env.stdout)["index_dir"], str(env_idx))

        cli_idx = self.tmp_dir / "cli_idx"
        res_cli = self.run_cli(
            "status",
            "--json",
            "--index-dir",
            str(cli_idx),
            use_default_cfg=False,
            exe=symlink_exe,
            extra_env={"LINEAR_INDEX_DIR": str(env_idx)},
        )
        self.assertEqual(json.loads(res_cli.stdout)["index_dir"], str(cli_idx))

        # Verify zero-config defaults when config.local.json is absent
        (fake_skill / "config.local.json").unlink()
        res_defaults = self.run_cli("status", "--json", use_default_cfg=False, exe=symlink_exe)
        self.assertEqual(res_defaults.returncode, 0)
        defaults_info = json.loads(res_defaults.stdout)
        self.assertIsNone(defaults_info["default_team"])
        self.assertEqual(
            defaults_info["index_dir"],
            str(Path("~/.claude/linear-index/workspace").expanduser()),
        )


if __name__ == "__main__":
    unittest.main()
