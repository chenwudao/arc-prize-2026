# V5 Breakthrough Analysis (`31.18` LB) & V6 Generalizable Architecture (`v6-dprime-smart-guards-memory`)

**Date**: 2026-10-18  
**Baseline**: V5 (`57305102`, Public LB **31.18**, `+3.86` vs V4 `27.32`, `+3.14` vs V2 `28.04`)  
**Target**: Push toward **38+** with 100% game-agnostic mechanisms that generalize to the 50% unseen Private Leaderboard.

---

## 1. Historical Leaderboard Trajectory

| Iteration | Submission ID | Public LB Score | Delta vs Prev | Core Architectural Characteristics |
| :--- | :---: | :---: | :---: | :--- |
| **V1** (`v1-dprime-coverage`) | `56988179` | `24.22` | — | D' formula defined, but `_PriorityGate.acquire` still used fresh-first bypass |
| **V2** (`v2-dprime-full-install`) | `57062234` | `28.04` | `+3.82` | Clean `install_d` hooking `_PriorityGate.acquire` + `EXPOSE_RESET` off |
| **V3** (`v3-dprime-scoped-PersistGuard`) | `57142410` | `26.45` | `-1.59` | Added 8 bundled changes including `EXPOSE_RESET='on'` + `96k` hard restart |
| **Memory v1** (`arc3-memory-v1`) | `57189269` | `22.60` | `-3.85` | Prompt-injected episodic memory polluting SGLang prefix KV-cache |
| **V4** (`v4-dprime-verified- fixes`) | `57218570` | `27.32` | `+0.87` (vs V3) | Fixed 3 code bugs in V3, but retained `EXPOSE_RESET='on'` and `96k` wipe |
| **V5** (`v5-dprime-pure-guards`) | `57305102` | **`31.18`** | **`+3.86`** (vs V4) | Reverted `EXPOSE_RESET` & `96k` wipe; added 3-point animation guard, 30s timeout helper retention, `ARC3_DEATH_LEDGER='1'` (+ fallback), and late `step_budget.py` alert |

---

## 2. Why V5 Achieved the `31.18` Breakthrough (`+3.86` over V4)

1. **Eliminating `EXPOSE_RESET='on'` (Stopping Voluntary $4\times$ RHAE Self-Sabotage)**:
   - Under $\text{RHAE}_i = \min(115, 100 \times (h_i / a_i)^2)$, every voluntary mid-level `RESET` keeps all prior actions in the level denominator $a_i$, cutting the level score to $\approx \frac{1}{4}$. Keeping `EXPOSE_RESET` off (with `EXPOSE_UNDO='on'`) preserved action efficiency on mid-to-deep levels.
2. **Removing `stagnation_restart.py` (`96k` Hard Wipe) + Adding Transactional 30s Timeout Helper Retention**:
   - Prevented games from forcibly yielding their active SGLang GPU slot via `_note_history_evicted()` at `96k` tokens.
   - Fixed the upstream bug in `ToolAgent._record_retained_functions` where a 30s Python BFS timeout (`"keepable_functions" not in sandbox_result`) wiped `self._kept_functions = {}`. Preserving validated board parsers and simulators across timeouts on Levels 3–8 (which carry the highest linear weights $i / \sum i$) allowed the agent to immediately refine its search depth and clear deep levels.
3. **Complete 3-Point Animation-Aware Guard**:
   - Exempted actions with intermediate frame animations (`transient_pixels > 0`) from `_stale_state` blocks and batch `no_op_action` aborts across `python_tool_sandbox.py`, `solver.py`, and `tool_agent.py`.
4. **Zero-Prefix-Overhead `ARC3_DEATH_LEDGER='1'` (+ Post-Drain Fallback) & Late `step_budget.py` Alert**:
   - Added `0` tokens on normal turns (100% SGLang RadixAttention prefix KV-cache hit rate), speaking up only when the current board state hash matched a prior fatal path or when a shrinking border bar dropped to $\le 25\%$ / $\le 12$ steps.

---

## 3. V6 Design: 4 Game-Agnostic Upgrades for Pushing Toward `38+`

### 3.1 Pre-Execution State-Hash Guards (`level >= 2`, Overridable on Immediate Repeat)
- **`ARC3_DEATH_REPEAT_GUARD='1'` (with `_fatal_prefix_match` lookahead)**:
  - In V5, `ARC3_DEATH_LEDGER='1'` only emitted text advisories at the start of a turn for the turn's initial board state $H_0$. If a multi-step batch `action([...])` transitioned into an intermediate state $H_k$ from which the next move (or suffix) previously caused `GAME_OVER`, nothing stopped the engine from executing it and killing the attempt.
  - With `ARC3_DEATH_REPEAT_GUARD='1'`, `ToolAgent._action_guard_hook` checks every position of a batch against `_death_ledger_index` before execution and raises `KnownDeathActionError` (`0` actions spent, attempt preserved intact, overridable if the model immediately re-issues the action).
