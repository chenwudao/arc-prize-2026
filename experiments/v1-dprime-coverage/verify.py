"""Check numerical parity, actual gate coverage, and both notebook branches."""
import ast
import collections
import heapq
import json
import logging
import math
import os
import sys
import threading
import time
import types
import unittest
from pathlib import Path

import scheduler

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "verification-fixtures"
scope = {"__name__": "verified_priority_inputs"}
module = types.ModuleType(scope["__name__"])
sys.modules[module.__name__] = module
exec(compile((FIXTURES / "priority_scheduler.py").read_text(), "priority_scheduler.py", "exec"),
     module.__dict__)
Snapshot = module.PrioritySnapshot

# Extract the authors' reference without running the notebook or installing a patch.
reference = types.ModuleType("reference_dprime")
exec(compile((FIXTURES / "reference-dprime.py").read_text(), "reference_dprime.py", "exec"),
     reference.__dict__)

# Use the real admission gate class, not a reimplementation of its ordering.
gate_node = next(n for n in ast.parse((FIXTURES / "tool_agent_gate.py").read_text()).body
                 if isinstance(n, ast.ClassDef) and n.name == "_PriorityGate")
gate_scope = dict(threading=threading, heapq=heapq, time=time, os=os, PrioritySnapshot=Snapshot,
                  log=logging.getLogger("gate_verification"), _GATE_STATS=collections.defaultdict(int),
                  priority_value=scheduler.dprime_priority,
                  _get_env_bool=lambda name, default=False: os.environ.get(name, str(int(default))) == "1",
                  _get_env_float=lambda name, default: float(os.environ.get(name, default)),
                  _endgame_start_minutes=lambda: 0, _priority_refresh_enabled=lambda: True,
                  _priority_human_actions=lambda: 25, _priority_action_scale=lambda: 115,
                  _priority_token_scale=lambda: 62000, _priority_action_weight=lambda: .25,
                  _priority_tail_base=lambda: 6, _priority_tail_cap=lambda: 6,
                  _priority_level_options=lambda: {})
exec(compile("from __future__ import annotations\n" + ast.unparse(gate_node),
             "actual_priority_gate.py", "exec"), gate_scope)
Gate = gate_scope["_PriorityGate"]


class Checks(unittest.TestCase):
    def test_reference_parity(self):
        for total in [None, 1, 6, 8, 10, 12]:
            for level in [1, 3, 6, 10]:
                for actions, tokens, pace in [(0, 0, 0), (50, 50000, 15000),
                                               (200, 300000, 60000)]:
                    for fade in [None, 0, .5, 1, 2]:
                        state = Snapshot(level, actions, tokens, pace, total)
                        self.assertEqual(scheduler.dprime_priority(state, tail_fraction=fade),
                                         reference.d_priority(state, tail_fraction=fade))

    def test_spending_and_deadline(self):
        state = Snapshot(3, 0, 0, 30000, 10)
        self.assertGreater(scheduler.dprime_priority(state),
                           scheduler.dprime_priority(Snapshot(3, 120, 200000, 30000, 10)))
        self.assertGreater(scheduler.dprime_priority(state, tail_fraction=1),
                           scheduler.dprime_priority(state, tail_fraction=0))
        self.assertEqual(scheduler.dprime_priority(Snapshot(10, 0, 0, 30000, 10), tail_fraction=1),
                         scheduler.dprime_priority(Snapshot(10, 0, 0, 30000, 10), tail_fraction=0))
        self.assertLess(scheduler.dprime_priority(state), 1_000_000)
        self.assertGreaterEqual(scheduler.dprime_priority(Snapshot(1, -1, math.nan, math.inf)), 1)

    def test_pace_per_game(self):
        first, other = scheduler.ObservedPace(), scheduler.ObservedPace()
        first.record_completion(10000, 1)
        first.record_completion(30000, 100000)
        self.assertEqual(first.cost_multiplier(), 20000)
        self.assertEqual(other.cost_multiplier(), 0)

    def test_install_retains_gate(self):
        fake = types.SimpleNamespace(priority_value=module.priority_value,
                                     ProgressPace=module.ProgressPace, _PriorityGate=Gate,
                                     PrioritySnapshot=Snapshot, _PRIORITY_UNTRIMMED_BASE=2_000_000,
                                     _PRIORITY_BAND=1_000_000)
        acquire, handover = Gate.acquire, Gate.handover
        scheduler.install(fake)
        scheduler.install(fake)
        self.assertIs(Gate.acquire, acquire)
        self.assertIs(Gate.handover, handover)
        self.assertEqual(os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"], "0.4")

    def test_fresh_game_wins_real_gate(self):
        scheduler.install(types.SimpleNamespace(priority_value=module.priority_value,
                          ProgressPace=module.ProgressPace, _PriorityGate=Gate,
                          PrioritySnapshot=Snapshot, _PRIORITY_UNTRIMMED_BASE=2_000_000,
                          _PRIORITY_BAND=1_000_000))
        gate = Gate(1)
        start = time.monotonic()
        gate.configure_clock(start, start + 60)
        gate.acquire(1)
        admitted = []

        def wait(label, priority, snapshot=None):
            with gate._cond:
                gate._enqueue_and_wait(priority, snapshot)
            admitted.append(label)
            gate.release()

        threads = [threading.Thread(target=wait, args=("continuation", 17000, Snapshot(3, 5, 1000, 30000, 10))),
                   threading.Thread(target=wait, args=("fresh", 1_999_999))]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 2
        while len(gate._waiting) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(gate._waiting), 2)
        gate.release()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(admitted, ["fresh", "continuation"])

    def test_notebook_syntax_and_formal_branch(self):
        notebook = json.loads((ROOT / "upload/arc3-v1-dprime-coverage.ipynb").read_text())
        for i, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] != "code" or cell["source"].startswith("%%writefile"):
                continue
            # Shell magics have already been inspected separately. Compile Python,
            # including async notebook cells, without starting servers or games.
            source = "\n".join("pass" if line.startswith("!") else line
                               for line in cell["source"].splitlines())
            compile(source, f"cell_{i}.py", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        config = next(c["source"] for c in notebook["cells"]
                      if c["cell_type"] == "code" and "bm.solver.max_runtime_s_per_game = 48*60" in c["source"])
        for formal in [False, True]:
            bm = types.SimpleNamespace(solver=types.SimpleNamespace())
            exec(config, {"bm": bm, "TRUE_SUBMISSION": formal, "USE_PRIORITY_SCHEDULING": True})
            self.assertEqual(bm.n_passes, 1)
            self.assertEqual(bm.solver.concurrency, 120 if formal else 4)
            self.assertEqual(bm.solver.max_runtime_s_per_game, 532*60 if formal else 300)
        meta = json.loads((ROOT / "upload/kernel-metadata.json").read_text())
        self.assertTrue(meta["is_private"])
        self.assertFalse(meta["enable_internet"])
        self.assertEqual(meta["machine_shape"], "NvidiaRtxPro6000")
        self.assertNotIn("id_no", meta)


if __name__ == "__main__":
    unittest.main(verbosity=2)
