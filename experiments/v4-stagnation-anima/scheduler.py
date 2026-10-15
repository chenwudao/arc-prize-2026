"""V4 Stagnation + Animation-Aware + D-Prime Scheduler.

Combines the proven V2 Clean D-prime scheduler (LB 28.04) with:
1. 96k-Token Stagnation Context Restart (stagnation_restart.py): clears poisoned
   reasoning context and buggy retained functions once per level after 98,304
   generated tokens, preserving board state and empirical Python observations.
2. Animation-Aware No-Op & Stale-State Fix: actions with transient animation
   pixels (transient_pixels > 0) are not misclassified as NO-OP or stale-state,
   and empty animation responses always carry documented schema keys.
3. Fatal Edge-Strip Meter (edge_meter.py): reports objective pixel measurements
   of shrinking monotone edge strips on post-death diagnostic turns.
4. Segmentation Bounding-Box Geometry & Spatial Helpers: adds bbox_rc and
   bbox_center2_rc to segment_layer nodes plus standard grid transforms.
5. Reverts V3's harmful Level-1 repeat guards (restores ARC3_GUARDS_FROM_LEVEL=2
   and removes unsolicited 24-action advice text).

No game IDs, private/public membership, or human baseline answers are used.
"""
from __future__ import annotations

import ast
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

VERSION = "v4-stagnation-anima"
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

STAGNATION_RESTART_PY = '''"""One fresh reasoning context after a very expensive unfinished level.

Only observed level progress and actual generated tokens are used. The game,
action history, death ledger, model sampling and accounting are untouched.
"""
import logging

LEVEL_TOKEN_LIMIT = 96 * 1024
log = logging.getLogger(__name__)


def maybe_restart(agent, frame):
    if frame is None or int(frame.level) <= 0:
        return ""
    level = int(frame.level)
    generated = int(agent._session_generated_tokens)
    pending = getattr(agent, "_stagnation_pending_notice", None)
    if pending is not None:
        pending_level, at_tokens, notice = pending
        if pending_level == level and generated <= at_tokens:
            # A failed HTTP request must not lose the explanatory fresh opener.
            agent._resume_after_yield = False
            agent._resume_reason = ""
            return notice
        agent._stagnation_pending_notice = None
    seen = getattr(agent, "_stagnation_restarted_levels", set())
    if level in seen or (agent._last_step_summary or {}).get("run_complete"):
        return ""
    spent = max(0, generated - int(agent._tokens_at_level_start))
    if spent < LEVEL_TOKEN_LIMIT:
        return ""

    # Run only between analyzer invocations, after outstanding tool calls finish.
    # The next request is a complete current-board opener, never a yield resume
    # asking the model to continue reasoning that is no longer in its context.
    old_messages = len(agent._history_messages)
    agent._history_messages = []
    agent._kept_functions = {}
    agent._retained_clear_notice = ""
    agent._resume_after_yield = False
    agent._resume_reason = ""
    agent._text_chars_per_token = None
    agent._note_history_evicted()
    agent._stagnation_restarted_levels = seen | {level}
    notice = (
        f"Fresh review of the current level: {spent} tokens of earlier reasoning "
        "have not completed this level. That reasoning and retained Python functions "
        "have been cleared once to reconsider the problem from its observations. "
        "No game action or game reset was performed by this context change: the "
        "current board, completed levels, remaining action budget, and recorded "
        "history are unchanged. Python history, transitions and death_ledger still "
        "contain the actual observations. Re-establish what counts as success and "
        "what the controls do from the board and those observations; treat earlier "
        "interpretations as hypotheses. Check a concrete prediction with a safe "
        "action before committing to another long search.\\n\\n"
    )
    agent._stagnation_pending_notice = (level, generated, notice)
    log.warning("stagnation_context_restart level=%d step=%d tokens=%d old_messages=%d",
                level, int(frame.step), spent, old_messages)
    return notice
'''

