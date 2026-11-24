"""Unit tests for x-post-reader routing, safety guards, concurrency, and formatting."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import tiers
import formatter


def _load_x_read_module():
    path = str(SCRIPTS_DIR / "x-read")
    loader = importlib.machinery.SourceFileLoader("x_read_cli", path)
    spec = importlib.util.spec_from_loader("x_read_cli", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


x_read_cli = _load_x_read_module()


def _sample_post(
    pid: str = "100",
    *,
    author_id: str = "1",
    handle: str = "alice",
    text: str = "hello",
    replies: int = 0,
    replying_to: str | None = None,
    replying_to_status: str | None = None,
    article: tiers.ArticleData | None = None,
    is_retweet: bool = False,
) -> tiers.PostItem:
    return tiers.PostItem(
        id=pid,
        url=f"https://x.com/{handle}/status/{pid}",
        author_id=author_id,
        author_handle=handle,
        author_name=handle.title(),
        created_at="2026-11-24T10:00:00Z",
        text=text,
        is_note_tweet=len(text) > 280,
        article=article,
        replying_to=replying_to,
        replying_to_status=replying_to_status,
        stats={"replies": replies, "retweets": 1, "likes": 2},
        is_retweet=is_retweet,
    )


def _base_cfg(tmpdir: str, **overrides) -> dict:
    cfg = {
        "proxy": None,
        "cache_dir": str(Path(tmpdir) / "cache"),
        "output_spill_dir": str(Path(tmpdir) / "out"),
        "state_dir": str(Path(tmpdir) / "state"),
        "cache_ttl_seconds": 3600,
        "inline_max_chars": 16000,
        "tier1": {"api_base": "https://api.fxtwitter.com", "max_upstream_walk": 20, "timeout_seconds": 10},
        "tier2": {"enabled": True, "jina_base": "https://r.jina.ai", "jina_timeout_seconds": 30, "jina_api_key": ""},
        "tier3": {
            "enabled": True,
            "twitter_bin": str(Path(tmpdir) / "twitter"),
            "cookie_source": "config_file",
            "auth_token": "",
            "ct0": "",
            "browser_name": "",
            "max_thread_tweets": 50,
            "min_interval_seconds": 0,
            "circuit_breaker_cooldown_seconds": 900,
            "timeout_seconds": 50,
        },
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def _make_fake_twitter(tmpdir: str) -> Path:
    bin_path = Path(tmpdir) / "twitter"
    bin_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(bin_path, 0o755)
    return bin_path


class TestUrlParsingAndHttp(unittest.TestCase):
    def test_status_variants_including_statuses_and_ascii_only(self) -> None:
        for raw, eid, euser in [
            ("https://x.com/karpathy/status/1890001?s=20", "1890001", "karpathy"),
            ("https://twitter.com/jack/statuses/20/photo/1", "20", "jack"),
            ("https://fxtwitter.com/i/web/status/999", "999", "i"),
            ("1234567890", "1234567890", "i"),
        ]:
            spec = tiers.parse_x_target(raw)
            self.assertEqual(spec.tweet_id, eid)
            self.assertEqual(spec.user_hint, euser)
            self.assertFalse(spec.is_article_url)

        with self.assertRaises(ValueError):
            tiers.parse_x_target("١٢٣٤٥")  # non-ASCII Unicode digits rejected

    def test_article_variants(self) -> None:
        for raw, eid, euser in [
            ("https://x.com/alice/article/555666", "555666", "alice"),
            ("https://x.com/i/articles/777888?t=1", "777888", "i"),
        ]:
            spec = tiers.parse_x_target(raw)
            self.assertEqual(spec.tweet_id, eid)
            self.assertEqual(spec.user_hint, euser)
            self.assertTrue(spec.is_article_url)

    def test_rejects_non_x_url(self) -> None:
        with self.assertRaises(ValueError):
            tiers.parse_x_target("https://example.com/user/status/123")

    def test_http_get_converts_timeout_and_fxembed_v2_status_key(self) -> None:
        with patch.object(tiers.urllib.request, "build_opener") as mock_opener:
            mock_opener.return_value.open.side_effect = TimeoutError("read timed out")
            with self.assertRaises(tiers.TierError) as ctx:
                tiers._http_get_text("https://api.fxtwitter.com/jack/status/20")
            self.assertEqual(ctx.exception.code, "network_error")

        v2_body = json.dumps({"code": 200, "status": {"id": "20", "text": "hello v2", "author": {"screen_name": "jack"}}})
        with patch.object(tiers, "_http_get_text", return_value=(200, v2_body)):
            post = tiers.fetch_tier1_fxembed(tiers.parse_x_target("https://x.com/jack/status/20"), _base_cfg("/tmp"))
            self.assertEqual(post.text, "hello v2")


class TestThreadHeuristicsAndValidation(unittest.TestCase):
    def test_thread_head_detection(self) -> None:
        self.assertTrue(tiers.is_likely_thread_head(_sample_post(text="1/8 Why agents fail", replies=4))[0])
        self.assertTrue(tiers.is_likely_thread_head(_sample_post(text="Deep dive 🧵", replies=2))[0])
        self.assertTrue(tiers.is_likely_thread_head(_sample_post(text="A thread: key takeaways", replies=1))[0])
        self.assertTrue(tiers.is_likely_thread_head(_sample_post(text="总结几个核心点：", replies=3))[0])
        self.assertFalse(tiers.is_likely_thread_head(_sample_post(text="Just shipped v1.0 today!", replies=12))[0])

    def test_jina_login_wall_footer_vs_real_wall_and_dead_page(self) -> None:
        # Pure login wall rejected
        ok1, _ = tiers.validate_not_login_wall("Don't miss what's happening. People on X are the first to know.")
        self.assertFalse(ok1)

        # Curly-apostrophe login wall rejected even with Jina preamble
        shell = (
            "Title: X\nURL Source: https://x.com/a/status/1\n\nMarkdown Content:\n"
            "Don’t miss what’s happening\nPeople on X are the first to know.\nSign in to X"
        )
        ok_shell, reason_shell = tiers.validate_not_login_wall(shell)
        self.assertFalse(ok_shell, reason_shell)

        # Dead page with Jina header rejected
        dead = "Title: X\nURL Source: https://x.com/a/status/1\n\nMarkdown Content:\nHmm...this page doesn't exist. Try searching for something else."
        ok_dead, reason_dead = tiers.validate_not_login_wall(dead)
        self.assertFalse(ok_dead, reason_dead)

        # Long real article (>800 chars) with trailing X footer banner is accepted!
        long_article = "# Deep Engineering Post\n\n" + ("Detailed systems content paragraph. " * 35)
        with_footer = f"{long_article}\n\nDon't miss what's happening\nPeople on X are the first to know."
        ok_long, reason_long = tiers.validate_not_login_wall(with_footer)
        self.assertTrue(ok_long, reason_long)


class TestTier3SafetyAndCircuitBreaker(unittest.TestCase):
    def test_config_file_ignores_env_and_never_invokes_subprocess_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_fake_twitter(tmpdir)
            cfg = _base_cfg(tmpdir)
            with patch.dict(os.environ, {"TWITTER_AUTH_TOKEN": "env_tok", "TWITTER_CT0": "env_ct0"}, clear=True):
                ready, reason = tiers.check_tier3_readiness(cfg)
                self.assertFalse(ready)
                self.assertEqual(reason, "alt_account_cookie_not_configured")
                with patch.object(tiers.subprocess, "run") as mock_run:
                    with self.assertRaises(tiers.TierError):
                        tiers.fetch_tier3_thread("100", cfg)
                    mock_run.assert_not_called()

    def test_browser_cookie3_stub_isolates_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_fake_twitter(tmpdir)
            cfg = _base_cfg(tmpdir, tier3={"auth_token": "tok123", "ct0": "ct0123"})
            with patch.dict(os.environ, {"TWITTER_BROWSER": "chrome", "PYTHONSAFEPATH": "1"}, clear=True):
                env = tiers._build_tier3_env(cfg)
                self.assertEqual(env["TWITTER_AUTH_TOKEN"], "tok123")
                self.assertEqual(env["TWITTER_CT0"], "ct0123")
                self.assertNotIn("TWITTER_BROWSER", env)
                self.assertNotIn("PYTHONSAFEPATH", env)

                proc = subprocess.run(
                    [sys.executable, "-c", "import browser_cookie3; print(browser_cookie3.chrome(), browser_cookie3.arc())"],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(proc.stdout.strip(), "[] []")

    def test_circuit_breaker_ignores_snowflake_326_429_and_trips_on_real_rate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_fake_twitter(tmpdir)
            cfg = _base_cfg(tmpdir, tier3={"auth_token": "tok", "ct0": "ct0"})

            # Snowflake ID containing "326" & "429" with err_code=not_found must NOT trip breaker
            not_found_out = json.dumps({
                "ok": False,
                "error": {"code": "not_found", "message": "Tweet 1890326429001 has no article content"},
            })
            with patch.object(
                tiers.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(["twitter"], 1, stdout=not_found_out, stderr=""),
            ):
                with self.assertRaises(tiers.TierError) as ctx:
                    tiers.fetch_tier3_article("1890326429001", cfg)
                self.assertEqual(ctx.exception.code, "not_found")

            ready, _ = tiers.check_tier3_readiness(cfg)
            self.assertTrue(ready)

            # Real HTTP 429 / rate_limited must trip breaker
            rl_out = json.dumps({"ok": False, "error": {"code": "rate_limited", "message": "HTTP 429"}})
            with patch.object(
                tiers.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(["twitter"], 1, stdout=rl_out, stderr=""),
            ):
                with self.assertRaises(tiers.TierError):
                    tiers.fetch_tier3_thread("100", cfg)

            ready2, reason2 = tiers.check_tier3_readiness(cfg)
            self.assertFalse(ready2)
            self.assertTrue(reason2.startswith("circuit_breaker_open:"))

    def test_subprocess_timeout_and_string_error_converted_to_tier_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_fake_twitter(tmpdir)
            cfg = _base_cfg(tmpdir, tier3={"auth_token": "tok", "ct0": "ct0", "timeout_seconds": 5})

            with patch.object(tiers.subprocess, "run", side_effect=subprocess.TimeoutExpired(["twitter"], 5)):
                with self.assertRaises(tiers.TierError) as ctx:
                    tiers.fetch_tier3_thread("100", cfg)
                self.assertEqual(ctx.exception.code, "tier3_timeout")

            str_err = json.dumps({"ok": False, "error": "unexpected string error"})
            with patch.object(
                tiers.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(["twitter"], 1, stdout=str_err, stderr=""),
            ):
                with self.assertRaises(tiers.TierError) as ctx2:
                    tiers.fetch_tier3_thread("100", cfg)
                self.assertEqual(ctx2.exception.code, "tier3_failed")
                self.assertIn("unexpected string error", str(ctx2.exception))


class TestRoutingMatrixAndFlows(unittest.TestCase):
    def test_resolve_post_routing_and_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_fake_twitter(tmpdir)
            cfg = _base_cfg(tmpdir, tier3={"auth_token": "tok", "ct0": "ct0"})

            # 1. Single post falls back Tier 1 fail -> Tier 2 fail -> Tier 3 single
            t3_single = _sample_post("300", handle="alice", text="Protected or fallback single post")
            with patch.object(x_read_cli, "fetch_tier1_fxembed", side_effect=tiers.TierError("tier1_failed", "down")), \
                 patch.object(x_read_cli, "fetch_tier2_jina", side_effect=tiers.TierError("tier2_login_wall", "wall")), \
                 patch.object(x_read_cli, "fetch_tier3_thread", return_value=[t3_single]):
                res = x_read_cli.resolve_post("https://x.com/alice/status/300", config=cfg)
                self.assertEqual(res["tier_used"], "tier3:twitter-cli")
                self.assertEqual(res["post_type"], "single")
                self.assertEqual(res["completeness"], "full")

            # 2. Tier 1 HTTP 404 escalates to Tier 3 when configured (protected post)
            with patch.object(x_read_cli, "fetch_tier1_fxembed", side_effect=tiers.TierError("not_found", "404")), \
                 patch.object(x_read_cli, "fetch_tier3_thread", return_value=[t3_single]):
                res404 = x_read_cli.resolve_post("https://x.com/alice/status/300", config=cfg)
                self.assertEqual(res404["tier_used"], "tier3:twitter-cli")

            # 3. --tier 2 and --tier 3 never call Tier 1
            with patch.object(x_read_cli, "fetch_tier1_fxembed") as mock_t1, \
                 patch.object(x_read_cli, "fetch_tier2_jina", return_value="# Jina Body\n\n" + "Content " * 10):
                res_t2 = x_read_cli.resolve_post("https://x.com/alice/status/300", config=cfg, forced_tier="2")
                self.assertEqual(res_t2["tier_used"], "tier2:jina")
                mock_t1.assert_not_called()

            with patch.object(x_read_cli, "fetch_tier1_fxembed") as mock_t1, \
                 patch.object(x_read_cli, "fetch_tier3_thread", return_value=[t3_single]):
                res_t3 = x_read_cli.resolve_post("https://x.com/alice/status/300", config=cfg, mode="single", forced_tier="3")
                self.assertEqual(res_t3["post_type"], "single")
                mock_t1.assert_not_called()

            # 4. --thread --tier 2 raises unsupported_tier_for_mode
            with self.assertRaises(tiers.TierError) as ctx:
                x_read_cli.resolve_post("https://x.com/alice/status/300", config=cfg, mode="thread", forced_tier="2")
            self.assertEqual(ctx.exception.code, "unsupported_tier_for_mode")

            # 5. --single --include-replies 1 keeps post_type=single even if Tier 3 unconfigured
            cfg_no_t3 = _base_cfg(tmpdir)
            single_post = _sample_post("301", text="Plain single post", replies=3)
            with patch.object(x_read_cli, "fetch_tier1_fxembed", return_value=single_post):
                res_inc = x_read_cli.resolve_post("https://x.com/alice/status/301", config=cfg_no_t3, include_replies=1)
                self.assertEqual(res_inc["post_type"], "single")
                self.assertEqual(res_inc["completeness"], "full")

    def test_article_complex_blocks_and_all_tiers_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_fake_twitter(tmpdir)
            cfg = _base_cfg(tmpdir, tier3={"auth_token": "tok", "ct0": "ct0"})

            complex_art = tiers.ArticleData(
                title="Complex Art",
                blocks_markdown="Intro paragraph.",
                has_complex_blocks=True,
            )
            focal_art = _sample_post("400", handle="alice", text="Preview", article=complex_art)
            t3_art = _sample_post(
                "400",
                author_id="99",
                handle="alice",
                text="",
                article=tiers.ArticleData(title="Complex Art", blocks_markdown="Intro paragraph.", has_complex_blocks=False),
            )

            # Tier 2 fails -> Tier 3 returns partial_root_only because Tier 1 flagged atomic/complex blocks
            with patch.object(x_read_cli, "fetch_tier1_fxembed", return_value=focal_art), \
                 patch.object(x_read_cli, "fetch_tier2_jina", side_effect=tiers.TierError("tier2_login_wall", "wall")), \
                 patch.object(x_read_cli, "fetch_tier3_article", return_value=t3_art):
                res = x_read_cli.resolve_post("https://x.com/alice/status/400", config=cfg)
                self.assertEqual(res["tier_used"], "tier3:twitter-cli")
                self.assertEqual(res["completeness"], "partial_root_only")

            # Tier 2 & Tier 3 both fail -> Tier 1 fallback still marked partial_root_only
            with patch.object(x_read_cli, "fetch_tier1_fxembed", return_value=focal_art), \
                 patch.object(x_read_cli, "fetch_tier2_jina", side_effect=tiers.TierError("tier2_login_wall", "wall")), \
                 patch.object(x_read_cli, "fetch_tier3_article", side_effect=tiers.TierError("tier3_failed", "err")):
                res_t1 = x_read_cli.resolve_post("https://x.com/alice/status/400", config=cfg)
                self.assertEqual(res_t1["tier_used"], "tier1:fxembed")
                self.assertEqual(res_t1["completeness"], "partial_root_only")

            # /article/<id> when ALL tiers fail must raise TierError (never return empty exit 0!)
            with patch.object(x_read_cli, "fetch_tier1_fxembed", side_effect=tiers.TierError("not_found", "404")), \
                 patch.object(x_read_cli, "fetch_tier2_jina", side_effect=tiers.TierError("tier2_login_wall", "wall")), \
                 patch.object(x_read_cli, "fetch_tier3_article", side_effect=tiers.TierError("not_found", "404")):
                with self.assertRaises(tiers.TierError) as ctx:
                    x_read_cli.resolve_post("https://x.com/alice/article/401", config=cfg)
                self.assertEqual(ctx.exception.code, "all_tiers_failed")

            # /alice/article/402 when Tier 1 fails & Tier 3 succeeds preserves Tier 3 author_id & created_at
            with patch.object(x_read_cli, "fetch_tier1_fxembed", side_effect=tiers.TierError("not_found", "404")), \
                 patch.object(x_read_cli, "fetch_tier2_jina", side_effect=tiers.TierError("tier2_login_wall", "wall")), \
                 patch.object(x_read_cli, "fetch_tier3_article", return_value=t3_art):
                res_meta = x_read_cli.resolve_post("https://x.com/alice/article/402", config=cfg)
                self.assertEqual(res_meta["focal"].author_id, "99")
                self.assertEqual(res_meta["focal"].created_at, "2026-11-24T10:00:00Z")


class TestThreadReconstructionUpstreamAndCache(unittest.TestCase):
    def test_cross_author_reply_and_leading_mention_inside_self_thread(self) -> None:
        # Bob#100 -> Alice#200 -> Alice#201 ("@OpenAI released..." self-reply) -> Alice#202
        bob = _sample_post("100", author_id="1", handle="bob", text="Original question?")
        a200 = _sample_post("200", author_id="2", handle="alice", text="1/3 My reply", replying_to="bob", replying_to_status="100")
        a201 = _sample_post("201", author_id="2", handle="alice", text="@OpenAI just shipped this", replying_to="alice", replying_to_status="200")
        a202 = _sample_post("202", author_id="2", handle="alice", text="3/3 Final point", replying_to="alice", replying_to_status="201")
        a_comment = _sample_post("203", author_id="2", handle="alice", text="@charlie thanks", replying_to="charlie", replying_to_status="999")
        stranger = _sample_post("204", author_id="3", handle="charlie", text="Nice!")

        # Simulate twitter-cli output (lacks replying_to_status) + duplicate stranger entry
        t3_raw = [
            _sample_post("200", author_id="2", handle="alice", text="1/3 My reply"),
            _sample_post("201", author_id="2", handle="alice", text="@OpenAI just shipped this"),
            _sample_post("202", author_id="2", handle="alice", text="3/3 Final point"),
            _sample_post("203", author_id="2", handle="alice", text="@charlie thanks"),
            stranger,
            stranger,
        ]
        verify_map = {"201": a201, "202": a202, "203": a_comment}

        posts, replies, incomplete = formatter.reconstruct_self_thread(
            a200,
            [bob, a200],
            t3_raw,
            include_replies=5,
            verify_parent_fn=lambda p: verify_map.get(p.id),
        )
        self.assertFalse(incomplete)
        self.assertEqual([p.id for p in posts], ["100", "200", "201", "202"])
        self.assertEqual([r.id for r in replies], ["204"])  # deduplicated

        md = formatter.render_markdown(
            focal=a200,
            posts=posts,
            post_type="thread",
            tier_used="tier3:twitter-cli",
            completeness="full",
        )
        self.assertIn("## [1/4] @bob", md)
        self.assertIn("## [2/4] @alice", md)

    def test_walk_upstream_truncation_on_error_and_cycle(self) -> None:
        cfg = _base_cfg("/tmp", tier1={"max_upstream_walk": 5})
        leaf = _sample_post("10", replying_to="alice", replying_to_status="9")
        with patch.object(tiers, "fetch_tier1_fxembed", side_effect=tiers.TierError("tier1_failed", "err")):
            chain, truncated = tiers.walk_upstream_tier1(leaf, cfg)
            self.assertEqual([p.id for p in chain], ["10"])
            self.assertTrue(truncated)

        cyclic = _sample_post("10", replying_to="alice", replying_to_status="10")
        chain_cyc, truncated_cyc = tiers.walk_upstream_tier1(cyclic, cfg)
        self.assertEqual([p.id for p in chain_cyc], ["10"])
        self.assertTrue(truncated_cyc)

    def test_main_cache_only_full_respects_ttl_zero_and_private_spill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "cfg.json"
            cfg = _base_cfg(tmpdir, cache_ttl_seconds=0, inline_max_chars=120)
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            long_post = _sample_post("500", text="B" * 300)
            partial_res = {
                "focal": long_post,
                "posts": [long_post],
                "post_type": "thread",
                "tier_used": "tier1:fxembed",
                "completeness": "partial_root_only",
                "completeness_note": "Line1\nLine2",
                "extra_replies": [],
            }
            with patch.object(x_read_cli, "resolve_post", return_value=partial_res), \
                 patch.object(sys, "stdout", new_callable=io.StringIO) as buf:
                rc = x_read_cli.main(["https://x.com/alice/status/500", "--config", str(cfg_path)])
                self.assertEqual(rc, 0)
                out = buf.getvalue()
                self.assertIn("Full content saved to", out)
                self.assertIn("---\ntweet_id:", out)

            # Cache dir must have 0 entries (partial_root_only & ttl=0)
            cache_dir = Path(cfg["cache_dir"])
            self.assertFalse(cache_dir.exists() and list(cache_dir.iterdir()))
            spill_file = Path(cfg["output_spill_dir"]) / "500.md"
            self.assertTrue(spill_file.exists())
            self.assertEqual(spill_file.stat().st_mode & 0o777, 0o600)

            # Missing --config returns exit code 2
            with patch.object(sys, "stderr", new_callable=io.StringIO):
                rc_bad = x_read_cli.main(["https://x.com/alice/status/500", "--config", str(Path(tmpdir) / "missing.json")])
                self.assertEqual(rc_bad, 2)


if __name__ == "__main__":
    unittest.main()
