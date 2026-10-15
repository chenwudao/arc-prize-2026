# V3 Postmortem, Top-Kernel Landscape Analysis, and V4 (`v4-stagnation-anima`) Design

**Date**: 2026-10-15  
**Current Best Score**: **28.04** (V2 `v2-d-prime`, Submission `57062234`)  
**Target Tier**: **31.0 – 34.0+**

---

## 1. Executive Summary of Recent Submissions

| Version | Date (UTC) | Submission ID | Public LB | $\Delta$ vs V2 | Core Configuration |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **V1 (`v1-d-prime`)** | 2026-10-11 | `56988179` | **24.22** | -3.82 | D' priority function, but `install_d` left D's original fresh-game gate intact |
| **V2 (`v2-d-prime`)** | 2026-10-12 | `57062234` | **28.04** | **0.00** | Clean D' priority + `install_d` replacing D's fresh-game gate |
| **V3 (`v3-cognitive-guard`)** | 2026-10-13 | `57142410` | **26.45** | -1.59 | V2 + `ARC3_GUARDS_FROM_LEVEL=1` + `NOOP_REPEAT_GUARD=1` + 24-action `[STRATEGY AUDIT]` |
| **Cleared-Level Memory v1** | 2026-10-14 | `57189269` | **22.60** | -5.44 | Sliding context window (`MAX_RECENT_TURNS=5`) + cleared-level memory summary |

---

## 2. Root-Cause Postmortem: Why V3 (26.45) and Memory-v1 (22.60) Regressed

### 2.1 Why V3 Dropped 1.59 Points (`28.04` $\to$ `26.45`)
1. **Enabling Strict Guards on Level 1 (`ARC3_GUARDS_FROM_LEVEL=1`, `ARC3_NOOP_REPEAT_GUARD=1`, `ARC3_DEATH_REPEAT_GUARD=1`)**:
   - In `ARC3-Inference/src/inference/tool_agent.py` (`_guards_active`), the baseline harness sets `ARC3_GUARDS_FROM_LEVEL=2` with an explicit comment:
     > *"Only enable no-op / death guards once the agent has cleared at least one level — on level 1 it knows nothing about the game yet and needs freedom to probe."*
   - When V3 forced `ARC3_GUARDS_FROM_LEVEL=1` and `ARC3_NOOP_REPEAT_GUARD=1`, any exploratory Python loop on Level 1 that hit an impassable wall or tested an inactive button was immediately aborted on the very first no-op, preventing the model from completing multi-step discovery probes in `exec()`.
2. **Directive Advice Injection (`[STRATEGY AUDIT]` every 24 actions)**:
   - Public ablation studies on `Qwen3.8-Flash-Next` (`leoprovorov/fable-astra-play-arc-3-handbook-harness`) established a clear empirical law: **"Add facts, not advice."**
   - Injecting prescriptive natural-language advice into user turn prompts distracts the fine-tuned LoRA adapters from structured Python tool synthesis and increases redundant replanning overhead.

### 2.2 Why Cleared-Level Memory v1 Dropped 5.44 Points (`28.04` $\to$ `22.60`)
- Continuously truncating `_history_messages` to a 5-turn sliding window (`MAX_RECENT_TURNS = 5`) inside an active level strips the model of its own recent experimental hypotheses and multi-turn deduction chains, causing it to repeat earlier exploration steps and inflating total action counts (which are penalized quadratically by $\text{RHAE} \propto (\text{Human}/\text{Agent})^2$).

---

## 3. Survey of Top Public Solutions (30.74 – 31.54+ Tier)

We pulled and inspected the top-scoring public Kaggle kernels as of 2026-10-15:

1. **`shiiin9/affectify-arc-31-54-in-a-single-sub` (31.54)** & **`jeannkouagou/arc-agi-3-29-in-a-single-submission` (29.74)**:
   - Pure TAAF (`Thinking and Acting Fast`) baseline with D' scheduler (`_priority_d_prime`), proving that uncorrupted Level-1 exploration + D' scheduling can reach 28–31.5 on low-variance runs, though run-to-run stochasticity remains $\sim \pm 1.8$ points.
2. **`ouyangruize/arc-agi-3-milestone-2-solution` (30.74 base + v2 animation fix)**:
   - Identified a critical bug in `solver.py` and `tool_agent.py`: when an action triggers a multi-frame animation that returns to the initial board state (`changed_pixels == 0`, `animation.transient_pixels > 0`), the harness labels the action `no-op (board unchanged)`. Fixing this verdict prevents the agent from falsely pruning timing-based or boomerang mechanics.
3. **`heliosli/try-merging-it-you-might-get-lucky-and-win-gold` & `yukailiu/arc-agi-3-champion-solution`**:
   - **96k-Token Stagnation Context Restart**: Instead of sliding-window truncation on every turn, let the model keep its full history until a single unfinished level consumes $\ge 96\text{k}$ generated tokens (`98,304` tokens). At that point, wipe `_history_messages` and `_kept_functions` **once per level** while keeping the live game board and Python `history`/`transitions`/`death_ledger` intact.
   - **Post-Death Edge Meter (`edge_meter.py`)**: Automatically measures monotone two-color shrinking bars along the 4 edges of the 64x64 grid on post-death diagnostic turns, giving the model exact step-cost/fuel-bar facts without prescriptive advice.
   - **Component BBox & Spatial Helpers (`segmentation.py`)**: Adds `bbox_rc`, `bbox_center2_rc`, `rot90/180/270`, `flipv/fliph`, `manhattan_distance`, and `find_cells`.

---

## 4. Architecture of V4 (`v4-stagnation-anima`)

V4 combines our proven **V2 (`28.04`)** D' scheduler with the structural harness fixes above:

```
┌───────────────────────────────────────────────────────────────────────────┐
│                   V4: v4-stagnation-anima Architecture                    │
├───────────────────────────────────────────────────────────────────────────┤
│ 1. Scheduler Layer (Cell 17: install_d)                                   │
│    • Clean V2 D' priority: unsolved games (score == 0) prioritized first  │
│    • Replaces D's fresh-game admission gate with _priority_d_prime        │
│    • Restores ARC3_GUARDS_FROM_LEVEL=2 & EXPOSE_RESET='on'                │
├───────────────────────────────────────────────────────────────────────────┤
│ 2. Harness Patch Layer (Cell 4: apply_v4_harness_patches)                 │
│    • Executed BEFORE Cell 14 unpickles benchmark_initial.pkl              │
│    • stagnation_restart.py: 1x per-level context wipe at 96k tokens       │
│      (preserves live board + Python history / transitions / death_ledger) │
│    • Animation-aware verdict in solver.py & tool_agent.py                 │
│      (distinguishes transient_pixels > 0 from pure no-op)                 │
│    • Empty animation schema fix in animation.py                           │
│    • edge_meter.py: objective HUD timer/bar measurement after deaths      │
│    • segmentation.py: bbox_rc, bbox_center2_rc & spatial grid helpers     │
└───────────────────────────────────────────────────────────────────────────┘
```
