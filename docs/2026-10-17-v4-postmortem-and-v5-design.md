# V4 (`27.32`) Postmortem, Oct 15–17 Public Kernel Survey & V5 (`v5-dprime-pure-guards`) Design

**Date**: 2026-10-17  
**Author**: Antigravity & Jesse

---

## 1. Historical Submission Trajectory

| Iteration | Submission ID | Public LB | Core Architecture & Delta | vs. V2 (`28.04`) |
| :--- | :---: | :---: | :--- | :---: |
| **V1** | `56988179` | **24.22** | `D'` priority formula only; stock `fresh-first` gate left in `_PriorityGate` | `-3.82` |
| **V2 (Best)** | `57062234` | **28.04** | Clean `D'` + `install_d` fresh-game gate replacement (`TAIL_FADE=0.4`, `GUARDS_FROM_LEVEL=2`, `EXPOSE_UNDO=on`, `EXPOSE_RESET` off) | **Baseline** |
| **V3** | `57142410` | **26.45** | V2 + `GUARDS_FROM_LEVEL=1` + 24-action `[STRATEGY AUDIT]` + `EXPOSE_RESET=on` | `-1.59` |
| **Memory v1** | `57189269` | **22.60** | Sliding window truncation (`MAX_RECENT_TURNS=5`), breaking KV-cache & probe history | `-5.44` |
| **V4** | `57218570` | **27.32** | V2 `D'` + `96k` Stagnation Restart + Animation-Aware Guard + Edge Meter + `EXPOSE_RESET=on` | **`-0.72`** (`+0.87` vs V3) |

---

## 2. Root-Cause Diagnosis of V4 (`27.32` vs. V2 `28.04`)

### 2.1 Retained `EXPOSE_RESET='on'` Induces Voluntary Mid-Level Resets ($4\times$ Quadratic RHAE Penalty)
- In V2 (`28.04`), `EXPOSE_RESET` was off (only `EXPOSE_UNDO='on'`).
- In V3 (`26.45`) and V4 (`experiments/v4-stagnation-anima/scheduler.py` line 575), `EXPOSE_RESET='on'` was enabled, injecting into the system prompt (`tn36-ef4dde99_p0.txt` line 72):
  > `- Keep RESET in mind when the level looks wedged, side-effected, or faster to restart cleanly than to unwind step by step.`
- Under the ARC-AGI-3 RHAE metric $\min(1.15, (h_i/a_i)^2)$, calling `RESET` does **not** reset the level's action counter $a_i$. All actions prior to `RESET` plus `RESET` itself remain in the denominator $a_i$. A single voluntary mid-level reset roughly doubles $a_i$, slashing that level's score to $\approx 25\%$.
- Every single top public kernel surveyed (`ouyangruize`, `shiiin9`, `daydreamerthinks`, `yukailiu`, `zhangyues0000`, `leoprovorov`, `efthimiosfousekis`) keeps `EXPOSE_RESET` **off**.

### 2.2 Negative Coupling Between `stagnation_restart.py` (`96k` Hard Wipe) and `D'` Scheduler
- While `stagnation_restart.py` helped `heliosli` (`27.72`) on top of Franzen's stock `fresh-first` scheduler (`26.56`), combining it with `D'` introduced two destructive side effects at `98,304` tokens:
  1. **Wiping `agent._kept_functions = {}`**: Because `ARC3_PERSISTENT_FUNCTIONS_SCOPE='game'`, `_kept_functions` holds validated Python helpers (board decoders, BFS solvers, state simulators) built across earlier completed levels. Clearing `_kept_functions` forces the model to rewrite helpers from scratch and spend extra actions re-probing.
  2. **Calling `agent._note_history_evicted()`**: Forces the active game stream to yield its GPU slot back to `_PriorityGate`. Under `D'`, at $t \ge 98{,}304$ tokens on an unfinished level, the patience factor $C$ has decayed heavily, causing the game to lose its SGLang seat for minutes and invalidating its RadixAttention KV-cache prefix.

