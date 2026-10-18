"""V6 D-Prime + Pre-Execution State-Hash Guards + Scoped Sandbox Memory.

Built on the V5 breakthrough architecture (Public LB 31.18), keeping 100% of V5's
verified gains and adding 4 strictly game-agnostic, Private-LB-safe upgrades:
1. Pre-Execution State-Hash Guards on Level >= 2 (Overridable on Immediate Repeat):
   - ARC3_DEATH_REPEAT_GUARD='1' (with _fatal_prefix_match lookahead): intercepts
     actions or batch suffixes from an exact whole-frame board state that previously
     caused GAME_OVER BEFORE execution (0 actions spent, attempt preserved intact).
   - ARC3_NOOP_REPEAT_GUARD='1' (made 100% animation-safe via transient_pixels > 0
     in both solver.py gameplay_changed_per_action and tool_agent.py _record_guard_observations):
     intercepts repeated no-op actions from an identical board state BEFORE execution.
   - ARC3_REPEAT_STATE_GUARD='1': per-snippet state-action cycle breaker that stops
     buggy Python loops from oscillating across revisited (state_hash, action_sig) pairs.
2. Persistent Scoped Sandbox Data Memory (scoped_memory.py / ARC3_SCOPED_MEMORY='1'):
   - Provides `scratch = {'game': {}, 'level': {}, 'step': {}}` (up to 128 KiB JSON)
     inside every Python tool call so parsed maps, hazard coordinates, and BFS graphs
     persist across turns without polluting the LLM prompt or SGLang prefix KV-cache.
   - Includes transactional 30s timeout protection for both `_kept_functions` and
     `_scratch_memory`.
3. Spatial Grounding on Death & Level Transitions:
   - ARC3_GAMEOVER_DIFF='1': emits exact object-level text diff (last_alive -> death_frame)
     on GAME_OVER turns alongside the visual diff image.
   - ARC3_LEVEL_INVENTORY='1': emits START-vs-START object inventory on the first turn
     of a new level (level >= 2), highlighting newly appeared object types.
4. Truncated Reasoning Recovery (Zero Prefix KV-Cache Breakage):
   - ARC3_STUB_DEAD_REASONING='1': replaces truncated reasoning-only replies (no tool call)
     with a compact stub at the tail of the turn so retries do not bloat context toward 58k.

No game IDs, private/public membership, or game-specific heuristics are used.
"""
from __future__ import annotations

import ast
import os
import threading
import time
from pathlib import Path
from typing import Any

VERSION = "v6-dprime-smart-guards-memory"
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

SCOPED_MEMORY_PY = '''"""Bounded JSON scratch space with game, level and observation lifetimes.

Only model-written data is stored; game frames and executable objects are never
implicitly retained. This module is embedded in the isolated Python runner.
"""
import json
import math

SCOPED_MEMORY_LIMIT = 131072
SCOPED_MEMORY_SCOPES = ("game", "level", "step")


def _memory_json_copy(value):
    count = 0

    def validate(item, depth=0):
        nonlocal count
        count += 1
        if count > 24000 or depth > 20:
            raise ValueError("memory contains too many entries or too much nesting")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for key, child in item.items():
                validate(key, depth + 1)
                validate(child, depth + 1)
            return
        raise ValueError("memory accepts only JSON data with string dictionary keys")

    validate(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > SCOPED_MEMORY_LIMIT:
        raise ValueError("memory exceeds the 128 KiB limit")
    return json.loads(encoded)


def restore_scoped_memory(saved, level, step):
    try:
        saved = _memory_json_copy(saved or {})
    except (TypeError, ValueError, OverflowError, RecursionError):
        saved = {}
    if type(saved) is not dict:
        saved = {}
    data = {scope: saved.get(scope, {}) if type(saved.get(scope)) is dict else {}
            for scope in SCOPED_MEMORY_SCOPES}
    identity = saved.get("_identity", {})
    if type(identity) is not dict or identity.get("level") != level:
        data["level"] = {}
        data["step"] = {}
    elif identity.get("step") != step:
        data["step"] = {}
    data["_identity"] = {"level": level, "step": step}
    return data


def refresh_scoped_memory(data, level, step):
    """Clear containers in place so local aliases see the invalidation too."""
    identity = data["_identity"]
    if identity["level"] != level:
        data["level"].clear()
        data["step"].clear()
    elif identity["step"] != step:
        data["step"].clear()
    identity.update(level=level, step=step)


def snapshot_scoped_memory(namespace, previous, level, step):
    try:
        if type(namespace) is not dict or set(namespace) != set(SCOPED_MEMORY_SCOPES):
            raise ValueError("scratch must contain exactly the game, level and step dictionaries")
        if any(type(namespace[s]) is not dict for s in SCOPED_MEMORY_SCOPES):
            raise ValueError("each scratch scope must remain a dictionary")
        saved = _memory_json_copy({**namespace, "_identity": {"level": level, "step": step}})
        return saved, ""
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        return restore_scoped_memory(previous, level, step), (
            "Scratch update was not saved: " + str(exc) + ". Previous valid data was restored."
        )
'''


