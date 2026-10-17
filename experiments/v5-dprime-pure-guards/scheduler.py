"""V5 D-Prime + Pure Deterministic Guards + Death Ledger & Step-Budget Alert.

Built on the proven V2 Clean D-prime scheduler baseline (LB 28.04), reverting all
V3/V4 negative side effects and adding deterministic, zero-cache-breakage fixes:
1. Revert EXPOSE_RESET='on' (restores default off; only EXPOSE_UNDO='on'), preventing
   voluntary mid-level resets that quadratically penalize RHAE (Human/Agent)^2.
2. Remove 96k stagnation_restart.py hard wipe (never calls _note_history_evicted()
   beyond standard 58k context drain and never wipes cross-level _kept_functions).
3. Complete 3-Point Animation-Aware Guard (python_tool_sandbox.py, solver.py,
   tool_agent.py, animation.py): actions with transient_pixels > 0 do not trigger
   _stale_state blocks or batch no_op_action aborts.
4. Transactional Helper Retention on Tool Timeout (tool_agent.py): preserves
   previously committed _kept_functions when a 30s Python call times out or aborts
   without a 'keepable_functions' report.
5. Static PYTHON_ADDENDUM_TAIL REPL Persistence Reminder (prompts.py): 1-line
   static system prompt note preserving 100% SGLang prefix KV-cache reuse.
6. On-Demand Current-Level Death Ledger (ARC3_DEATH_LEDGER='1' + post-drain fallback)
   and Late Step-Budget Bar Alert (step_budget.py, <=25% or <=12 steps remaining).

No game IDs, private/public membership, or human baseline answers are used.
"""
from __future__ import annotations

import ast
import os
import threading
import time
from pathlib import Path
from typing import Any

VERSION = "v5-dprime-pure-guards"
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

STEP_BUDGET_PY = '''"""On-demand step-budget bar detector and low-budget alert (pure stdlib).

Silent on normal turns; emits a single warning line only when a monotone shrinking
border bar (>=12 cells) is detected and remaining budget drops to <=25% or <=12 actions.
"""
from __future__ import annotations


def detect_budget(frames, min_actions: int = 4):
    """Detect a straight line whose contiguous run of equal cells loses cells from one end."""
    k = len(frames) - 1
    if k < min_actions or not frames or not frames[0]:
        return None
    n_rows = len(frames[0])
    n_cols = len(frames[0][0])
    best = None
    lines = [("row", i) for i in range(n_rows)] + [("col", j) for j in range(n_cols)]
    for kind, idx in lines:
        def line(frame, _kind=kind, _idx=idx):
            return list(frame[_idx]) if _kind == "row" else [row[_idx] for row in frame]

        first = line(frames[0])
        runs, start = [], 0
        for i in range(1, len(first) + 1):
            if i == len(first) or first[i] != first[start]:
                if i - start >= 12:
                    runs.append((start, i - 1))
                start = i
        if not runs:
            continue
        if line(frames[-1]) == first:
            continue
        series = [line(f) for f in frames]
        changed_prev = set()
        ok = True
        steps_with_change = 0
        max_step = 0
        for t in range(1, len(series)):
            changed = {i for i in range(len(first)) if series[t][i] != first[i]}
            if not changed >= changed_prev:
                ok = False
                break
            if len(changed) > len(changed_prev):
                steps_with_change += 1
                max_step = max(max_step, len(changed) - len(changed_prev))
            changed_prev = changed
        if not ok or not changed_prev or max_step > 6 or steps_with_change < 0.3 * k:
            continue
        for lo, hi in runs:
            d = {i for i in changed_prev if lo <= i <= hi}
            if not d or d != changed_prev:
                continue
            cells = sorted(d)
            contiguous = cells[-1] - cells[0] + 1 == len(cells)
            at_end = cells[0] == lo or cells[-1] == hi
            if not (contiguous and at_end):
                continue
            new_colors = {series[-1][i] for i in cells}
            if len(new_colors) != 1:
                continue
            used, cap = len(cells), hi - lo + 1
            rate = used / k
            if not (0.15 <= rate <= 4.0):
                continue
            cand = dict(
                kind=kind,
                index=idx,
                cap=cap,
                used=used,
                left=cap - used,
                rate=rate,
                remaining=int((cap - used) / rate),
                actions=k,
            )
            if best is None or (cap, used) > (best["cap"], best["used"]):
                best = cand
    return best


def step_budget_lines(agent, current_frame, history_entries) -> list[str]:
    """Return a 1-line low-budget alert when <=25% or <=12 actions remain, else []."""
    if current_frame is None:
        return []
    try:
        level = int(current_frame.level)
        entries = [e for e in (history_entries or []) if getattr(e, "frame", None) is not None]
        start = 0
        for i, e in enumerate(entries):
            if str(getattr(e, "action", "") or "").upper() == "RESET" or int(e.frame.level) != level:
                start = i
        frames = [e.frame.grid for e in entries[start:] if int(e.frame.level) == level]
        if len(frames) < 5:
            return []
        cache = getattr(agent, "_v5_budget_cache", None)
        if cache is not None and cache[0] == level and 0 <= len(frames) - cache[1] < 4:
            b = cache[2]
        else:
            b = detect_budget(frames)
            agent._v5_budget_cache = (level, len(frames), b)
        if not b or b["left"] <= 0:
            return []
        frac = b["left"] / float(b["cap"])
        if not (frac <= 0.25 or b["remaining"] <= 12):
            return []
        last = getattr(agent, "_v5_budget_alerted", None)
        if last is not None and last[0] == level and 0 <= len(frames) - last[1] < 8 and b["remaining"] > last[2] - 8:
            return []
        agent._v5_budget_alerted = (level, len(frames), b["remaining"])
        where = f"row {b['index']}" if b["kind"] == "row" else f"column {b['index']}"
        return [
            f"Step budget (read from the frames by the harness): the bar along {where} has {b['left']} of {b['cap']} cells left "
            f"after {b['actions']} actions on this attempt (about {b['rate']:.1f} cells per action). "
            f"At this rate about {b['remaining']} more actions empty it, and the level then resets (actions already spent still count)."
        ]
    except Exception:
        return []
'''


