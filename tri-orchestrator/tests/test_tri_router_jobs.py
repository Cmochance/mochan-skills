import importlib.util
from pathlib import Path
import sys
import threading
import time
import unittest

MODULE_PATH = Path(__file__).resolve().parent.parent / "server" / "tri_router_mcp.py"
SPEC = importlib.util.spec_from_file_location("tri_router_mcp", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
tri = importlib.util.module_from_spec(SPEC)
sys.modules["tri_router_mcp"] = tri
SPEC.loader.exec_module(tri)

GUARD_PATH = Path(__file__).resolve().parent.parent / "scripts" / "readonly-guard.py"
GUARD_SPEC = importlib.util.spec_from_file_location("readonly_guard", GUARD_PATH)
assert GUARD_SPEC is not None and GUARD_SPEC.loader is not None
guard = importlib.util.module_from_spec(GUARD_SPEC)
sys.modules["readonly_guard"] = guard
GUARD_SPEC.loader.exec_module(guard)


class TriRouterJobsTest(unittest.TestCase):
    def test_fast_job_completes_within_window(self) -> None:
        jm = tri.JobManager()

        def fast_handler(args: dict, ctx: tri.CancelContext) -> tuple[str, bool]:
            ctx.emit_progress(1, 1, "Done fast")
            return f"ok:{args.get('cwd')}", False

        job = jm.start_job("neon_analyze", {"cwd": "/tmp"}, fast_handler)
        finished = job.done_event.wait(timeout=2.0)
        self.assertTrue(finished)
        snap = job.snapshot()
        self.assertEqual(snap["status"], "completed")
        self.assertEqual(snap["result_text"], "ok:/tmp")
        self.assertFalse(snap["result_is_error"])

    def test_slow_job_hands_off_at_window_then_completes_on_await(self) -> None:
        jm = tri.JobManager()
        release = threading.Event()

        def slow_handler(args: dict, ctx: tri.CancelContext) -> tuple[str, bool]:
            ctx.emit_progress(1, 2, "Phase 1: Neon implementing...")
            release.wait(timeout=2.0)
            ctx.emit_progress(2, 2, "Phase 2: Carbon review passed")
            return "final-closed-loop-report", False

        job = jm.start_job("execute_with_review", {"cwd": "/tmp"}, slow_handler)
        # First window expires before release
        finished_1 = job.done_event.wait(timeout=0.05)
        self.assertFalse(finished_1)
        running_msg = jm.format_running(job)
        self.assertIn("Status:** `RUNNING`", running_msg)
        self.assertIn(job.job_id, running_msg)
        self.assertIn("await_pipeline", running_msg)

        # Let background job complete and await it
        release.set()
        finished_2 = job.done_event.wait(timeout=2.0)
        self.assertTrue(finished_2)
        snap = job.snapshot()
        self.assertEqual(snap["status"], "completed")
        self.assertEqual(snap["result_text"], "final-closed-loop-report")
        self.assertFalse(ctx_is_cancelled := job.cancel_ctx.cancelled.is_set())

    def test_cancel_pipeline_aborts_running_job_and_handles_missing(self) -> None:
        jm = tri.JobManager()
        started = threading.Event()

        def blocking_handler(args: dict, ctx: tri.CancelContext) -> tuple[str, bool]:
            started.set()
            while not ctx.cancelled.is_set():
                time.sleep(0.02)
            return "cancelled", True

        job = jm.start_job("execute_with_review", {"cwd": "/tmp"}, blocking_handler)
        self.assertTrue(started.wait(timeout=1.0))

        msg, is_err = jm.cancel_job(job.job_id)
        self.assertFalse(is_err)
        self.assertIn("Cancelled background job", msg)
        self.assertTrue(job.cancel_ctx.cancelled.is_set())
        self.assertTrue(job.done_event.wait(timeout=1.0))
        self.assertEqual(job.snapshot()["status"], "cancelled")

        miss_msg, miss_err = jm.cancel_job("tri-nonexistent")
        self.assertTrue(miss_err)
        self.assertIn("Unknown job_id", miss_msg)

    def test_cancel_context_link_target_before_and_after_cancel(self) -> None:
        # Cancel happens BEFORE link_target (race window simulation)
        wait_ctx_1 = tri.CancelContext(req_id="r1")
        job_ctx_1 = tri.CancelContext(req_id="j1")
        wait_ctx_1.cancel()
        wait_ctx_1.link_target(job_ctx_1)
        self.assertTrue(job_ctx_1.cancelled.is_set())

        # Cancel happens AFTER link_target
        wait_ctx_2 = tri.CancelContext(req_id="r2")
        job_ctx_2 = tri.CancelContext(req_id="j2")
        wait_ctx_2.link_target(job_ctx_2)
        self.assertFalse(job_ctx_2.cancelled.is_set())
        wait_ctx_2.cancel()
        self.assertTrue(job_ctx_2.cancelled.is_set())

    def test_readonly_guard_blocks_rg_pre_and_git_ext_diff_and_env(self) -> None:
        self.assertTrue(guard.is_safe_readonly_shell("rg -n 'foo' src")[0])
        self.assertTrue(guard.is_safe_readonly_shell("git --no-pager diff -- '*.py'")[0])

        for bad_cmd in (
            "rg --pre sh pattern src",
            "rg --pre=sh pattern src",
            "git diff --ext-diff HEAD",
            "GIT_EXTERNAL_DIFF=/tmp/evil git diff",
            "GIT_PAGER=sh git log -n 5",
            "PAGER=sh git show HEAD",
        ):
            ok, _reason = guard.is_safe_readonly_shell(bad_cmd)
            self.assertFalse(ok, f"Expected blocked in readonly mode: {bad_cmd}")


if __name__ == "__main__":
    unittest.main()
