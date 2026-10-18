"""Comprehensive verification for V6 D-Prime + Pre-Execution State Guards + Scoped Memory."""
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


class V6Checks(unittest.TestCase):
    def test_reference_dprime_parity(self):
        """Verify exact numerical match with authors' reference D' across grids of states."""
        for total in [None, 1, 6, 8, 10, 12]:
            for level in [1, 3, 6, 10]:
                for actions, tokens, pace in [(0, 0, 0), (50, 50000, 15000), (200, 300000, 60000)]:
                    for fade in [None, 0.0, 0.5, 1.0]:
                        state = Snapshot(level, actions, tokens, pace, total)
                        v6_val = scheduler.d_priority(state, tail_fraction=fade)
                        ref_val = reference.d_priority(state, tail_fraction=fade)
                        self.assertEqual(v6_val, ref_val)

    def test_install_d_gate_and_v6_flags(self):
        """Verify install_d hooks Gate.acquire, sets V6 guards & memory flags, and keeps EXPOSE_RESET off."""
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
        fake_solver = types.SimpleNamespace(_HarnessGameSession=fake_session, GUARDS_FROM_LEVEL=1)

        scheduler.install_d(fake_agent, fake_solver)

        self.assertTrue(getattr(Gate.acquire, "_ours_d", False))
        self.assertEqual(os.environ["ARC3_PRIORITY_PACE"], "1")
        self.assertEqual(os.environ["ARC3_PRIORITY_REFRESH_QUEUE"], "1")
        self.assertEqual(os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"], "0.4")
        self.assertEqual(os.environ["ARC3_GUARDS_FROM_LEVEL"], "2")
        self.assertEqual(os.environ["ARC3_DEATH_LEDGER"], "1")
        self.assertEqual(os.environ["ARC3_DEATH_REPEAT_GUARD"], "1")
        self.assertEqual(os.environ["ARC3_NOOP_REPEAT_GUARD"], "1")
        self.assertEqual(os.environ["ARC3_REPEAT_STATE_GUARD"], "1")
        self.assertEqual(os.environ["ARC3_SCOPED_MEMORY"], "1")
        self.assertEqual(os.environ["ARC3_GAMEOVER_DIFF"], "1")
        self.assertEqual(os.environ["ARC3_LEVEL_INVENTORY"], "1")
        self.assertEqual(os.environ["ARC3_STUB_DEAD_REASONING"], "1")
        self.assertEqual(os.environ["EXPOSE_UNDO"], "on")
        self.assertNotIn("EXPOSE_RESET", os.environ)
        self.assertEqual(fake_agent.GUARDS_FROM_LEVEL, 2)
        self.assertEqual(fake_solver.GUARDS_FROM_LEVEL, 2)

    def test_scoped_memory_lifecycle(self):
        """Verify scoped_memory.py game/level/step lifetime, in-place refresh, and JSON validation."""
        sm_mod = types.ModuleType("scoped_memory")
        exec(compile(scheduler.SCOPED_MEMORY_PY, "scoped_memory.py", "exec"), sm_mod.__dict__)

        mem = sm_mod.restore_scoped_memory(None, level=1, step=0)
        self.assertEqual(mem["game"], {})
        self.assertEqual(mem["level"], {})
        self.assertEqual(mem["step"], {})

        user_scratch = {
            "game": {"player_color": "R"},
            "level": {"portal": [4, 7]},
            "step": {"cursor": [2, 3]},
        }
        saved, notice = sm_mod.snapshot_scoped_memory(user_scratch, mem, level=1, step=0)
        self.assertEqual(notice, "")
        self.assertEqual(saved["game"]["player_color"], "R")

        # Same level, next step -> step cleared, level & game kept
        restored_step1 = sm_mod.restore_scoped_memory(saved, level=1, step=1)
        self.assertEqual(restored_step1["game"], {"player_color": "R"})
        self.assertEqual(restored_step1["level"], {"portal": [4, 7]})
        self.assertEqual(restored_step1["step"], {})

        # Next level -> level & step cleared, game kept
        restored_lvl2 = sm_mod.restore_scoped_memory(saved, level=2, step=5)
        self.assertEqual(restored_lvl2["game"], {"player_color": "R"})
        self.assertEqual(restored_lvl2["level"], {})
        self.assertEqual(restored_lvl2["step"], {})

        # Invalid mutation (e.g. non-JSON object) -> restores previous valid data
        bad_scratch = {"game": {"bad": object()}, "level": {}, "step": {}}
        fallback, err_notice = sm_mod.snapshot_scoped_memory(bad_scratch, saved, level=1, step=0)
        self.assertIn("Scratch update was not saved", err_notice)
        self.assertEqual(fallback["game"], {"player_color": "R"})
        self.assertEqual(fallback["level"], {"portal": [4, 7]})

    def test_apply_v6_harness_patches_and_live_sandbox(self):
        """Verify apply_v6_harness_patches against real patched ARC3-Inference bundle and run live sandbox."""
        real_patched = Path("/tmp/taaf_patched/src/ARC3-Inference")
        if not real_patched.exists():
            self.skipTest("/tmp/taaf_patched not present")

        with tempfile.TemporaryDirectory() as tmp:
            work_root = Path(tmp) / "ARC3-Inference"
            shutil.copytree(real_patched, work_root)
            patched_files = scheduler.apply_v6_harness_patches(work_root)
            self.assertEqual(len(patched_files), 7)

            # Verify solver.py has animation-aware gameplay_changed_per_action
            solver_text = Path(patched_files["solver"]).read_text(encoding="utf-8")
            self.assertIn(
                'or (item.get("animation") or {}).get("transient_pixels", 0)',
                solver_text,
            )

            # Verify tool_agent.py has animation-aware _record_guard_observations and scoped_memory
            ta_text = Path(patched_files["tool_agent"]).read_text(encoding="utf-8")
            self.assertIn(
                'or (compact_payload.get("animation") or {}).get("transient_pixels", 0)',
                ta_text,
            )
            self.assertIn('if "keepable_functions" not in sandbox_result:', ta_text)
            self.assertIn("scratch_saved_keys", ta_text)

            # Live test of patched python_tool_sandbox with both retained functions and scratch memory
            sys.path.insert(0, str(work_root))
            try:
                for mod_name in list(sys.modules):
                    if mod_name == "inference" or mod_name.startswith("inference."):
                        sys.modules.pop(mod_name, None)
                from inference.agent.python_tool_sandbox import run_sandboxed_python

                initial_state = {
                    "current_frame": {
                        "ascii": "....\n....",
                        "step": 0,
                        "level": 1,
                        "shape": [2, 4],
                        "grid": [[0, 0, 0, 0], [0, 0, 0, 0]],
                    },
                    "history": [],
                    "valid_actions": ["UP", "DOWN"],
                    "last_action_call_result": {},
                }
                res1 = run_sandboxed_python(
                    code=(
                        "scratch['game']['rule'] = 'push'\n"
                        "scratch['level']['walls'] = [[1, 2]]\n"
                        "scratch['step']['probe'] = 1\n"
                        "def get_walls():\n"
                        "    return scratch['level'].get('walls', [])\n"
                        "print('walls:', get_walls())"
                    ),
                    timeout_seconds=10,
                    initial_state=initial_state,
                    action_handler=lambda actions, **kw: {
                        "action_result": {"executed": True, "gameplay_changed": True},
                        "state": initial_state,
                    },
                    kept_functions=[],
                    retain_imports=True,
                    repair_hints=True,
                    scoped_memory={},
                    scoped_memory_enabled=True,
                )
                self.assertIn("walls: [[1, 2]]", res1.get("stdout", ""))
                self.assertEqual(len(res1.get("keepable_functions", [])), 1)
                self.assertEqual(res1["scoped_memory"]["level"]["walls"], [[1, 2]])

                # Call 2 on step 1 (same level): retained function reads persisted scratch['level']!
                state_step1 = dict(initial_state)
                state_step1["current_frame"] = dict(initial_state["current_frame"], step=1)
                res2 = run_sandboxed_python(
                    code="print('reused:', get_walls(), 'step_dict:', scratch['step'])",
                    timeout_seconds=10,
                    initial_state=state_step1,
                    action_handler=lambda actions, **kw: {},
                    kept_functions=[item["source"] for item in res1["keepable_functions"]],
                    retain_imports=True,
                    repair_hints=True,
                    scoped_memory=res1["scoped_memory"],
                    scoped_memory_enabled=True,
                )
                self.assertIn("reused: [[1, 2]] step_dict: {}", res2.get("stdout", ""))
            finally:
                sys.path.remove(str(work_root))


if __name__ == "__main__":
    unittest.main()
