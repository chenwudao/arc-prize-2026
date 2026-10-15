"""Comprehensive verification for V4 Stagnation + Animation-Aware + D-Prime iteration."""
import ast
import collections
import heapq
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import scheduler

FIXTURES = ROOT.parent / "v1-dprime-coverage/verification-fixtures"

# Load PrioritySnapshot from fixtures
scope = {"__name__": "verified_priority_inputs"}
module = types.ModuleType(scope["__name__"])
sys.modules[module.__name__] = module
exec(compile((FIXTURES / "priority_scheduler.py").read_text(), "priority_scheduler.py", "exec"), module.__dict__)
Snapshot = module.PrioritySnapshot

# Extract reference D' without running notebook
reference = types.ModuleType("reference_dprime")
exec(compile((FIXTURES / "reference-dprime.py").read_text(), "reference_dprime.py", "exec"), reference.__dict__)

# Parse real admission gate class from fixtures
gate_node = next(
    n
    for n in ast.parse((FIXTURES / "tool_agent_gate.py").read_text()).body
    if isinstance(n, ast.ClassDef) and n.name == "_PriorityGate"
)
gate_scope = dict(
    threading=threading,
    heapq=heapq,
    time=time,
    os=os,
    PrioritySnapshot=Snapshot,
    log=logging.getLogger("gate_verification"),
    _GATE_STATS=collections.defaultdict(int),
    priority_value=scheduler.d_priority,
    _get_env_bool=lambda name, default=False: os.environ.get(name, str(int(default))) == "1",
    _get_env_float=lambda name, default: float(os.environ.get(name, default)),
    _endgame_start_minutes=lambda: 0,
    _priority_refresh_enabled=lambda: True,
    _priority_human_actions=lambda: 25,
    _priority_action_scale=lambda: 115,
    _priority_token_scale=lambda: 62000,
    _priority_action_weight=lambda: 0.25,
    _priority_tail_base=lambda: 6,
    _priority_tail_cap=lambda: 6,
    _priority_level_options=lambda: {},
)
exec(
    compile("from __future__ import annotations\n" + ast.unparse(gate_node), "actual_priority_gate.py", "exec"),
    gate_scope,
)
Gate = gate_scope["_PriorityGate"]


