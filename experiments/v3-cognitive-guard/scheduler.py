"""V3 Cognitive Guard Scheduler: Full D-prime priority alignment + fresh-game admission replacement + Strategy-Audit + Level-1 Guards.

Sources:
- Daniel Franzen Milestone 2 Solution: https://github.com/da-fr/arc-agi-3-solution
- Affectify D-prime Formula: https://www.kaggle.com/code/shiiin9/affectify-arc-31-54-in-a-single-sub
- Yukai Liu Champion Solution: https://www.kaggle.com/code/yukailiu/arc-agi-3-champion-solution
- Lord Han Solo (lordhansolo) Milestone 2 Solution (Strategy Audit): Kaggle Topic 744792

No game IDs, private/public membership, or human baseline answers are used.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Any

VERSION = "v3-cognitive-guard"
SCALE = 1000.0

D_PRIME = {
    "level_pow": 0.5,
    "eff_const": 300.0,
    "eff_pow": 2.5,
    "pace_pow": 0.4,
    "pace_ref": 30_000.0,
    "c_action": 0.1,
    "action_scale": 115.0,
    "c_token": 0.9,
    "token_scale": 225_000.0,
    "lin_floor": 0.1,
    "rel_pow": 0.5,
    "b1": 10.0,
    "b2": 14.0,
    "b3": 16.0,
    "fade": 0.4,
}


class FormPace:
    """Mean generated tokens per level cleared in this game session."""

    def __init__(self):
        self.completed = 0
        self.tokens = 0.0

    def record_completion(self, tokens_used: float, reference_tokens: float = 0.0) -> None:
        self.completed += 1
        self.tokens += max(0.0, float(tokens_used))

    def cost_multiplier(self) -> float:
        return self.tokens / self.completed if self.completed else 0.0


def _levels(total: Any) -> int | None:
    try:
        n = int(total)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def d_parts(
    level: int,
    actions: float,
    tokens: float,
    pace: float,
    total_levels: Any,
    params: dict[str, float] = D_PRIME,
) -> tuple[float, float]:
    """Calculate (A * C, B) components of D-prime priority."""
    level = max(1, int(level))
    n = _levels(total_levels) or 10
    n_clamped = min(10, max(6, n))
    norm = 55 / (n_clamped * (n_clamped + 1) / 2)
    a = max(0.0, float(actions))
    t = max(0.0, float(tokens))

    # A: Level depth & action efficiency
    A = (1.0 + params["level_pow"] * (level - 1)) * norm
    A *= (params["eff_const"] / (params["eff_const"] + a)) ** params["eff_pow"]
    if pace > 0:
        A *= min(4.0, max(0.25, (params["pace_ref"] / max(1.0, pace)) ** params["pace_pow"]))

    # C: Token & action patience degradation
    scale = params["token_scale"]
    rel = pace if pace > 0 else params["pace_ref"]
    scale *= min(2.0, max(0.5, rel / params["pace_ref"])) ** params["rel_pow"]
    floor = params["lin_floor"]
    C = (
        params["c_action"] * max(floor, 1.0 - a / params["action_scale"])
        + params["c_token"] * max(floor, 1.0 - t / scale)
    )

    # B: Remaining level completion potential
    remaining = max(0, n - level)
    B = (0.0, params["b1"], params["b2"], params["b3"])[min(remaining, 3)]

    # Optional gating of remaining reward by current level patience
    if os.environ.get("ARC3_PRIORITY_GATE_B", "0") == "1":
        B *= C

    return A * C, B


def d_value(
    level: int,
    actions: float,
    tokens: float,
    pace: float,
    total_levels: Any,
    phi: float = 1.0,
) -> float:
    u, v = d_parts(level, actions, tokens, pace, total_levels)
    return u + v * phi


def d_priority(state: Any, *, tail_fraction: float | None = None, **_ignored) -> int:
    """Evaluate integer priority value compatible with Franzen priority bands."""
    phi = 1.0 if tail_fraction is None else min(1.0, max(0.0, float(tail_fraction)))
    val = d_value(
        state.level,
        state.actions,
        state.tokens,
        float(getattr(state, "cost_multiplier", 0.0) or 0.0),
        getattr(state, "total_levels", None),
        phi,
    )
    return max(1, int(val * SCALE))


FRESH = {"replaced": 0}
_TL = threading.local()


def install_strategy_audit(tool_agent_module: Any) -> bool:
    """Attach strategic audit intervention when stalled on a single level.
    
    Compatible with all ToolAgent._build_user_prompt signatures (*args, **kwargs).
    """
    tool_agent_cls = getattr(tool_agent_module, "ToolAgent", None)
    if tool_agent_cls is None or not hasattr(tool_agent_cls, "_build_user_prompt"):
        return False
    if getattr(tool_agent_cls, "_v3_audit_installed", False):
        return True

    orig_build = tool_agent_cls._build_user_prompt

    def _build_user_prompt_with_audit(self, *args: Any, **kwargs: Any) -> str:
        base_prompt = orig_build(self, *args, **kwargs)
        if os.environ.get("ARC3_STRATEGY_AUDIT", "1") != "1":
            return base_prompt

        # Extract previous_step_summary safely from kwargs or args
        prev_summary = kwargs.get("previous_step_summary")
        if prev_summary is None:
            for arg in args:
                if isinstance(arg, dict) and ("action_num" in arg or "executed_count" in arg or "level_actions" in arg):
                    prev_summary = arg
                    break
        if prev_summary is None:
            prev_summary = getattr(self, "_last_step_summary", None)

        actions = 0
        if prev_summary and isinstance(prev_summary, dict):
            try:
                actions = int(
                    prev_summary.get("action_num")
                    or prev_summary.get("end_action_num")
                    or prev_summary.get("level_actions")
                    or 0
                )
            except (TypeError, ValueError):
                actions = 0

        # When agent has taken over 24 actions without clearing the level, inject reflection guidance
        if actions >= 24:
            audit_msg = (
                "\n\n[STRATEGY AUDIT]: High action count on this level without progression. "
                "Your working hypothesis may be incomplete or invalid. Stop repeating similar action sequences. "
                "Re-examine the board for overlooked objects or mechanics, and consider testing UNDO or RESET "
                "if you have reached an irreversible or dead-end board state."
            )
            base_prompt += audit_msg
        return base_prompt

    tool_agent_cls._build_user_prompt = _build_user_prompt_with_audit
    tool_agent_cls._v3_audit_installed = True
    return True


def install_d(tool_agent: Any, solver: Any) -> str:
    """Install full D-prime scheduler, replacing priority formula, fresh-first gate, and activating cognitive guards."""
    for name in (
        "priority_value",
        "ProgressPace",
        "_PriorityGate",
        "PrioritySnapshot",
        "_PRIORITY_UNTRIMMED_BASE",
        "_PRIORITY_BAND",
    ):
        if not hasattr(tool_agent, name):
            raise RuntimeError(f"tool_agent missing required attribute: {name}")

    session_cls = getattr(solver, "_HarnessGameSession", None)
    if session_cls is None or not callable(getattr(session_cls, "play", None)):
        raise RuntimeError("solver missing _HarnessGameSession.play")

    gate_cls = tool_agent._PriorityGate
    for name in ("acquire", "_enqueue_and_wait", "_snapshot_priority"):
        if not callable(getattr(gate_cls, name, None)):
            raise RuntimeError(f"_PriorityGate missing callable: {name}")

    tool_agent.priority_value = d_priority
    tool_agent.ProgressPace = FormPace
    tool_agent._arc3_iteration_version = VERSION

    # 1. D-prime scheduler configuration
    os.environ["ARC3_PRIORITY_PACE"] = "1"
    os.environ["ARC3_PRIORITY_REFRESH_QUEUE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"] = str(D_PRIME["fade"])

    # 2. Cognitive Guard & Anti-Loop Configuration
    os.environ["ARC3_STRATEGY_AUDIT"] = "1"
    os.environ["ARC3_GUARDS_FROM_LEVEL"] = "1"  # Lower guard activation to Level 1
    os.environ["ARC3_NOOP_REPEAT_GUARD"] = "1"  # Stop repeating dead actions
    os.environ["ARC3_DEATH_REPEAT_GUARD"] = "1" # Stop repeating fatal paths
    os.environ["ARC3_DEATH_LEDGER"] = "1"       # Record death states
    os.environ["ARC3_STEP_VERIFICATION_HINT"] = "1"
    os.environ["ARC3_REPORT_GAMEPLAY_CHANGED"] = "1"
    os.environ["ARC3_LEVEL_TRANSFER_GUIDANCE"] = "1"

    if hasattr(tool_agent, "GUARDS_FROM_LEVEL"):
        tool_agent.GUARDS_FROM_LEVEL = 1

    # Track total levels per thread session
    if not getattr(session_cls.play, "_ours_d", False):
        orig_play = session_cls.play

        def play(self, *args, **kwargs):
            run = getattr(getattr(self, "game", None), "game_run", None)
            _TL.n = getattr(run, "number_of_levels", None)
            try:
                return orig_play(self, *args, **kwargs)
            finally:
                _TL.n = None

        play._ours_d = True
        session_cls.play = play

    # Replace fresh-first gate: unstarted games enter queue via D-prime snapshot priority
    if not getattr(gate_cls.acquire, "_ours_d", False):
        orig_acquire = gate_cls.acquire
        fresh_floor = tool_agent._PRIORITY_UNTRIMMED_BASE - tool_agent._PRIORITY_BAND
        snapshot_cls = tool_agent.PrioritySnapshot

        def acquire(self, priority: int):
            if priority < fresh_floor:
                return orig_acquire(self, priority)
            snap = snapshot_cls(1, 0, 0.0, 0.0, getattr(_TL, "n", None))
            value = self._snapshot_priority(snap, time.monotonic())
            with self._cond:
                self._enqueue_and_wait(value, snap)
            FRESH["replaced"] += 1

        acquire._ours_d = True
        gate_cls.acquire = acquire

    # Safely install Strategy Audit hook
    install_strategy_audit(tool_agent)

    line = (
        f"#ARC3_ITERATION {VERSION} installed; fresh-first replaced with D-prime admission; "
        f"tail fade {D_PRIME['fade']}; strategy-audit + level-1 guards active"
    )
    print(line, flush=True)
    return line
