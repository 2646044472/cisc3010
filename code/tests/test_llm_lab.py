import collections
import json
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

from llm_lab.backend import Simulator
from llm_lab.common import TERMINAL, token_for, validate_request
from llm_lab.experiment import percentile
from llm_lab.gateway import Gateway, WorkerPool
from llm_lab.worker import Engine, Job
from llm_lab.check import check_run
from llm_lab.admission import Admission, AdmissionError


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine("test-worker", Simulator())
        self.engine.configure({"slots": 2, "speed": 0.25})

    def tearDown(self):
        self.engine.stop.set()
        self.engine.thread.join(timeout=3)
        self.assertFalse(self.engine.thread.is_alive())

    def job(self, rid, maximum=12, prompt="hello world"):
        return self.engine.submit({"request_id": rid, "max_tokens": maximum, "prompt": prompt})

    def test_execution_observations_match_trace_and_reset(self):
        self.engine.stop.set()
        self.engine.thread.join(timeout=3)
        self.engine.backend = types.SimpleNamespace(
            name="cpu-model", model_id="test", revision="test",
            iterate=lambda pieces, execution: [None for _ in pieces])
        saved = []
        self.engine.iteration_trace.write = lambda run_id, event: saved.append(event)
        decode = Job("decode", "private prompt", 8, None, 4)
        prefill = Job("prefill", "private prompt", 8, None, 12)
        cfg = self.engine.config | {"prefill_chunk": 5}
        for _ in range(40):
            prefill.remaining_prefill = 12
            self.engine.real_iteration([decode, prefill], cfg)
        snapshot = self.engine.snapshot()
        recent = snapshot["recent_iterations"]
        self.assertEqual(len(recent), 32)
        self.assertEqual(recent[-1], saved[-1])
        self.assertEqual(recent[-1]["phases"], ["decode", "prefill"])
        self.assertEqual(recent[-1]["piece_tokens"], [1, 5])
        self.assertEqual(recent[-1]["prefill_tokens"], 5)
        self.assertEqual(snapshot["last_mixed_iteration"], recent[-1])
        self.assertNotIn("private prompt", json.dumps(recent))
        self.engine.configure({})
        self.assertEqual(self.engine.snapshot()["recent_iterations"], [])
        self.assertIsNone(self.engine.snapshot()["last_mixed_iteration"])

    def drain(self, job):
        events = []
        while True:
            event = job.output.get(timeout=4)
            events.append(event)
            if event["event"] in TERMINAL:
                return events

    def test_output_is_ordered_and_matches_reference(self):
        job = self.job("output", 20)
        events = self.drain(job)
        tokens = [e for e in events if e["event"] == "token"]
        self.assertEqual([e["seq"] for e in tokens], list(range(20)))
        self.assertEqual("".join(e["delta"] for e in tokens), "".join(token_for(job.prompt, i) for i in range(20)))
        self.assertEqual(events[-1]["event"], "completed")

    def test_static_batch_holds_admission_until_long_request_finishes(self):
        self.engine.configure({"scheduling": "static"})
        long = self.job("long", 70)
        short = self.job("short", 2)
        self.drain(short)
        newcomer = self.job("new", 2)
        long_events = self.drain(long)
        self.drain(newcomer)
        start = next(e["t"] for e in self.engine.timeline if e["request_id"] == "new" and e["event"] == "started")
        self.assertGreaterEqual(start, long_events[-1]["t"])

    def test_continuous_admission_uses_freed_slot(self):
        long = self.job("long", 70)
        short = self.job("short", 2)
        self.drain(short)
        newcomer = self.job("new", 2)
        new_events = self.drain(newcomer)
        long_events = self.drain(long)
        self.assertLess(new_events[-1]["t"], long_events[-1]["t"])

    def test_active_cancellation_releases_kv_reservation(self):
        self.engine.configure({"slots": 1})
        first = self.job("cancel", 120)
        while first.output.get(timeout=4)["event"] != "token":
            pass
        self.assertTrue(self.engine.cancel_job("cancel"))
        self.assertEqual(self.drain(first)[-1]["event"], "cancelled")
        second = self.job("after", 2)
        self.assertEqual(self.drain(second)[-1]["event"], "completed")
        self.assertEqual(self.engine.snapshot()["kv_reserved"], 0)

    def test_queued_cancellation_releases_queue(self):
        self.engine.configure({"slots": 1})
        first = self.job("first", 40)
        second = self.job("queued", 2)
        self.assertTrue(self.engine.cancel_job("queued"))
        self.assertEqual(self.drain(second)[-1]["event"], "cancelled")
        self.drain(first)
        self.assertEqual(self.engine.snapshot()["queued"], 0)

    def test_kv_budget_serializes_requests_without_overcommit(self):
        self.engine.configure({"kv_budget": 128, "slots": 2})
        first = self.job("one", 70)
        second = self.job("two", 70)
        self.drain(first)
        self.drain(second)
        started = [e for e in self.engine.timeline if e["event"] == "started"]
        complete = next(e for e in self.engine.timeline if e["request_id"] == "one" and e["event"] == "completed")
        self.assertGreaterEqual(started[1]["t"], complete["t"])

    def test_prefix_cache_requires_exact_prefix_and_is_bounded(self):
        self.engine.configure({"prefix_cache": True, "cache_budget": 32})
        prompt = " ".join("prefix" + str(i) for i in range(40))
        self.drain(self.job("miss", 2, prompt))
        hit = self.job("hit", 2, prompt + " suffix")
        self.drain(hit)
        self.assertEqual(hit.cache_hit, 32)
        changed = self.job("changed", 2, "different " + prompt)
        self.drain(changed)
        self.assertEqual(changed.cache_hit, 0)
        self.assertLessEqual(self.engine.snapshot()["cache_tokens"], 32)

    def test_duplicate_identifier_and_oversize_rejected(self):
        job = self.job("same", 2)
        with self.assertRaises(ValueError):
            self.job("same", 2)
        self.drain(job)
        self.engine.configure({"kv_budget": 128})
        with self.assertRaises(ValueError):
            self.job("big", 200)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.gateway = Gateway(types.SimpleNamespace(urls={}, backend="simulator"))
        self.gateway.stop_event.set()
        self.gateway.monitor.join(timeout=1)
        self.gateway.health = {wid: {"id": wid, "healthy": True} for wid in ["worker-1", "worker-2"]}
        self.gateway.admission.PLANS = Admission.PLANS | {"demo": {"rate": 200, "burst": 200, "inflight": 128, "token_budget": 100000}}

    def request(self, rid, maximum=40):
        return {"request_id": rid, "prompt": "a test prompt", "max_tokens": maximum, "run_id": None}

    def test_simultaneous_assignments_balance_outstanding_counts(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=12) as executor:
            records = list(executor.map(lambda i: self.gateway.assign(self.request("parallel" + str(i))), range(40)))
        self.assertEqual(collections.Counter(r["worker"] for r in records), {"worker-1": 20, "worker-2": 20})

    def test_unhealthy_worker_is_excluded(self):
        self.gateway.health["worker-1"]["healthy"] = False
        self.assertEqual(self.gateway.assign(self.request("healthy"))["worker"], "worker-2")

    def test_four_worker_pool_balances_and_excludes_failed_replica(self):
        from concurrent.futures import ThreadPoolExecutor
        self.gateway.health = {f"worker-{i}": {"id": f"worker-{i}", "healthy": True} for i in range(1, 5)}
        with ThreadPoolExecutor(max_workers=12) as executor:
            records = list(executor.map(lambda i: self.gateway.assign(self.request("four" + str(i))), range(40)))
        self.assertEqual(collections.Counter(r["worker"] for r in records), {f"worker-{i}": 10 for i in range(1, 5)})
        self.gateway.health["worker-1"]["healthy"] = False
        later = [self.gateway.assign(self.request("survivor" + str(i))) for i in range(9)]
        self.assertEqual(collections.Counter(r["worker"] for r in later), {f"worker-{i}": 3 for i in range(2, 5)})

    def test_pool_rejects_invalid_counts_threads_and_port_ranges(self):
        for count in (0, 17, True):
            with self.assertRaises(ValueError):
                WorkerPool(8800, "simulator", None, worker_count=count)
        with self.assertRaises(ValueError):
            WorkerPool(65533, "simulator", None, worker_count=4)
        with self.assertRaises(ValueError):
            WorkerPool(8800, "simulator", None, threads=0)

    def test_gateway_bind_failure_does_not_launch_or_leak_model_processes(self):
        from unittest.mock import patch
        from llm_lab.gateway import serve_gateway
        with patch("llm_lab.gateway.ThreadingHTTPServer", side_effect=OSError("port occupied")), \
             patch.object(WorkerPool, "start") as start, patch.object(WorkerPool, "close") as close:
            with self.assertRaisesRegex(OSError, "port occupied"):
                serve_gateway(port=8990, backend="simulator", worker_count=4)
        start.assert_not_called()
        close.assert_called_once()

    def test_work_estimator_uses_remaining_requested_budget(self):
        self.gateway.policy = "token_work"
        a = self.gateway.assign(self.request("long", 120))
        b = self.gateway.assign(self.request("short", 16))
        self.assertNotEqual(a["worker"], b["worker"])
        c = self.gateway.assign(self.request("new", 16))
        self.assertEqual(c["worker"], b["worker"])