class V4Checks(unittest.TestCase):
    def test_reference_dprime_parity(self):
        """Verify exact numerical match with authors' reference D' across grids of states."""
        for total in [None, 1, 6, 8, 10, 12]:
            for level in [1, 3, 6, 10]:
                for actions, tokens, pace in [(0, 0, 0), (50, 50000, 15000), (200, 300000, 60000)]:
                    for fade in [None, 0.0, 0.5, 1.0]:
                        state = Snapshot(level, actions, tokens, pace, total)
                        v4_val = scheduler.d_priority(state, tail_fraction=fade)
                        ref_val = reference.d_priority(state, tail_fraction=fade)
                        self.assertEqual(v4_val, ref_val)

    def test_pace_tracker(self):
        """Verify per-game observed token pace calculation."""
        pace = scheduler.FormPace()
        self.assertEqual(pace.cost_multiplier(), 0.0)
        pace.record_completion(15000)
        self.assertEqual(pace.cost_multiplier(), 15000.0)
        pace.record_completion(25000)
        self.assertEqual(pace.cost_multiplier(), 20000.0)

    def test_install_d_gate_and_level1_unguarded(self):
        """Verify install_d hooks Gate.acquire, removes 2,000,000 hard band, and preserves GUARDS_FROM_LEVEL=2."""
        fake_agent = types.SimpleNamespace(
            priority_value=module.priority_value,
            ProgressPace=module.ProgressPace,
            _PriorityGate=Gate,
            PrioritySnapshot=Snapshot,
            _PRIORITY_UNTRIMMED_BASE=2_000_000,
            _PRIORITY_BAND=1_000_000,
            GUARDS_FROM_LEVEL=1,
        )
        fake_session = types.SimpleNamespace(play=lambda self, *args, **kwargs: "played")
        fake_solver = types.SimpleNamespace(_HarnessGameSession=fake_session)

        scheduler.install_d(fake_agent, fake_solver)

        self.assertTrue(getattr(Gate.acquire, "_ours_d", False))
        self.assertEqual(os.environ["ARC3_PRIORITY_PACE"], "1")
        self.assertEqual(os.environ["ARC3_PRIORITY_REFRESH_QUEUE"], "1")
        self.assertEqual(os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"], "0.4")
        self.assertEqual(os.environ["ARC3_GUARDS_FROM_LEVEL"], "2")
        self.assertEqual(os.environ["EXPOSE_RESET"], "on")
        self.assertEqual(fake_agent.GUARDS_FROM_LEVEL, 2)

        gate = Gate(slots=1)
        start_t = time.monotonic()
        gate.configure_clock(start_t, start_t + 3600)
        self.assertEqual(gate._free, 1)
        gate.acquire(2_000_000 - 1)
        self.assertEqual(gate._free, 0)
        gate.release()
        self.assertEqual(gate._free, 1)

    def test_stagnation_restart_behavior(self):
        """Verify 96k-token one-time stagnation context restart."""
        stag_mod = types.ModuleType("stagnation_restart")
        exec(compile(scheduler.STAGNATION_RESTART_PY, "stagnation_restart.py", "exec"), stag_mod.__dict__)

        class DummyAgent:
            def __init__(self):
                self._session_generated_tokens = 50_000
                self._tokens_at_level_start = 0
                self._history_messages = [{"role": "user", "content": "msg1"}]
                self._kept_functions = {"solve": "def solve(): pass"}
                self._retained_clear_notice = "old"
                self._resume_after_yield = True
                self._resume_reason = "yield_tokens"
                self._text_chars_per_token = 3.5
                self._last_step_summary = {}
                self._stagnation_restarted_levels = set()
                self._stagnation_pending_notice = None
                self.evicted_called = 0

            def _note_history_evicted(self):
                self.evicted_called += 1

        agent = DummyAgent()
        frame = types.SimpleNamespace(level=1, step=18)

        # 1. Below 98,304 tokens -> no restart
        notice = stag_mod.maybe_restart(agent, frame)
        self.assertEqual(notice, "")
        self.assertEqual(len(agent._history_messages), 1)
        self.assertIn("solve", agent._kept_functions)

        # 2. Reach 98,304 tokens -> triggers one-time restart
        agent._session_generated_tokens = 96 * 1024 + 100
        notice = stag_mod.maybe_restart(agent, frame)
        self.assertIn("Fresh review of the current level", notice)
        self.assertEqual(agent._history_messages, [])
        self.assertEqual(agent._kept_functions, {})
        self.assertFalse(agent._resume_after_yield)
        self.assertEqual(agent.evicted_called, 1)
        self.assertIn(1, agent._stagnation_restarted_levels)

        # 3. After more tokens generated on same level -> does NOT restart again
        agent._history_messages = [{"role": "user", "content": "new_attempt"}]
        agent._session_generated_tokens = 200_000
        notice2 = stag_mod.maybe_restart(agent, frame)
        self.assertEqual(notice2, "")
        self.assertEqual(len(agent._history_messages), 1)

    def test_edge_meter_detection(self):
        """Verify shrinking monotone edge-strip measurement on fatal attempt."""
        edge_mod = types.ModuleType("edge_meter")
        exec(compile(scheduler.EDGE_METER_PY, "edge_meter.py", "exec"), edge_mod.__dict__)

        frames = [
            types.SimpleNamespace(level=1, ascii="RRRRRRRR\n........\n........"),
            types.SimpleNamespace(level=1, ascii="RRRRRR..\n........\n........"),
            types.SimpleNamespace(level=1, ascii="RRRR....\n........\n........"),
            types.SimpleNamespace(level=1, ascii="RR......\n........\n........"),
            types.SimpleNamespace(level=1, ascii="........\n........\n........"),
        ]
        history = [
            types.SimpleNamespace(action="RIGHT", frame=frames[i], result={"game_over": i == 4})
            for i in range(5)
        ]
        lines = edge_mod.fatal_meter_lines(history)
        self.assertEqual(len(lines), 1)
        self.assertIn("top edge, color R", lines[0])
        self.assertIn("2 before the fatal action -> 0 in the fatal frame (empty)", lines[0])

    def test_apply_v4_harness_patches_on_real_bundle(self):
        """Verify apply_v4_harness_patches against the real patched ARC3-Inference bundle."""
        real_patched = Path("/tmp/taaf_patched/src/ARC3-Inference")
        if not real_patched.exists():
            self.skipTest("/tmp/taaf_patched not present")

        with tempfile.TemporaryDirectory() as tmp:
            work_root = Path(tmp) / "ARC3-Inference"
            shutil.copytree(real_patched, work_root)
            patched_files = scheduler.apply_v4_harness_patches(work_root)
            self.assertEqual(len(patched_files), 7)

            # Verify segmentation geometry output
            seg_mod = types.ModuleType("seg_test")
            seg_src = Path(patched_files["segmentation"]).read_text(encoding="utf-8")
            exec(compile(seg_src, "segmentation.py", "exec"), seg_mod.__dict__)
            seg_res = seg_mod.segment_layer([[1, 1], [1, 0]], "0123456789ABCDEF")
            one_node = next(n for n in seg_res["nodes"] if n["color"] == "1")
            self.assertEqual(one_node["bbox_rc"], [0, 0, 1, 1])
            self.assertEqual(one_node["bbox_center2_rc"], [1, 1])
            self.assertEqual(seg_mod.manhattan_distance((0, 0), (3, 4)), 7)


if __name__ == "__main__":
    unittest.main()
