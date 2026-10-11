"""D-prime scoring from Affectify, with Franzen's fresh-first gate retained.

Sources:
https://www.kaggle.com/code/shiiin9/affectify-arc-31-54-in-a-single-sub
https://github.com/da-fr/arc-agi-3-solution
No game IDs, private/public membership or human baseline answers are used.
"""
from __future__ import annotations

import math
import os

VERSION = "v1-dprime-coverage"
SCALE = 1000


def _finite(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return value if math.isfinite(value) else float(default)


class ObservedPace:
    """Mean generated tokens per level actually cleared in this game."""

    def __init__(self):
        self.completed = 0
        self.tokens = 0.0

    def record_completion(self, tokens_used, reference_tokens=0.0):
        self.completed += 1
        self.tokens += max(0.0, _finite(tokens_used))

    def cost_multiplier(self):
        return self.tokens / self.completed if self.completed else 0.0


def dprime_priority(state, *, tail_fraction=None, **unused):
    level = max(1, int(_finite(state.level, 1)))
    raw_total = _finite(getattr(state, "total_levels", None), 10)
    total = int(raw_total) if raw_total > 0 and raw_total.is_integer() else 10
    # Match the public D-prime normalization; total itself determines remaining levels.
    bounded_total = min(10, max(6, total))
    normalization = 55 / (bounded_total * (bounded_total + 1) / 2)
    actions = max(0.0, _finite(state.actions))
    tokens = max(0.0, _finite(state.tokens))
    pace = max(0.0, _finite(getattr(state, "cost_multiplier", 0.0)))

    immediate = (1 + 0.5 * (level - 1)) * normalization
    immediate *= (300 / (300 + actions)) ** 2.5
    if pace > 0:
        immediate *= min(4.0, max(0.25, (30_000 / max(1.0, pace)) ** 0.4))

    relative_cost = (pace if pace > 0 else 30_000) / 30_000
    token_allowance = 225_000 * min(2.0, max(0.5, relative_cost)) ** 0.5
    patience = (0.1 * max(0.1, 1 - actions / 115)
                + 0.9 * max(0.1, 1 - tokens / token_allowance))
    remaining = max(0, total - level)
    continuation = (0.0, 10.0, 14.0, 16.0)[min(remaining, 3)]
    fade = 1.0 if tail_fraction is None else min(1.0, max(0.0, _finite(tail_fraction)))
    # Stay below the warm/fresh cache bands of the original scheduler.
    return min(999_999, max(1, int(SCALE * (immediate * patience + continuation * fade))))


def install(tool_agent):
    required = ("priority_value", "ProgressPace", "_PriorityGate", "PrioritySnapshot",
                "_PRIORITY_UNTRIMMED_BASE", "_PRIORITY_BAND")
    missing = [name for name in required if not hasattr(tool_agent, name)]
    if missing:
        raise RuntimeError(f"Unexpected Franzen harness: missing {missing}")
    if tool_agent._PRIORITY_BAND != 1_000_000:
        raise RuntimeError("Unexpected priority bands")
    if getattr(tool_agent, "_arc3_iteration_version", None) == VERSION:
        return
    # Do not replace acquire/handover: fresh games keep original coverage priority,
    # and warm streams keep their admission until trimming or completion.
    tool_agent.priority_value = dprime_priority
    tool_agent.ProgressPace = ObservedPace
    tool_agent._arc3_iteration_version = VERSION
    os.environ.update({
        "ARC3_PRIORITY_PACE": "1",
        "ARC3_PRIORITY_REFRESH_QUEUE": "1",
        "ARC3_PRIORITY_TAIL_FADE": "1",
        "ARC3_PRIORITY_TAIL_FADE_FRACTION": "0.4",
    })
    print(f"#ARC3_ITERATION {VERSION} installed; fresh-first retained; tail fade=0.4",
          flush=True)
