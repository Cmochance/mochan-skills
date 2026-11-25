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


if __name__ == "__main__":
    unittest.main()