def _replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"Expected exactly 1 match for {label}, found {count}")
    return source.replace(before, after, 1)


def apply_v6_harness_patches(arc3_inference_root: str | Path) -> dict[str, str]:
    """Apply V6 surgical patches to ARC3-Inference source tree and verify AST syntax."""
    root = Path(arc3_inference_root)
    utils_dir = root / "inference/utils"
    agent_dir = root / "inference/agent"
    fw_dir = root / "inference/framework"

    # 1. Write step_budget.py and scoped_memory.py
    step_budget_path = utils_dir / "step_budget.py"
    ast.parse(STEP_BUDGET_PY)
    step_budget_path.write_text(STEP_BUDGET_PY, encoding="utf-8", newline="\n")

    scoped_memory_path = utils_dir / "scoped_memory.py"
    ast.parse(SCOPED_MEMORY_PY)
    scoped_memory_path.write_text(SCOPED_MEMORY_PY, encoding="utf-8", newline="\n")

    # 2. Patch prompts.py (1-line static REPL variable persistence reminder in PYTHON_ADDENDUM_TAIL)
    prompts_path = agent_dir / "prompts.py"
    prompts_src = prompts_path.read_text(encoding="utf-8")
    prompts_src = _replace_once(
        prompts_src,
        '    "- Flag semantics: `game_over` = this attempt FAILED (death or a limit ran out) — the level auto-resets to its initial state and completed levels are kept; it never means the run is won. `level_completed` = advanced one level. `run_complete`/`done` = the whole game is won. Deaths come either from the action itself (e.g., a hazard cell) or from a step/time budget depleting — watch for a bar at the grid border that shrinks each action, and count remaining budget into your plans.\\n"\n)',
        '    "- Flag semantics: `game_over` = this attempt FAILED (death or a limit ran out) — the level auto-resets to its initial state and completed levels are kept; it never means the run is won. `level_completed` = advanced one level. `run_complete`/`done` = the whole game is won. Deaths come either from the action itself (e.g., a hazard cell) or from a step/time budget depleting — watch for a bar at the grid border that shrinks each action, and count remaining budget into your plans.\\n"\n'
        '    "- Variables assigned in one `python` call do NOT persist to the next call (only retained top-level `def` functions and `scratch` dicts persist); recompute or store reusable data in `scratch` explicitly.\\n"\n)',
        "prompts_python_addendum_tail",
    )
    ast.parse(prompts_src)
    prompts_path.write_text(prompts_src, encoding="utf-8", newline="\n")

    # 3. Patch python_tool_sandbox.py:
    #    - Scoped memory (`scratch = {'game': {}, 'level': {}, 'step': {}}`)
    #    - Animation-aware stale-state handling (both clear and append guard)
    sandbox_path = agent_dir / "python_tool_sandbox.py"
    sandbox_src = sandbox_path.read_text(encoding="utf-8")
    sandbox_src = _replace_once(
        sandbox_src,
        "from inference.utils import retained_functions as _retained_functions\n",
        "from inference.utils import retained_functions as _retained_functions\n"
        "from inference.utils import scoped_memory as _scoped_memory\n",
        "sandbox_import_scoped_memory",
    )
    sandbox_src = _replace_once(
        sandbox_src,
        "    __RETAINED_FUNCTIONS_SOURCE__\n",
        "    __RETAINED_FUNCTIONS_SOURCE__\n\n    __SCOPED_MEMORY_SOURCE__\n",
        "sandbox_bootstrap_scoped_memory_placeholder",
    )
    sandbox_src = _replace_once(
        sandbox_src,
        ').replace("__RETAINED_FUNCTIONS_SOURCE__\\n", inspect.getsource(_retained_functions)).replace(',
        ').replace("__SCOPED_MEMORY_SOURCE__\\n", inspect.getsource(_scoped_memory)).replace("__RETAINED_FUNCTIONS_SOURCE__\\n", inspect.getsource(_retained_functions)).replace(',
        "sandbox_bootstrap_scoped_memory_replace",
    )
    sandbox_src = _replace_once(
        sandbox_src,
        "        _animation_views = []\n",
        """        _animation_views = []
        _scratch_enabled = bool(initial.get("scoped_memory_enabled"))
        _initial_frame = initial.get("state", {}).get("current_frame", {})
        _scratch_data = restore_scoped_memory(
            initial.get("scoped_memory"), _initial_frame.get("level", 0), _initial_frame.get("step", 0))
        if _scratch_enabled:
            runtime_globals["scratch"] = {s: _scratch_data[s] for s in SCOPED_MEMORY_SCOPES}

        def _collect_memory_payload():
            if not _scratch_enabled:
                return {}
            frame = runtime_globals.get("current_frame")
            saved, notice = snapshot_scoped_memory(
                runtime_globals.get("scratch"), initial.get("scoped_memory"),
                frame.level, frame.step)
            return {"scoped_memory": saved, "memory_notice": notice}
""",
        "sandbox_init_scratch",
    )
    sandbox_src = _replace_once(
        sandbox_src,
        '            runtime_globals["current_frame"] = current_frame\n',
        """            if _scratch_enabled:
                active = runtime_globals.get("scratch", {})
                if type(active) is dict and all(type(active.get(s)) is dict for s in SCOPED_MEMORY_SCOPES):
                    for scope in SCOPED_MEMORY_SCOPES:
                        _scratch_data[scope] = active[scope]
                    refresh_scoped_memory(_scratch_data, current_frame.level, current_frame.step)
            runtime_globals["current_frame"] = current_frame
""",
        "sandbox_refresh_scratch",
    )
    retention_anchor = "                    **_collect_retention_payload(),\n"
    if sandbox_src.count(retention_anchor) != 2:
        raise RuntimeError(
            f"Expected 2 occurrences of _collect_retention_payload anchor, found {sandbox_src.count(retention_anchor)}"
        )
    sandbox_src = sandbox_src.replace(
        retention_anchor,
        retention_anchor + "                    **_collect_memory_payload(),\n",
    )
    sandbox_src = _replace_once(
        sandbox_src,
        "    repair_hints: bool = False,\n) -> dict[str, Any]:",
        "    repair_hints: bool = False,\n    scoped_memory: dict[str, Any] | None = None,\n    scoped_memory_enabled: bool = False,\n) -> dict[str, Any]:",
        "sandbox_sig_scoped_memory",
    )
    sandbox_src = _replace_once(
        sandbox_src,
        '                "animation_enabled": animation_handler is not None,\n',
        '                "animation_enabled": animation_handler is not None,\n'
        '                "scoped_memory": scoped_memory,\n'
        '                "scoped_memory_enabled": scoped_memory_enabled,\n',
        "sandbox_send_scoped_memory",
    )
    sandbox_src = _replace_once(
        sandbox_src,
        '                    "keepable_functions": list(message.get("keepable_functions") or []),\n',
        '                    "keepable_functions": list(message.get("keepable_functions") or []),\n'
        '                    **({"scoped_memory": message.get("scoped_memory"), "memory_notice": message.get("memory_notice", "")} if scoped_memory_enabled else {}),\n',
        "sandbox_return_scoped_memory",
    )
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

    # 4. Patch solver.py:
    #    - Animation-aware _action_verdict
    #    - Animation-aware batch no_op_action stop guard
    #    - Animation-aware gameplay_changed_per_action so NoopRepeatGuard never records animated actions as no-ops
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
    solver_src = _replace_once(
        solver_src,
        """            final_payload["gameplay_changed_per_action"] = [
                bool(item.get("gameplay_changed", True)) for item in executed_payloads
            ]""",
        """            final_payload["gameplay_changed_per_action"] = [
                bool(
                    item.get("gameplay_changed", True)
                    or (item.get("animation") or {}).get("transient_pixels", 0)
                )
                for item in executed_payloads
            ]""",
        "solver_gameplay_changed_per_action_animation",
    )
    ast.parse(solver_src)
    solver_path.write_text(solver_src, encoding="utf-8", newline="\n")

    # 5. Patch tool_agent.py:
    #    - Import step_budget_lines
    #    - Scoped memory state, sandbox invocation, transactional timeout retention, and system prompt guidance
    #    - Transactional helper retention on tool timeout/abort ('keepable_functions' not in sandbox_result)
    #    - Animation-aware single-action verdict in _record_guard_observations (for NoopRepeatGuard)
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
        "            self._history_messages = []\n",
        "            self._scratch_memory = {}\n            self._history_messages = []\n",
        "ta_init_scratch_memory",
    )
    ta_src = _replace_once(
        ta_src,
        '            repair_hints=_get_env_bool("ARC3_PERSISTENT_FUNCTIONS_REPAIR_HINTS", False),\n',
        '            repair_hints=_get_env_bool("ARC3_PERSISTENT_FUNCTIONS_REPAIR_HINTS", False),\n'
        '            scoped_memory=getattr(self, "_scratch_memory", {}),\n'
        '            scoped_memory_enabled=_get_env_bool("ARC3_SCOPED_MEMORY", False),\n',
        "ta_pass_scoped_memory",
    )
    ta_src = _replace_once(
        ta_src,
        '        payload: dict[str, Any] = {"tool": "python"}\n',
        """        payload: dict[str, Any] = {"tool": "python"}
        if _get_env_bool("ARC3_SCOPED_MEMORY", False):
            saved_memory = sandbox_result.get("scoped_memory")
            if isinstance(saved_memory, dict):
                self._scratch_memory = saved_memory
                memory_keys = {s: list(saved_memory.get(s, {}))[:12] for s in ("game", "level", "step")}
                if any(memory_keys.values()):
                    payload["scratch_saved_keys"] = memory_keys
            elif getattr(self, "_scratch_memory", None):
                memory_keys = {s: list(self._scratch_memory.get(s, {}))[:12] for s in ("game", "level", "step") if isinstance(self._scratch_memory.get(s), dict)}
                if any(memory_keys.values()):
                    payload["scratch_saved_keys"] = memory_keys
            if sandbox_result.get("memory_notice"):
                payload["scratch_notice"] = sandbox_result["memory_notice"]
""",
        "ta_record_scoped_memory",
    )
    ta_src = _replace_once(
        ta_src,
        "    if _level_transfer_guidance_enabled():\n        prompt = apply_level_transfer_system_guidance(prompt)\n    return prompt",
        """    if _level_transfer_guidance_enabled():
        prompt = apply_level_transfer_system_guidance(prompt)
    if _get_env_bool("ARC3_SCOPED_MEMORY", False):
        prompt += (
            "\\nPersistent Python data: `scratch` is available in every Python call. "
            "Use `scratch['game']` for compact mechanics/evidence reusable across levels, "
            "`scratch['level']` for this level's inferred rules, parsed layout, simulator parameters or search results, "
            "and `scratch['step']` for observations and coordinates tied to the current frame. "
            "Game data lasts until the game ends; level data is cleared when the level changes; "
            "step data is cleared immediately whenever an action changes the frame's step or level. "
            "Ordinary local variables still reset between calls. Store useful computed results explicitly in scratch, "
            "then reuse them instead of printing/rebuilding them. Saved data is your own hypothesis, not ground truth; "
            "revise it when new observations disagree, and read changing positions from the current frame. "
            "Keep the three scope dictionaries; store only JSON values (string keys, lists, strings, numbers, booleans, null), "
            "up to 128 KiB total. Do not store functions or frame objects there. "
            "Your retained functions may read scratch at call time.\\n"
        )
    return prompt""",
        "ta_system_prompt_scoped_memory",
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
        """        verdicts = raw_payload.get("gameplay_changed_per_action")
        if not isinstance(verdicts, list) or not verdicts:
            if len(trace) != 1 or not compact_payload.get("executed"):
                return
            verdicts = [compact_payload.get("gameplay_changed")]""",
        """        verdicts = raw_payload.get("gameplay_changed_per_action")
        if not isinstance(verdicts, list) or not verdicts:
            if len(trace) != 1 or not compact_payload.get("executed"):
                return
            verdicts = [
                bool(
                    compact_payload.get("gameplay_changed")
                    or (compact_payload.get("animation") or {}).get("transient_pixels", 0)
                )
            ]""",
        "ta_guard_observations_animation",
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
        "scoped_memory": str(scoped_memory_path),
        "prompts": str(prompts_path),
        "python_tool_sandbox": str(sandbox_path),
        "solver": str(solver_path),
        "tool_agent": str(ta_path),
        "animation": str(anim_path),
    }


