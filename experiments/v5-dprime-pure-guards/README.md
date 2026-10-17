# V5 (`v5-dprime-pure-guards`): Clean D-Prime + Pure Deterministic Guards + On-Demand Death Ledger & Step-Budget Alert

## Overview
`v5-dprime-pure-guards` builds directly on our highest-scoring golden baseline (**V2 `57062234`**, Public LB **28.04**), reverting the negative side effects identified in V4 (`57218570`, Public LB **27.32**) and integrating five surgical, zero-KV-cache-breakage improvements verified across the October 15–17 top public submissions.

## What Changed from V4 (`27.32`) to V5
1. **Reverted `EXPOSE_RESET='on'` (Restored V2 Default `off`, keeping only `EXPOSE_UNDO='on'`)**:
   - In V3 (`26.45`) and V4 (`27.32`), enabling `EXPOSE_RESET='on'` injected a system prompt instruction encouraging the model to call `RESET` voluntarily mid-level.
   - Under the ARC-AGI-3 RHAE metric $\min(1.15, (h_i/a_i)^2)$, calling `RESET` does **not** reset the level's action counter $a_i$ — all actions before `RESET` plus `RESET` itself remain in the denominator, slashing the level's score by $4\times$.
   - All 15 surveyed top public notebooks (`ouyangruize` `30.74`, `shiiin9` `31.54`, `daydreamerthinks` `29.26`, `yukailiu`, `zhangyues0000`, `leoprovorov`) keep `EXPOSE_RESET` off.
2. **Removed `96k` Hard Context Wipe (`stagnation_restart.py`) & Unadvertised Sandbox Bloats**:
   - In V4, `stagnation_restart.py` wiped `agent._kept_functions = {}` (destroying validated cross-level helper functions built on earlier levels under `ARC3_PERSISTENT_FUNCTIONS_SCOPE='game'`) and called `agent._note_history_evicted()` (forcing the game to yield its active GPU slot under `D'` and invalidating the SGLang RadixAttention KV-cache prefix).
   - Standard context draining (`ARC3_CONTEXT_DRAIN_TOKENS = 58 * 1024`) already drains old turns smoothly while keeping `_kept_functions` intact.
3. **Complete 3-Point Animation-Aware Execution Guard (`python_tool_sandbox.py`, `solver.py`, `tool_agent.py`, `animation.py`)**:
   - Actions with intermediate animations (`transient_pixels > 0`) clear `_stale_state`, do not append to `_stale_state`, do not abort multi-action batches via `stop_reason = "no_op_action"` in `solver.py`, and report `"animated effect (intermediate frames changed; final board restored)"`.
4. **Transactional Helper Retention on Tool Timeout (`tool_agent.py`)**:
   - Fixes a bug in base `harness-changes.patch` where a 30-second Python tool timeout (`"keepable_functions" not in sandbox_result`) caused `_record_retained_functions` to overwrite `self._kept_functions = {}` and wipe all retained functions from earlier levels.
5. **Static 1-Line REPL Variable Persistence Reminder (`prompts.py`)**:
   - Appends a single static bullet to `PYTHON_ADDENDUM_TAIL` reminding the model that local variables do not persist across `python` tool calls (only top-level `def` functions persist), preserving 100% SGLang prefix KV-cache reuse.
6. **On-Demand Current-Level Death Ledger (`ARC3_DEATH_LEDGER='1'` + Post-Drain Fallback) & Late Step-Budget Alert (`step_budget.py`)**:
   - Enables the built-in per-instance state-hash-indexed `ARC3_DEATH_LEDGER='1'` (plus `death_ledger` in Python sandbox globals) and adds a 1-line fallback summary of recorded fatal attempt endings on the current level so fatal moves are never repeated after `58k` context drain.
   - Adds `step_budget.py` (`detect_budget` + `step_budget_lines`), which stays completely silent (`0` tokens) on normal turns and emits a 1-line warning only when a shrinking border bar ($\ge 12$ cells) drops to $\le 25\%$ capacity or $\le 12$ remaining actions.

## Verification & Build Commands
```bash
python3 experiments/v5-dprime-pure-guards/verify.py -v
python3 experiments/v5-dprime-pure-guards/build.py
```
