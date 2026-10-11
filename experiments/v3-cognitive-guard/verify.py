"""Comprehensive verification for V3 Cognitive Guard iteration."""
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


class V3Checks(unittest.TestCase):
    def test_reference_dprime_parity(self):
        """Verify exact numerical match with authors' reference D' across grids of states."""
        for total in [None, 1, 6, 8, 10, 12]:
            for level in [1, 3, 6, 10]:
                for actions, tokens, pace in [(0, 0, 0), (50, 50000, 15000), (200, 300000, 60000)]:
                    for fade in [None, 0.0, 0.5, 1.0]:
                        state = Snapshot(level, actions, tokens, pace, total)
                        v3_val = scheduler.d_priority(state, tail_fraction=fade)
                        ref_val = reference.d_priority(state, tail_fraction=fade)
                        self.assertEqual(v3_val, ref_val)

    def test_pace_tracker(self):
        """Verify per-game observed token pace calculation."""
        pace = scheduler.FormPace()
        self.assertEqual(pace.cost_multiplier(), 0.0)
        pace.record_completion(15000)
        self.assertEqual(pace.cost_multiplier(), 15000.0)
        pace.record_completion(25000)
        self.assertEqual(pace.cost_multiplier(), 20000.0)

    def test_install_d_gate_interception_and_guards(self):
        """Verify install_d hooks Gate.acquire, removes 2,000,000 hard band, and sets guards."""
        fake_agent = types.SimpleNamespace(
            priority_value=module.priority_value,
            ProgressPace=module.ProgressPace,
            _PriorityGate=Gate,
            PrioritySnapshot=Snapshot,
            _PRIORITY_UNTRIMMED_BASE=2_000_000,
            _PRIORITY_BAND=1_000_000,
            GUARDS_FROM_LEVEL=2,
            ToolAgent=types.SimpleNamespace(
                _build_user_prompt=lambda self, *args, **kwargs: "Mock base prompt"
            ),
        )
        fake_session = types.SimpleNamespace(play=lambda self, *args, **kwargs: "played")
        fake_solver = types.SimpleNamespace(_HarnessGameSession=fake_session)

        scheduler.install_d(fake_agent, fake_solver)

        # Gate acquire should now be hooked
        self.assertTrue(getattr(Gate.acquire, "_ours_d", False))
        self.assertEqual(os.environ["ARC3_PRIORITY_PACE"], "1")
        self.assertEqual(os.environ["ARC3_PRIORITY_REFRESH_QUEUE"], "1")
        self.assertEqual(os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"], "0.4")
        self.assertEqual(os.environ["ARC3_GUARDS_FROM_LEVEL"], "1")
        self.assertEqual(os.environ["ARC3_NOOP_REPEAT_GUARD"], "1")
        self.assertEqual(os.environ["ARC3_DEATH_REPEAT_GUARD"], "1")
        self.assertEqual(os.environ["ARC3_DEATH_LEDGER"], "1")
        self.assertEqual(os.environ["ARC3_STRATEGY_AUDIT"], "1")
        self.assertEqual(fake_agent.GUARDS_FROM_LEVEL, 1)

        # Create gate instance and test acquire with fresh priority (>= fresh_floor)
        gate = Gate(slots=1)
        start_t = time.monotonic()
        gate.configure_clock(start_t, start_t + 3600)

        # Before acquiring, gate has 1 free slot
        self.assertEqual(gate._free, 1)

        # Test acquiring slot for fresh game (which previously passed 2,000,000)
        fresh_prio = 2_000_000 - 1
        gate.acquire(fresh_prio)
        self.assertEqual(gate._free, 0)

        # Release and verify it unblocks
        gate.release()
        self.assertEqual(gate._free, 1)

    def test_strategy_audit_prompts_and_signatures(self):
        """Verify Strategy Audit operates cleanly across all signature variations."""
        class MockToolAgent:
            def __init__(self):
                self._last_step_summary = None

            def _build_user_prompt(
                self,
                current_level=None,
                previous_step_summary=None,
                valid_actions=None,
            ):
                return f"Prompt for level={current_level}"

        mock_module = types.SimpleNamespace(ToolAgent=MockToolAgent)
        success = scheduler.install_strategy_audit(mock_module)
        self.assertTrue(success)

        agent = MockToolAgent()

        # 1. Normal turn (< 24 actions): prompt is unaugmented
        p1 = agent._build_user_prompt(
            current_level=1,
            previous_step_summary={"action_num": 10},
            valid_actions=["UP", "DOWN"],
        )
        self.assertNotIn("[STRATEGY AUDIT]", p1)
        self.assertIn("Prompt for level=1", p1)

        # 2. Stalled turn (>= 24 actions) passed as keyword argument
        p2 = agent._build_user_prompt(
            current_level=1,
            previous_step_summary={"action_num": 25},
            valid_actions=["UP", "DOWN"],
        )
        self.assertIn("[STRATEGY AUDIT]", p2)
        self.assertIn("Prompt for level=1", p2)

        # 3. Positional arguments call (current_level, previous_step_summary, valid_actions)
        p3 = agent._build_user_prompt(1, {"action_num": 30}, ["UP", "DOWN"])
        self.assertIn("[STRATEGY AUDIT]", p3)

        # 4. Keyword only with valid_actions and end_action_num
        p4 = agent._build_user_prompt(
            current_level=2,
            previous_step_summary={"end_action_num": 26},
            valid_actions=["RESET", "UNDO"],
        )
        self.assertIn("[STRATEGY AUDIT]", p4)

        # 5. Stored summary fallback on self
        agent._last_step_summary = {"action_num": 28}
        p5 = agent._build_user_prompt(current_level=3)
        self.assertIn("[STRATEGY AUDIT]", p5)

        # 6. Disabled via environment variable
        os.environ["ARC3_STRATEGY_AUDIT"] = "0"
        p6 = agent._build_user_prompt(
            current_level=1,
            previous_step_summary={"action_num": 50},
        )
        self.assertNotIn("[STRATEGY AUDIT]", p6)
        os.environ["ARC3_STRATEGY_AUDIT"] = "1"


if __name__ == "__main__":
    unittest.main()
