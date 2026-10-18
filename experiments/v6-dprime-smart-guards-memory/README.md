# ARC3 V6: D-Prime + Pre-Execution State-Hash Guards + Scoped Sandbox Memory

## Overview
Built directly on our **V5 (`v5-dprime-pure-guards`) breakthrough (`31.18` Public LB, `+3.86` over V4, `+3.14` over V2)**, **V6 (`v6-dprime-smart-guards-memory`)** retains 100% of V5's verified gains while addressing the four remaining game-agnostic bottlenecks to push toward **38+** across both the 50% Public LB and 50% Private LB:

1. **Pre-Execution Whole-Frame State-Hash Guards (`level >= 2`, Overridable on Immediate Repeat)**:
   - `ARC3_DEATH_REPEAT_GUARD='1'` (with `_fatal_prefix_match` lookahead): refuses known-fatal actions or batch suffixes from an identical whole-frame board state (`_state_identity_border() == 0`) **before** sending them to the game engine (`0` actions spent, attempt preserved intact).
   - `ARC3_NOOP_REPEAT_GUARD='1'` + **Complete 4-Point Animation-Safety**: extends V5's `transient_pixels > 0` check to `solver.py` (`gameplay_changed_per_action`) and `tool_agent.py` (`_record_guard_observations`), eliminating the upstream false-noop limitation on animated actions while blocking repeated no-ops from identical board states on `level >= 2`.
   - `ARC3_REPEAT_STATE_GUARD='1'`: per-snippet `(state_hash, action_sig)` cycle breaker that halts buggy Python `while` loops before they burn 20–30 actions oscillating across revisited states.
2. **Persistent Scoped Sandbox Data Memory (`scoped_memory.py` / `ARC3_SCOPED_MEMORY='1'`)**:
   - Exposes `scratch = {'game': {}, 'level': {}, 'step': {}}` (bounded to 128 KiB JSON) inside every Python tool call so parsed layouts, hazard coordinates, switch mappings, and BFS graphs persist across calls without adding a single dynamic token to the LLM User Prompt (100% SGLang RadixAttention prefix KV-cache preservation).
   - Includes **transactional 30s timeout protection** for both `_kept_functions` and `_scratch_memory`.
3. **Spatial Grounding on Death & Level Transitions**:
   - `ARC3_GAMEOVER_DIFF='1'`: emits exact object-level text diffs (`last_alive -> death_frame`) on `GAME_OVER` turns alongside the visual diff image.
   - `ARC3_LEVEL_INVENTORY='1'`: emits a `START-vs-START` object inventory on the first turn of each new level (`level >= 2`), highlighting newly `appeared` object types as likely new mechanics.
4. **Truncated Reasoning Recovery (`ARC3_STUB_DEAD_REASONING='1'`)**:
   - Replaces truncated reasoning-only replies (`finish_reason=length`, no tool call) with a compact stub at the tail of the turn so retries do not pollute context or accelerate `58k` history eviction.

## Verification
```bash
python3 experiments/v6-dprime-smart-guards-memory/verify.py -v
python3 experiments/v6-dprime-smart-guards-memory/build.py
```

## Kaggle Smoke Test (5-Minute, 4 Games, RTX PRO 6000) & Formal Submission
- **Kernel**: `jessewudao/arc3-v6-dprime-smart-guards-memory` (v1) — `KernelWorkerStatus.COMPLETE` (`1206.8s` total wallclock, `331.76` generated tokens/sec).
- **Smoke Test Score Progression**:
  - **V3 / V4**: `mean score: 0.89`, `median score: 0.00` (1/4 games cleared Level 1)
  - **V5 (`31.18` LB)**: `mean score: 1.86`, `median score: 1.34` (2/4 games cleared Level 1: `m0r0` `4.76` [51 actions], `tn36` `2.67` [49 actions])
  - **V6**: **`mean score: 2.78`, `median score: 3.17`** (`+49.5%` mean over V5, `3.12x` over V3/V4) — **3/4 games cleared Level 1 in 5 minutes**:
    - `m0r0-492f87ba`: `score=4.76`, `levels=1.0/6`, `actions=18` (vs `51` in V5), `tokens=25675`
    - `tn36-ef4dde99`: `score=3.57` (vs `2.67` in V5), `levels=1.0/7`, `actions=29` (vs `49` in V5), `tokens=25453`
    - `sk48-d8078629`: `score=2.78` (vs `0.00` in V3/V4/V5), `levels=1.0/8`, `actions=25` (vs `66` in V5), `tokens=27441`
    - `bp35-0a0ad940`: `score=0.00`, `levels=0.0/9`, `actions=16`, `tokens=23185`
- **Formal Competition Submission**:
  - **Submission ID**: `57338741` (`2026-10-18 04:40:42 UTC`, `SubmissionStatus.PENDING`)