def install_d(tool_agent: Any, solver: Any) -> str:
    """Install full D-prime scheduler, pre-execution state guards, and scoped memory."""
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

    # D-prime scheduler + V6 pre-execution state guards + scoped memory + spatial diffs
    os.environ["ARC3_PRIORITY_PACE"] = "1"
    os.environ["ARC3_PRIORITY_REFRESH_QUEUE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE"] = "1"
    os.environ["ARC3_PRIORITY_TAIL_FADE_FRACTION"] = str(D_PRIME["fade"])
    os.environ["ARC3_GUARDS_FROM_LEVEL"] = "2"
    os.environ["ARC3_DEATH_LEDGER"] = "1"
    os.environ["ARC3_DEATH_REPEAT_GUARD"] = "1"
    os.environ["ARC3_NOOP_REPEAT_GUARD"] = "1"
    os.environ["ARC3_REPEAT_STATE_GUARD"] = "1"
    os.environ["ARC3_SCOPED_MEMORY"] = "1"
    os.environ["ARC3_GAMEOVER_DIFF"] = "1"
    os.environ["ARC3_LEVEL_INVENTORY"] = "1"
    os.environ["ARC3_STUB_DEAD_REASONING"] = "1"
    os.environ["EXPOSE_UNDO"] = "on"
    os.environ.pop("EXPOSE_RESET", None)

    if hasattr(tool_agent, "GUARDS_FROM_LEVEL"):
        tool_agent.GUARDS_FROM_LEVEL = 2
    if hasattr(solver, "GUARDS_FROM_LEVEL"):
        solver.GUARDS_FROM_LEVEL = 2

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
        f"#ARC3_ITERATION {VERSION} installed; D-prime admission; "
        f"tail fade {D_PRIME['fade']}; EXPOSE_RESET off; pre-exec death/noop/cycle guards (L>=2) + "
        f"4-point animation guard + scoped scratch memory + timeout retention + gameover/level diffs active"
    )
    print(line, flush=True)
    return line