- **Animation-Safe `ARC3_NOOP_REPEAT_GUARD='1'` & `ARC3_REPEAT_STATE_GUARD='1'`**:
  - Upstream left `ARC3_NOOP_REPEAT_GUARD` off because `solver.py` (`gameplay_changed_per_action`) and `tool_agent.py` (`_record_guard_observations`) did not check `animation.transient_pixels > 0`, causing animated bounces/pulses to be recorded as permanent no-ops.
  - V6 patches both `gameplay_changed_per_action` in `solver.py` and `_record_guard_observations` in `tool_agent.py` to check `or (animation or {}).get("transient_pixels", 0)`, making `NoopRepeatGuard` 100% animation-safe.
  - Enables `ARC3_NOOP_REPEAT_GUARD='1'` (blocks repeated no-ops from identical board states on `level >= 2`, overridable) and `ARC3_REPEAT_STATE_GUARD='1'` (per-snippet cycle breaker that stops buggy loops from oscillating across revisited `(state_hash, action_sig)` pairs).

### 3.2 Persistent Scoped Sandbox Data Memory (`scoped_memory.py` / `ARC3_SCOPED_MEMORY='1'`)
- Provides `scratch = {'game': {}, 'level': {}, 'step': {}}` (bounded to 128 KiB JSON) inside every Python sandbox invocation:
  - `scratch['game']`: persists across the entire game session.
  - `scratch['level']`: persists across turns and deaths on the current level; cleared automatically on level transition.
  - `scratch['step']`: persists across inspection calls on the current step; cleared automatically in-place whenever `step` or `level` changes.
- Stored in host process memory (`self._scratch_memory`) and never injected into the LLM User Prompt (0 dynamic prompt tokens, 100% KV-cache preservation), with transactional 30s timeout retention.

### 3.3 Spatial Grounding on Death & Level Transitions
- **`ARC3_GAMEOVER_DIFF='1'`**: Injects compact object-level textual diffs (`last_alive -> death_frame`) on `GAME_OVER` turns alongside the visual diff image so the model has exact `(row, col)` coordinates of the fatal change without spending an extra Python tool call.
- **`ARC3_LEVEL_INVENTORY='1'`**: On the first turn (`action_num == 0`) of `level >= 2`, compares the new level's starting board against the previous level's starting board (`START-vs-START`) and highlights newly `appeared` object types.

### 3.4 Truncated Reasoning Recovery (`ARC3_STUB_DEAD_REASONING='1'`)
- Replaces truncated reasoning-only replies (`finish_reason=length`, no tool call, ~35k chars) with a short stub at the tail of the current turn (and drops it at turn end), preventing truncated thoughts from consuming the `58k` context budget.

---

## 4. V6 Smoke Test Validation (5-Minute, 4 Games, RTX PRO 6000) & Formal Submission

| Metric / Game | V3 / V4 (`26.45` / `27.32` LB) | V5 (`31.18` LB) | **V6 (`v6-dprime-smart-guards-memory`)** |
| :--- | :---: | :---: | :---: |
| **Mean Score** | `0.89` | `1.86` | **`2.78` (`+49.5%` vs V5)** |
| **Median Score** | `0.00` | `1.34` | **`3.17` (`+136.6%` vs V5)** |
| **Games Clearing Level 1 (in 5m)** | `1 / 4` | `2 / 4` | **`3 / 4`** |
| **Total Actions (4 games)** | `172` | `186` | **`88` (high RHAE efficiency)** |
| **Throughput (tok/s)** | `316.0` | `311.79` | **`331.76`** |
| `m0r0-492f87ba` | `3.57` (`38` act) | `4.76` (`51` act) | **`4.76` (`18` act)** |
| `tn36-ef4dde99` | `0.00` (`48` act) | `2.67` (`49` act) | **`3.57` (`29` act)** |
| `sk48-d8078629` | `0.00` (`45` act) | `0.00` (`66` act) | **`2.78` (`25` act)** |
| `bp35-0a0ad940` | `0.00` (`41` act) | `0.00` (`20` act) | `0.00` (`16` act) |

- **Active V6 Telemetry in Smoke Test (`*_requests.jsonl`)**:
  - `scratch_saved_keys` (`scratch['game'|'level'|'step']`): active `144` times in `bp35`, `4` times in `m0r0`, `9` times in `sk48`.
  - `function_retention` (`_kept_functions` + 30s timeout preservation): active `113` (`bp35`), `171` (`m0r0`), `107` (`sk48`), `252` (`tn36`) times.
  - `ARC3_LEVEL_INVENTORY='1'` (`New level` START-vs-START inventory): emitted cleanly on every level transition (`m0r0`, `sk48`, `tn36`).
- **Formal Competition Submission**:
  - **Kernel**: `jessewudao/arc3-v6-dprime-smart-guards-memory` (v1)
  - **Submission ID**: `57338741` (`2026-10-18 04:40:42 UTC`, `SubmissionStatus.PENDING`)

