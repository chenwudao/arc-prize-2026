# V4: `v4-stagnation-anima`

**Clean D' Priority + 96k-Token Stagnation Context Restart + Animation-Aware No-Op Fix + Post-Death Edge Meter + Component Geometry**

## 1. Motivation & Postmortem of V3 (26.45)

| Version | Submission ID | LB Score | Key Changes | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **V1** | `56988179` | **24.22** | D' priority without `install_d` fresh-game gate replacement | Partial D' activation |
| **V2** | `57062234` | **28.04** | Clean D' + `install_d` replacing D's fresh-game admission gate | **Current Best** (+3.82 vs V1) |
| **V3** | `57142410` | **26.45** | V2 + `ARC3_GUARDS_FROM_LEVEL=1` + `NOOP_REPEAT_GUARD=1` + 24-action `[STRATEGY AUDIT]` | Regressed (-1.59 vs V2) |
| **Memory v1** | `57189269` | **22.60** | Cleared-level memory summary injection (`MAX_RECENT_TURNS=5`) | Regressed (-5.44 vs V2) |

### Why V3 Regressed (-1.59 vs V2)
1. **Premature Level-1 Guards (`ARC3_GUARDS_FROM_LEVEL=1`, `ARC3_NOOP_REPEAT_GUARD=1`)**:
   In `tool_agent.py` (`_guards_active`), Daniel Franzen's base harness intentionally disables repeat/death guards on Level 1 (`ARC3_GUARDS_FROM_LEVEL=2`) because on Level 1 the agent has zero prior knowledge of the game rules and must probe action semantics (sometimes repeating actions or testing hazards). Activating strict 1-strike repeat guards on Level 1 prematurely truncated exploratory tool loops.
2. **Directive Prompt Injection (`[STRATEGY AUDIT]`)**:
   As demonstrated in public ablations (`leoprovorov/fable-astra-play-arc-3-handbook-harness`), injecting multi-line behavioral *advice* into the turn prompt degrades `Qwen3.8-Flash-Next` tool-calling accuracy ("Add facts, not advice").

## 2. Core Components of V4 (`v4-stagnation-anima`)

V4 starts cleanly from **V2 (`28.04`)**, reverts all V3 guard/prompt interferences, and integrates five targeted, high-leverage structural improvements verified across top 30.74–31.54+ public solutions:

1. **Clean V2 D' Priority & `install_d` Admission Gate Replacement**:
   - Retains `ARC3_GUARDS_FROM_LEVEL=2` (default) and sets `EXPOSE_RESET='on'`.
   - Prioritizes zero-score game attempts before revisit phases while keeping the 2-level cap and dynamic batch sizing (`B=1/2/4`).
2. **96k-Token Stagnation Context Restart (`stagnation_restart.py`)**:
   - When the agent generates $\ge 98,304$ tokens (`96 * 1024`) on an **unfinished level** (`levels_completed == _level_at_attempt_start`), its multi-turn conversation window (`_history_messages`) and stale helper functions (`_kept_functions`) are wiped **once per level**, restarting reasoning from a clean context window.
   - Crucially, the **live game board is NOT reset**, and the Python sandbox retains all accumulated factual state (`history`, `transitions`, `death_ledger`).
3. **Animation-Aware No-Op & Stale-State Fix (`solver.py`, `tool_agent.py`, `python_tool_sandbox.py`)**:
   - In multi-frame animated games, an action can trigger intermediate movement frames (`animation.transient_pixels > 0`) before the board settles back to its starting pixels (`changed_pixels == 0`).
   - Previously, `_action_verdict` in `solver.py` and the action trace in `tool_agent.py` labeled these actions `no-op (board unchanged)`, causing the model to discard valid mechanics (e.g., temporary bridges, projectiles, pulsing switches).
   - V4 detects `transient_pixels > 0` and reports `animated return (settled back to start after N transient px; not a pure no-op)`.
   - Also fixes `Empty animation` in `animation.py` to include `'action': str(action_label), 'frames': 0, 'steps': []`.
4. **Objective Post-Death Edge Meter (`edge_meter.py`)**:
   - On post-death diagnostic turns (`died_count > 0`), inspects the 4 outer edges (`top`, `bottom`, `left`, `right`) of the 64x64 frame across the level's action history to detect monotone two-color shrinking HUD timer/fuel bars and appends a single factual measurement line (`Edge meter: ...`).
5. **Component Bounding-Box Geometry & Spatial Helpers (`segmentation.py`)**:
   - Enriches `components()` output dictionaries with `bbox_rc` and `bbox_center2_rc` (doubled integer center coordinates avoiding float rounding).
   - Exports `rot90`, `rot180`, `rot270`, `flipv`, `fliph`, `manhattan_distance`, and `find_cells` into the Python sandbox globals.

## 3. Build & Verification

- Verify locally:
  ```bash
  python3 experiments/v4-stagnation-anima/verify.py
  ```
- Build upload package:
  ```bash
  python3 experiments/v4-stagnation-anima/build.py
  ```