class InputTests(unittest.TestCase):
    def test_conversation_must_end_with_matching_user_prompt(self):
        base = {"request_id": "conversation", "prompt": "hello", "max_tokens": 12}
        for messages in [[{"role": "assistant", "content": "hello"}], [{"role": "user", "content": "different"}], [{"role": "tool", "content": "hello"}]]:
            with self.assertRaises(ValueError):
                validate_request(base | {"messages": messages})
        parsed = validate_request(base | {"messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(parsed["messages"][0]["content"], "hello")

    def test_path_escape_and_boolean_lengths_rejected(self):
        for rid, length in [("../escape", 2), ("ok", True)]:
            with self.assertRaises(ValueError):
                validate_request({"request_id": rid, "prompt": "hello", "max_tokens": length})

    def test_percentile_interpolates_and_handles_empty_samples(self):
        self.assertEqual(percentile([10, 20], .95), 19.5)
        self.assertIsNone(percentile([], .95))


class AdmissionTests(unittest.TestCase):
    def test_token_bucket_refill_and_client_isolation(self):
        admission = Admission()
        for _ in range(6):
            admission.admit("client-a", 10, [], clock=0)
        with self.assertRaises(AdmissionError):
            admission.admit("client-a", 10, [], clock=0)
        admission.admit("client-b", 10, [], clock=0)
        admission.admit("client-a", 10, [], clock=.5)

    def test_concurrency_and_budget_release_at_terminal_outcome(self):
        admission = Admission()
        records = [{"tenant": "client-a", "status": "active", "reservation": 100} for _ in range(4)]
        with self.assertRaisesRegex(AdmissionError, "client_concurrency_limit"):
            admission.admit("client-a", 10, records, clock=0)
        records[0]["status"] = "cancelled"
        admission.admit("client-a", 10, records, clock=1)
        with self.assertRaisesRegex(AdmissionError, "client_token_budget"):
            admission.admit("client-b", 3000, [], clock=1)


class EvidenceTests(unittest.TestCase):
    def test_checker_includes_fourth_replica_and_requires_its_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            request = {"request_id": "fourth", "prompt": "hello", "max_tokens": 1}
            row = {"request_id": "fourth", "status": "completed", "sequences": [0], "text": token_for("hello", 0)}
            workers = [{"id": f"worker-{i}", "healthy": True} for i in range(1, 5)]
            for name, value in [("workload", [request]), ("config", {"backend": "simulator", "worker_start": workers}),
                                ("requests", [row]), ("cleanup", {"outstanding": 0, "workers": workers})]:
                (folder / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
            gateway = [{"request_id": "fourth", "worker": "worker-4", "event": "assigned"},
                       {"request_id": "fourth", "event": "completed"}]
            events = [{"request_id": "fourth", "worker": "worker-4", "event": "token", "seq": 0},
                      {"request_id": "fourth", "worker": "worker-4", "event": "completed"}]
            (folder / "gateway.jsonl").write_text("\n".join(map(json.dumps, gateway)), encoding="utf-8")
            evidence = folder / "worker-4.jsonl"
            evidence.write_text("\n".join(map(json.dumps, events)), encoding="utf-8")
            self.assertTrue(check_run(folder)["passed"])
            evidence.unlink()
            self.assertFalse(check_run(folder)["passed"])

    def test_checker_detects_corrupted_output_and_missing_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            request = {"request_id": "one", "prompt": "hello", "max_tokens": 2}
            rows = [{"request_id": "one", "status": "completed", "sequences": [0, 1],
                     "text": token_for("hello", 0) + token_for("hello", 1)}]
            gateway = [{"request_id": "one", "event": "assigned", "worker": "worker-1"},
                       {"request_id": "one", "event": "completed"}]
            worker = [{"request_id": "one", "worker": "worker-1", "event": "token", "seq": i} for i in range(2)]
            worker.append({"request_id": "one", "worker": "worker-1", "event": "completed"})
            for name, value in [("workload", [request]), ("config", {"backend": "simulator"}), ("requests", rows),
                                ("cleanup", {"outstanding": 0, "workers": []})]:
                (folder / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
            (folder / "gateway.jsonl").write_text("\n".join(json.dumps(e) for e in gateway), encoding="utf-8")
            (folder / "worker-1.jsonl").write_text("\n".join(json.dumps(e) for e in worker), encoding="utf-8")
            self.assertTrue(check_run(folder)["passed"])
            rows[0]["text"] = "corrupted output"
            (folder / "requests.json").write_text(json.dumps(rows), encoding="utf-8")
            self.assertFalse(check_run(folder)["passed"])
            rows[0]["text"] = token_for("hello", 0) + token_for("hello", 1)
            (folder / "requests.json").write_text(json.dumps(rows), encoding="utf-8")
            (folder / "gateway.jsonl").write_text(json.dumps(gateway[0]), encoding="utf-8")
            self.assertFalse(check_run(folder)["passed"])


if __name__ == "__main__":
    unittest.main()