EDGE_METER_PY = '''"""Measure monotone two-color strips on board edges from observations only.

An edge strip is not automatically an action budget. Reports state the pixels
and observed rate; semantic cause remains a hypothesis for the agent to test.
"""
def _edges(frame):
    rows = frame.ascii.splitlines()
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        return {}
    return {'top': rows[0], 'bottom': rows[-1],
            'left': ''.join(row[0] for row in rows), 'right': ''.join(row[-1] for row in rows)}


def measure_edge_meters(frames):
    """Pass one level/attempt, oldest first, including its fatal frame if present."""
    if len(frames) < 4 or len({frame.level for frame in frames}) != 1:
        return []
    sample = [_edges(frame) for frame in frames]
    if not all(sample):
        return []
    reports = []
    for side, first in sample[0].items():
        if len(set(first)) != 1:
            continue
        color = first[0]
        strips = [item[side] for item in sample]
        if any(len(strip) != len(first) or len(set(strip)) > 2 for strip in strips):
            continue
        replacements = set(''.join(strips)) - {color}
        if len(replacements) != 1:
            continue
        if any(sum(a != b for a, b in zip(strip, strip[1:])) > 1 for strip in strips):
            continue
        counts = [strip.count(color) for strip in strips]
        deltas = [a - b for a, b in zip(counts, counts[1:])]
        drops = [d for d in deltas if d > 0]
        if any(d < 0 for d in deltas) or len(drops) < 3:
            continue
        regular = max(drops) - min(drops) <= 1 and all(d > 0 for d in deltas)
        rate = sum(deltas) / len(deltas)
        reports.append({
            'edge': side,
            'color': color,
            'initial_pixels': len(first),
            'remaining_pixels': counts[-1],
            'previous_pixels': counts[-2],
            'observed_steps': len(deltas),
            'decreases': len(drops),
            'drop_range': [min(drops), max(drops)],
            'exhausted': counts[-1] == 0,
            'rough_actions_to_zero': round(counts[-1] / rate, 1) if regular and rate else None,
            'meaning': 'observed shrinking edge strip; its semantic role is unverified',
        })
    return reports


def fatal_meter_evidence(history):
    """Find the latest fatal action before an automatic reset, using actual frames."""
    deaths = [i for i, e in enumerate(history) if (e.result or {}).get('game_over')]
    if not deaths:
        return []
    end = deaths[-1]
    if any(str(e.action).upper() != 'RESET' for e in history[end + 1:]):
        return []
    begin = end
    while begin > 0:
        if (history[begin - 1].frame.level != history[end].frame.level or
                (history[begin - 1].result or {}).get('game_over')):
            break
        begin -= 1
        if str(history[begin].action).upper() == 'RESET':
            break
    frames = [e.frame for e in history[begin:end + 1] if e.frame is not None]
    return measure_edge_meters(frames)


def fatal_meter_lines(history):
    lines = []
    for item in fatal_meter_evidence(history):
        ending = 'empty' if item['exhausted'] else 'not empty'
        lines.append(
            f"Measured edge-strip evidence at the fatal action: {item['edge']} edge, color {item['color']}, "
            f"{item['initial_pixels']} pixels at this attempt's start; "
            f"{item['previous_pixels']} before the fatal action -> {item['remaining_pixels']} in the fatal frame ({ending}). "
            f"It decreased on {item['decreases']}/{item['observed_steps']} observed transitions. "
            "These are pixel measurements, not proof of this strip's role. If it is the action budget, use this evidence to distinguish depletion from a hazard."
        )
    return lines
'''


def _replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"Expected exactly 1 match for {label}, found {count}")
    return source.replace(before, after, 1)


