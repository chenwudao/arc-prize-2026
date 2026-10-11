class _PriorityGate:
    """Harness-side admission control, for when the server ignores `priority`.

    The request field is a hint a backend may drop; this enforces the same
    ordering locally by limiting how many games hold a slot at once and
    choosing who gets a freed one.

    A game keeps its slot while its prefix is intact, because interrupting it
    there throws away a cache entry about to be reused. When the trimmer drops
    a message the prefix is invalid anyway and the next request must be
    prefilled from the divergence point - the one moment when yielding is free -
    so that is where the handover happens.

    Release and re-enqueue are one critical section. Releasing first would leave
    a window in which a lower-priority waiter takes the slot the caller was
    about to compete for.
    """

    def __init__(self, slots: int) -> None:
        self._cond = threading.Condition()
        self._free = max(1, int(slots))
        self._waiting: list[tuple[int, int]] = []
        self._seq = 0
        self._admitted: set[int] = set()
        self._snapshots: dict[int, PrioritySnapshot] = {}
        self._clock_start: float | None = None
        self._clock_deadline: float | None = None
        self._tail_fade_announced = False

    def configure_clock(self, started_at: float, deadline: float | None) -> None:
        """One shared monotonic clock, configured before initial admission.

        Earliest session start/deadline wins; appropriate for simultaneously
        launched sessions. No clock is inferred from the last action payload.
        """
        if _get_env_bool("ARC3_PRIORITY_TAIL_FADE", False) and deadline is None:
            raise ValueError("ARC3_PRIORITY_TAIL_FADE requires a finite runtime or soft deadline")
        with self._cond:
            self._clock_start = min(self._clock_start, started_at) if self._clock_start is not None else started_at
            if deadline is not None:
                self._clock_deadline = min(self._clock_deadline, deadline) if self._clock_deadline is not None else deadline

    def _snapshot_priority(self, snapshot: PrioritySnapshot, now: float) -> int:
        elapsed = max(0.0, now - self._clock_start) if self._clock_start is not None else 0.0
        endgame = _endgame_start_minutes() > 0 and elapsed >= 60 * _endgame_start_minutes()
        tail_fraction = None
        if _get_env_bool("ARC3_PRIORITY_TAIL_FADE", False):
            if self._clock_deadline is None or self._clock_start is None:
                raise ValueError("ARC3_PRIORITY_TAIL_FADE requires a finite runtime or soft deadline")
            fraction_setting = os.environ.get("ARC3_PRIORITY_TAIL_FADE_FRACTION", "").strip()
            if fraction_setting:
                try:
                    fraction = float(fraction_setting)
                except ValueError:
                    raise ValueError("ARC3_PRIORITY_TAIL_FADE_FRACTION must be > 0 and <= 1") from None
                if not 0.0 < fraction <= 1.0:
                    raise ValueError("ARC3_PRIORITY_TAIL_FADE_FRACTION must be > 0 and <= 1")
                # Use the full shared run duration, not the shrinking time left.
                window = fraction * max(0.0, self._clock_deadline - self._clock_start)
            else:
                window = max(1.0, 60 * _get_env_float("ARC3_PRIORITY_TAIL_FADE_MINUTES", 90.0))
            remaining = max(0.0, self._clock_deadline - now)
            tail_fraction = remaining / window if window > 0.0 else 0.0
            if remaining <= window:
                # Snapshot scoring also happens outside _pump's lock. Announce
                # once per shared gate, even when several games trim together.
                with self._cond:
                    if not self._tail_fade_announced:
                        self._tail_fade_announced = True
                        log.warning(
                            "tail fade phase after %.1f minutes: %.1f minutes "
                            "remaining; fading tail B to zero over the final "
                            "%.1f minutes, retaining hazard C",
                            elapsed / 60.0, remaining / 60.0, window / 60.0,
                        )
        return priority_value(
            snapshot, endgame=endgame, tail_fraction=tail_fraction,
            human_actions=_priority_human_actions(), action_scale=_priority_action_scale(),
            token_scale=_priority_token_scale(), action_weight=_priority_action_weight(),
            tail_base=_priority_tail_base(), tail_cap=_priority_tail_cap(),
            **_priority_level_options(),
        )

    def acquire(self, priority: int) -> None:
        with self._cond:
            self._enqueue_and_wait(priority)

    def release(self) -> None:
        with self._cond:
            self._free += 1
            self._pump()

    def handover(self, priority: int, snapshot: PrioritySnapshot | None = None) -> None:  # noqa: D401
        """Give up the slot and immediately compete for it again.

        The caller may win it straight back, which is the right outcome when
        nothing else is waiting or everything else is further along.
        """
        _t0 = time.monotonic()
        with self._cond:
            self._free += 1
            self._enqueue_and_wait(priority, snapshot)
        _GATE_STATS["handover_ms"] += int(1000 * (time.monotonic() - _t0))

    def _enqueue_and_wait(self, priority: int, snapshot: PrioritySnapshot | None = None) -> None:
        # TEMPORARY: with slots == games nobody should ever block here
        _GATE_STATS["enqueued"] += 1
        self._seq += 1
        token = self._seq
        if snapshot is not None:
            self._snapshots[token] = snapshot
        # negated so the heap pops the HIGHEST priority; the sequence number
        # breaks ties by arrival
        heapq.heappush(self._waiting, (-int(priority), token))
        self._pump()
        if token not in self._admitted:
            _GATE_STATS["blocked"] += 1
            t0 = time.monotonic()
            while token not in self._admitted:
                self._cond.wait()
            _GATE_STATS["blocked_ms"] += int(1000 * (time.monotonic() - t0))
        self._admitted.discard(token)

    def _pump(self) -> None:
        if _priority_refresh_enabled() and self._free > 0:
            now = time.monotonic()
            self._waiting = [
                (-self._snapshot_priority(self._snapshots[token], now), token)
                if token in self._snapshots else (priority, token)
                for priority, token in self._waiting
            ]
            heapq.heapify(self._waiting)
        woke = False
        while self._free > 0 and self._waiting:
            _, token = heapq.heappop(self._waiting)
            self._snapshots.pop(token, None)
            self._admitted.add(token)
            self._free -= 1
            woke = True
        if woke:
            self._cond.notify_all()