### 2.3 Unadvertised Sandbox & Segmentation Additions (`bbox_rc`, `rot90`, `manhattan_distance`, `find_cells`)
- Decompressing `yukailiu`'s 100KB `_DHIA_PATCH_B64` (`Dhia 0.1.21`) confirmed that `sujanmajhisuzan` extracted only the 10-line `component_geometry` (`bbox_rc`) snippet from `Dhia 0.1.21` without `grid_view` or `prompts.py` documentation.
- Because the system prompt never advertised those symbols, the model called them `0` times in V4 transcripts while `bbox_rc` and `bbox_center2_rc` slightly increased `current_frame.segmentation` JSON payload size on every turn.

---

## 3. High-Value Mechanisms from Oct 15–17 Public Kernels

1. **Transactional Helper Retention on Tool Timeout (`yukailiu` v35 `Dhia 0.1.21`)**:
   - In base `harness-changes.patch`, when a Python tool call hits the 30-second timeout (`Tool timed out after 30s`), `run_sandboxed_python` returns `{"error": ..., "stdout": "", "action_results": [...]}` **without** a `"keepable_functions"` key.
   - `ToolAgent._record_retained_functions` treats the missing key as `[]` and executes `self._kept_functions = {}`, **wiping all cross-level retained functions whenever any BFS/simulation call times out**!
   - Guarding `if "keepable_functions" not in sandbox_result: return` preserves `self._kept_functions` across tool timeouts.
2. **Complete 3-Point Animation-Aware Guard + 1-Line Static REPL Persistence Note (`ouyangruize` v7)**:
   - Guards `_stale_state` clearing and appending in `python_tool_sandbox.py`, `_HarnessGameSession` batch `no_op_action` stopping and step verdict in `solver.py`, and trace/opener verdicts in `tool_agent.py`, plus a 1-line static reminder in `PYTHON_ADDENDUM_TAIL`.
3. **Current-Level Death Ledger (`ARC3_DEATH_LEDGER='1'` + Post-Drain Fallback) & Late Step-Budget Bar Alert (`zhangyues0000` R3 & `leoprovorov` Fable-Astra)**:
   - Enabling Franzen's built-in per-instance `ARC3_DEATH_LEDGER='1'` surfaces exact fatal continuations when the current board state hash matches a recorded fatal attempt on the current level, and populates `death_ledger` in the Python sandbox. Adding a 1-line fallback when `not matches` ensures fatal endings on the current level remain visible even after `58k` context eviction.
   - `step_budget.py` detects monotone shrinking border bars ($\ge 12$ cells) and stays completely silent (`0` tokens) until $\le 25\%$ capacity or $\le 12$ actions remain.

---

## 4. V5 (`v5-dprime-pure-guards`) Architecture Summary

1. **Golden V2 `D'` Scheduler Base**: `install_d` fresh-game admission replacement, `ARC3_PRIORITY_TAIL_FADE_FRACTION='0.4'`, `ARC3_GUARDS_FROM_LEVEL=2`, `EXPOSE_UNDO='on'`, **`EXPOSE_RESET` OFF**.
2. **No `96k` Hard Context Wipe & No Unadvertised Bloat**: Removes `stagnation_restart.py`, `edge_meter.py`, and `bbox_rc`.
3. **Complete 3-Point Animation-Aware Execution Guard**: `python_tool_sandbox.py`, `solver.py`, `tool_agent.py`, `animation.py`.
4. **Transactional Helper Retention on 30s Tool Timeout**: Preserves `self._kept_functions` when `"keepable_functions" not in sandbox_result`.
5. **Static 1-Line REPL Persistence Note**: Appended to `PYTHON_ADDENDUM_TAIL` in `prompts.py` (100% SGLang prefix KV-cache reuse).
6. **On-Demand Death Ledger & Late Step-Budget Bar Alert**: `ARC3_DEATH_LEDGER='1'` + post-drain fallback + `step_budget.py` ($\le 25\%$ or $\le 12$ steps remaining).
