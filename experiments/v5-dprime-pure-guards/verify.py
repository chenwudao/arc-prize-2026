"""Comprehensive verification for V5 D-Prime + Pure Deterministic Guards iteration."""
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


class V5Checks(unittest.TestCase):
    def test_reference_dprime_parity(self):
        """Verify exact numerical match with authors' reference D' across grids of states."""
        for total in [None, 1, 6, 8, 10, 12]:
            for level in [1, 3, 6, 10]:
                for actions, tokens, pace in [(0, 0, 0), (50, 50000, 15000), (200, 300000, 60000)]:
                    for fade in [None, 0.0, 0.5, 1.0]:
                        state = Snapshot(level, actions, tokens, pace, total)
                        v5_val = scheduler.d_priority(state, tail_fraction=fade)
                        ref_val = reference.d_priority(state, tail_fraction=fade)
                        self.assertEqual(v5_val, ref_val)

    def test_pace_tracker(self):
        """Verify per-game observed token pace calculation."""
        pace = scheduler.FormPace()
        self.assertEqual(pace.cost_multiplier(), 0.0)
        pace.record_completion(15000)
        self.assertEqual(pace.cost_multiplier(), 15000.0)
        pace.record_completion(25000)
        self.assertEqual(pace.cost_multiplier(), 20000.0)

    def test_install_d_gate_and_expose_reset_off(self):
        """Verify install_d hooks Gate.acquire, sets GUARDS_FROM_LEVEL=2, DEATH_LEDGER=1, and removes EXPOSE_RESET."""
        os.environ["EXPOSE_RESET"] = "on"  # Simulate polluted env
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
        self.assertEqual(os.environ["ARC3_DEATH_LEDGER"], "1")
        self.assertEqual(os.environ["EXPOSE_UNDO"], "on")
        self.assertNotIn("EXPOSE_RESET", os.environ)
        self.assertEqual(fake_agent.GUARDS_FROM_LEVEL, 2)

        gate = Gate(slots=1)
        start_t = time.monotonic()
        gate.configure_clock(start_t, start_t + 3600)
        self.assertEqual(gate._free, 1)
        gate.acquire(2_000_000 - 1)
        self.assertEqual(gate._free, 0)
        gate.release()
        self.assertEqual(gate._free, 1)

    def test_step_budget_detector_and_alert(self):
        """Verify step_budget_lines stays silent when >25% left and alerts when <=25% or <=12 actions remain."""
        sb_mod = types.ModuleType("step_budget")
        exec(compile(scheduler.STEP_BUDGET_PY, "step_budget.py", "exec"), sb_mod.__dict__)

        def make_grid(bar_left: int, cap: int = 20):
            bar_row = [8] * bar_left + [0] * (cap - bar_left)
            other_row = [1] * cap
            return [bar_row, other_row, other_row]

        agent = types.SimpleNamespace()
        # 1. Plenty of budget left (16/20 = 80%, 16 actions remaining) -> silent ([])
        high_frames = [
            types.SimpleNamespace(level=1, grid=make_grid(20 - i))
            for i in range(5)
        ]
        high_history = [
            types.SimpleNamespace(action="RIGHT" if i > 0 else "RESET", frame=high_frames[i])
            for i in range(len(high_frames))
        ]
        self.assertEqual(sb_mod.step_budget_lines(agent, high_frames[-1], high_history), [])

        # 2. Low budget (4/20 = 20%, 4 actions remaining) -> emits 1 warning line
        low_frames = [
            types.SimpleNamespace(level=1, grid=make_grid(20 - i))
            for i in range(17)
        ]
        low_history = [
            types.SimpleNamespace(action="RIGHT" if i > 0 else "RESET", frame=low_frames[i])
            for i in range(len(low_frames))
        ]
        alert = sb_mod.step_budget_lines(agent, low_frames[-1], low_history)
        self.assertEqual(len(alert), 1)
        self.assertIn("4 of 20 cells left", alert[0])
        self.assertIn("about 4 more actions empty it", alert[0])

        # 3. Immediate next action on same attempt is throttled -> silent ([])
        next_frame = types.SimpleNamespace(level=1, grid=make_grid(3))
        low_history.append(types.SimpleNamespace(action="RIGHT", frame=next_frame))
        self.assertEqual(sb_mod.step_budget_lines(agent, next_frame, low_history), [])

    def test_apply_v5_harness_patches_on_real_bundle(self):
        """Verify apply_v5_harness_patches against the real patched ARC3-Inference bundle."""
        real_patched = Path("/tmp/taaf_patched/src/ARC3-Inference")
        if not real_patched.exists():
            self.skipTest("/tmp/taaf_patched not present")

        with tempfile.TemporaryDirectory() as tmp:
            work_root = Path(tmp) / "ARC3-Inference"
            shutil.copytree(real_patched, work_root)
            patched_files = scheduler.apply_v5_harness_patches(work_root)
            self.assertEqual(len(patched_files), 6)

            # Verify prompts.py has the static REPL persistence line
            prompts_text = Path(patched_files["prompts"]).read_text(encoding="utf-8")
            self.assertIn(
                "Variables assigned in one `python` call do NOT persist to the next call",
                prompts_text,
            )

            # Verify tool_agent.py has transactional helper retention and death ledger fallback
            ta_text = Path(patched_files["tool_agent"]).read_text(encoding="utf-8")
            self.assertIn('if "keepable_functions" not in sandbox_result:', ta_text)
            self.assertIn("Recorded fatal attempt endings on this level", ta_text)
            self.assertIn("step_budget_lines(self, current_frame, history_entries)", ta_text)


if __name__ == "__main__":
    unittest.main()