def _replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"Expected exactly 1 match for {label}, found {count}")
    return source.replace(before, after, 1)


def apply_v5_harness_patches(arc3_inference_root: str | Path) -> dict[str, str]:
    """Apply V5 surgical patches to ARC3-Inference source tree and verify AST syntax."""
    root = Path(arc3_inference_root)
    utils_dir = root / "inference/utils"
    agent_dir = root / "inference/agent"
    fw_dir = root / "inference/framework"

    # 1. Write step_budget.py
    step_budget_path = utils_dir / "step_budget.py"
    ast.parse(STEP_BUDGET_PY)
    step_budget_path.write_text(STEP_BUDGET_PY, encoding="utf-8", newline="\n")

    # 2. Patch prompts.py (1-line static REPL variable persistence reminder in PYTHON_ADDENDUM_TAIL)
    prompts_path = agent_dir / "prompts.py"
    prompts_src = prompts_path.read_text(encoding="utf-8")
    prompts_src = _replace_once(
        prompts_src,
        '    "- Flag semantics: `game_over` = this attempt FAILED (death or a limit ran out) — the level auto-resets to its initial state and completed levels are kept; it never means the run is won. `level_completed` = advanced one level. `run_complete`/`done` = the whole game is won. Deaths come either from the action itself (e.g., a hazard cell) or from a step/time budget depleting — watch for a bar at the grid border that shrinks each action, and count remaining budget into your plans.\\n"\n)',
        '    "- Flag semantics: `game_over` = this attempt FAILED (death or a limit ran out) — the level auto-resets to its initial state and completed levels are kept; it never means the run is won. `level_completed` = advanced one level. `run_complete`/`done` = the whole game is won. Deaths come either from the action itself (e.g., a hazard cell) or from a step/time budget depleting — watch for a bar at the grid border that shrinks each action, and count remaining budget into your plans.\\n"\n'
        '    "- Variables assigned in one `python` call do NOT persist to the next call (only retained top-level `def` functions persist); recompute or pass state explicitly in each call.\\n"\n)',
        "prompts_python_addendum_tail",
    )
    ast.parse(prompts_src)
    prompts_path.write_text(prompts_src, encoding="utf-8", newline="\n")

    # 3. Patch python_tool_sandbox.py (Animation-aware stale-state handling: both clear and append guard)
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

    # 4. Patch solver.py (Animation-aware verdict and _HarnessGameSession batch no-op stop guard)
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

    # 5. Patch tool_agent.py:
    #    - Import step_budget_lines
    #    - Transactional helper retention on tool timeout/abort ('keepable_functions' not in sandbox_result)
    #    - Death ledger fallback line when current board state hash does not match but level has deaths
    #    - Step-budget alert line after death ledger lines
    #    - Animation-aware trace verdict and opener outcome
    ta_path = agent_dir / "tool_agent.py"
    ta_src = ta_path.read_text(encoding="utf-8")
    ta_src = _replace_once(
        ta_src,
        "from inference.agent.python_tool_sandbox import run_sandboxed_python\n",
        "from inference.agent.python_tool_sandbox import run_sandboxed_python\n"
        "from inference.utils.step_budget import step_budget_lines\n",
        "ta_imports",
    )
    ta_src = _replace_once(
        ta_src,
        """        try:
            previous = self._kept_functions
            kept = {}""",
        """        try:
            previous = self._kept_functions
            if "keepable_functions" not in sandbox_result:
                if previous:
                    payload["function_retention"] = (
                        f"Tool call did not complete; preserved {len(previous)} previously retained helper function(s)."
                    )
                return
            kept = {}""",
        "ta_transactional_helper_retention",
    )
    ta_src = _replace_once(
        ta_src,
        """        for uidx, pos in self._death_ledger_index.get(state_hash, []):
            matches[uidx] = max(matches.get(uidx, -1), pos)
        if not matches:
            return []""",
        """        for uidx, pos in self._death_ledger_index.get(state_hash, []):
            matches[uidx] = max(matches.get(uidx, -1), pos)
        if not matches:
            if previous_step_summary and previous_step_summary.get("game_over"):
                return []
            recent = []
            for item in self._death_ledger_attempts[-3:]:
                acts = item["actions"]
                tail = ", ".join(acts[-4:]) if len(acts) > 4 else ", ".join(acts)
                prefix = f"... ({len(acts)} steps) " if len(acts) > 4 else ""
                recent.append(f"[{prefix}{tail} -> GAME OVER]")
            return [
                f"Recorded fatal attempt endings on this level ({len(self._death_ledger_attempts)} distinct path(s)): "
                + "; ".join(recent)
                + ". Do not repeat a known-fatal ending without a changed plan (full details in python `death_ledger`)."
            ]""",
        "ta_death_ledger_fallback",
    )
    ta_src = _replace_once(
        ta_src,
        """            lines.extend(
                self._death_ledger_lines(
                    current_frame, history_entries, previous_step_summary
                )
            )""",
        """            lines.extend(
                self._death_ledger_lines(
                    current_frame, history_entries, previous_step_summary
                )
            )
        lines.extend(step_budget_lines(self, current_frame, history_entries))""",
        "ta_step_budget_hook",
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

    # 6. Patch animation.py (Empty animation schema completeness)
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

    return {
        "step_budget": str(step_budget_path),
        "prompts": str(prompts_path),
        "python_tool_sandbox": str(sandbox_path),
        "solver": str(solver_path),
        "tool_agent": str(ta_path),
        "animation": str(anim_path),
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

    # D-prime scheduler configuration (preserving V2 golden baseline: EXPOSE_RESET off!)
    os.environ["ARC3_PRIORITY_PACE"] = "1"
    os.environ["ARC3_PRIORITY_REFRESH_QUEUE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"] = str(D_PRIME["fade"])
    os.environ["ARC3_GUARDS_FROM_LEVEL"] = "2"
    os.environ["ARC3_DEATH_LEDGER"] = "1"
    os.environ["EXPOSE_UNDO"] = "on"
    os.environ.pop("EXPOSE_RESET", None)

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
        f"tail fade {D_PRIME['fade']}; EXPOSE_RESET off; 3-point animation guard + timeout helper retention + death ledger & step budget active"
    )
    print(line, flush=True)
    return line