def apply_v4_harness_patches(arc3_inference_root: str | Path) -> dict[str, str]:
    """Apply V4 surgical patches to ARC3-Inference source tree and verify AST syntax."""
    root = Path(arc3_inference_root)
    utils_dir = root / "inference/utils"
    agent_dir = root / "inference/agent"
    fw_dir = root / "inference/framework"

    # 1. Write stagnation_restart.py and edge_meter.py
    stag_path = utils_dir / "stagnation_restart.py"
    edge_path = utils_dir / "edge_meter.py"
    ast.parse(STAGNATION_RESTART_PY)
    ast.parse(EDGE_METER_PY)
    stag_path.write_text(STAGNATION_RESTART_PY, encoding="utf-8", newline="\n")
    edge_path.write_text(EDGE_METER_PY, encoding="utf-8", newline="\n")

    # 2. Patch python_tool_sandbox.py (Animation-aware stale-state handling)
    sandbox_path = agent_dir / "python_tool_sandbox.py"
    sandbox_src = sandbox_path.read_text(encoding="utf-8")
    sandbox_src = _replace_once(
        sandbox_src,
        """            gameplay_changed = action_result.get("gameplay_changed")
            if gameplay_changed is True:
                # a real change means the snippet's beliefs are current again
                del _stale_state[:]
            if gameplay_changed is False and action_result.get("executed"):""",
        """            gameplay_changed = action_result.get("gameplay_changed")
            animated = bool((action_result.get("animation") or {}).get("transient_pixels", 0))
            if gameplay_changed is True or animated:
                # Visible or intermediate motion keeps the snippet's beliefs live.
                del _stale_state[:]
            if gameplay_changed is False and not animated and action_result.get("executed"):""",
        "sandbox_animation_stale_state",
    )
    ast.parse(sandbox_src)
    sandbox_path.write_text(sandbox_src, encoding="utf-8", newline="\n")

    # 3. Patch solver.py (Animation-aware verdict and batch no-op stop)
    solver_path = fw_dir / "solver.py"
    solver_src = solver_path.read_text(encoding="utf-8")
    solver_src = _replace_once(
        solver_src,
        """    if item.get("level_completed"):
        return "LEVEL COMPLETED"
    changed = item.get("gameplay_changed")
    if changed is False:""",
        """    if item.get("level_completed"):
        return "LEVEL COMPLETED"
    changed = item.get("gameplay_changed")
    if changed is False and (item.get("animation") or {}).get("transient_pixels", 0):
        return "animated effect (intermediate frames changed; final board restored)"
    if changed is False:""",
        "solver_action_verdict",
    )
    solver_src = _replace_once(
        solver_src,
        """                and NOOP_GUARD_BORDER_WIDTH > 0
                and batch_size >= 2
                and not payload.get("gameplay_changed", True)
            ):
                stop_reason = "no_op_action"
                break""",
        """                and NOOP_GUARD_BORDER_WIDTH > 0
                and batch_size >= 2
                and not payload.get("gameplay_changed", True)
                and not (payload.get("animation") or {}).get("transient_pixels", 0)
            ):
                stop_reason = "no_op_action"
                break""",
        "solver_batch_noop_stop",
    )
    ast.parse(solver_src)
    solver_path.write_text(solver_src, encoding="utf-8", newline="\n")

    # 4. Patch tool_agent.py (Stagnation restart + Fatal edge meter + Animation-aware trace)
    ta_path = agent_dir / "tool_agent.py"
    ta_src = ta_path.read_text(encoding="utf-8")
    ta_src = _replace_once(
        ta_src,
        "from inference.agent.python_tool_sandbox import run_sandboxed_python\n",
        "from inference.agent.python_tool_sandbox import run_sandboxed_python\n"
        "from inference.utils.stagnation_restart import maybe_restart\n"
        "from inference.utils.edge_meter import fatal_meter_lines\n",
        "ta_imports",
    )
    ta_src = _replace_once(
        ta_src,
        "            self._history_messages = []\n            self._session_total_tokens = 0\n",
        "            self._stagnation_restarted_levels = set()\n"
        "            self._stagnation_pending_notice = None\n"
        "            self._history_messages = []\n            self._session_total_tokens = 0\n",
        "ta_session_reset",
    )
    ta_src = _replace_once(
        ta_src,
        "        current_frame, history_entries = load_runtime_state(state_path)\n        user_prompt = self._build_user_prompt(\n",
        "        current_frame, history_entries = load_runtime_state(state_path)\n"
        "        restart_notice = maybe_restart(self, current_frame)\n"
        "        user_prompt = restart_notice + self._build_user_prompt(\n",
        "ta_maybe_restart_call",
    )
    ta_src = _replace_once(
        ta_src,
        '                fatal_action = str(previous_step_summary.get("fatal_action") or "")\n',
        '                lines.extend(fatal_meter_lines(history_entries))\n'
        '                fatal_action = str(previous_step_summary.get("fatal_action") or "")\n',
        "ta_fatal_edge_meter",
    )
    ta_src = _replace_once(
        ta_src,
        """            elif item.get("level_completed"):
                verdict = "LEVEL COMPLETED"
            elif item.get("gameplay_changed") is False:""",
        """            elif item.get("level_completed"):
                verdict = "LEVEL COMPLETED"
            elif item.get("gameplay_changed") is False and (item.get("animation") or {}).get("transient_pixels", 0):
                verdict = "animated effect (intermediate frames changed; final board restored)"
            elif item.get("gameplay_changed") is False:""",
        "ta_trace_verdict",
    )
    ta_src = _replace_once(
        ta_src,
        """                elif previous_step_summary.get("board_changed"):
                    lines.append(
                        f"That sequence changed only cells within {border} of the edge "
                        "(usually a timer or remaining-steps bar) - nothing inside the "
                        "board area moved."
                    )
                else:
                    lines.append("That sequence produced no change anywhere on the board.")""",
        """                elif previous_step_summary.get("board_changed"):
                    lines.append(
                        f"That sequence changed only cells within {border} of the edge "
                        "(usually a timer or remaining-steps bar) - nothing inside the "
                        "board area moved."
                    )
                elif (previous_step_summary.get("animation") or {}).get("transient_pixels", 0):
                    lines.append("That sequence triggered an intermediate animation whose final frame restored the board.")
                else:
                    lines.append("That sequence produced no change anywhere on the board.")""",
        "ta_opener_outcome_animation",
    )
    ast.parse(ta_src)
    ta_path.write_text(ta_src, encoding="utf-8", newline="\n")

    # 5. Patch animation.py (Empty animation schema completeness)
    anim_path = utils_dir / "animation.py"
    anim_src = anim_path.read_text(encoding="utf-8")
    anim_src = _replace_once(
        anim_src,
        """    empty = {
        "error": (
            "No animation is available: the last executed action returned a single frame."
        )
    }""",
        """    empty = {
        "action": record.get("action_display") if record else None,
        "frames": 0,
        "steps": [],
        "error": (
            "No animation is available: the last executed action returned a single frame."
        )
    }""",
        "anim_empty_schema",
    )
    ast.parse(anim_src)
    anim_path.write_text(anim_src, encoding="utf-8", newline="\n")

    # 6. Patch segmentation.py (Add bbox_rc, bbox_center2_rc & spatial utilities)
    seg_path = utils_dir / "segmentation.py"
    seg_src = seg_path.read_text(encoding="utf-8")
    seg_src = _replace_once(
        seg_src,
        "    return canonical, rotation, symmetry, hashes[0], shape_hash\n",
        "    return canonical, rotation, symmetry, hashes[0], shape_hash\n\n\n"
        "def component_geometry(cells):\n"
        "    r0 = min(p[0] for p in cells)\n"
        "    c0 = min(p[1] for p in cells)\n"
        "    r1 = max(p[0] for p in cells)\n"
        "    c1 = max(p[1] for p in cells)\n"
        "    return {'bbox_rc': [r0, c0, r1, c1], 'bbox_center2_rc': [r0 + r1, c0 + c1]}\n",
        "seg_component_geometry_def",
    )
    seg_src = _replace_once(
        seg_src,
        '                "pixels": len(comp["cells"]),\n                "boundary": [[r, c] for r, c in boundary],',
        '                "pixels": len(comp["cells"]),\n                **component_geometry(comp["cells"]),\n                "boundary": [[r, c] for r, c in boundary],',
        "seg_component_geometry_node",
    )
    spatial_helpers = """

# Built-in spatial transformation utilities for python REPL
def rot90(grid, k=1):
    k = k % 4
    res = [list(row) for row in grid]
    for _ in range(k):
        res = [list(x) for x in zip(*res[::-1])]
    return res

def rot180(grid):
    return rot90(grid, 2)

def rot270(grid):
    return rot90(grid, 3)

def flipv(grid):
    return [list(row) for row in grid[::-1]]

def fliph(grid):
    return [list(row[::-1]) for row in grid]

def manhattan_distance(p1, p2):
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

def find_cells(grid, target):
    coords = []
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val == target:
                coords.append((r, c))
    return coords
"""
    if "def rot90(" not in seg_src:
        seg_src += spatial_helpers
    ast.parse(seg_src)
    seg_path.write_text(seg_src, encoding="utf-8", newline="\n")

    return {
        "stagnation_restart": str(stag_path),
        "edge_meter": str(edge_path),
        "python_tool_sandbox": str(sandbox_path),
        "solver": str(solver_path),
        "tool_agent": str(ta_path),
        "animation": str(anim_path),
        "segmentation": str(seg_path),
    }


def install_d(tool_agent: Any, solver: Any) -> str:
    """Install full D-prime scheduler, replacing priority formula and fresh-first gate."""
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

    # D-prime scheduler configuration (preserving Level-1 unguarded probing)
    os.environ["ARC3_PRIORITY_PACE"] = "1"
    os.environ["ARC3_PRIORITY_REFRESH_QUEUE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"] = str(D_PRIME["fade"])
    os.environ["ARC3_GUARDS_FROM_LEVEL"] = "2"
    os.environ["EXPOSE_UNDO"] = "on"
    os.environ["EXPOSE_RESET"] = "on"

    if hasattr(tool_agent, "GUARDS_FROM_LEVEL"):
        tool_agent.GUARDS_FROM_LEVEL = 2

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

    line = (
        f"#ARC3_ITERATION {VERSION} installed; fresh-first replaced with D-prime admission; "
        f"tail fade {D_PRIME['fade']}; 96k stagnation restart + animation-aware noop + edge meter active"
    )
    print(line, flush=True)
    return line
