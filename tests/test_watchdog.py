import watchdog


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(clock, **kw):
    return watchdog.Watchdog(clock=clock, freeze_seconds=90, cooldown_seconds=600, max_per_hour=3, **kw)


def run(wd, clock, frame, seconds, step=10):
    """Feed the same frame every `step` s for `seconds`; return list of non-None actions."""
    actions = []
    for _ in range(seconds // step):
        clock.t += step
        a = wd.step(frame)
        if a:
            actions.append(a)
    return actions


def test_changing_frames_never_reboot():
    clock = Clock()
    wd = make(clock)
    for i in range(100):
        clock.t += 10
        assert wd.step(f"frame{i}") is None


def test_frozen_frame_triggers_reboot_after_freeze_window():
    clock = Clock()
    wd = make(clock)
    wd.step("a")
    assert run(wd, clock, "a", 80) == []
    assert run(wd, clock, "a", 10) == ["reboot"]


def test_unreachable_device_is_not_rebooted_and_resets_tracking():
    clock = Clock()
    wd = make(clock)
    wd.step("a")
    assert run(wd, clock, None, 300) == []
    # frozen timer restarts once reachable again
    assert run(wd, clock, "a", 80) == []


def test_cooldown_blocks_second_reboot_then_allows():
    clock = Clock()
    wd = make(clock)
    wd.step("a")
    assert run(wd, clock, "a", 90) == ["reboot"]
    assert run(wd, clock, "a", 400) == []          # still frozen, inside cooldown
    assert run(wd, clock, "a", 200) == ["reboot"]  # cooldown (600s) elapsed


def test_hourly_cap():
    clock = Clock()
    wd = watchdog.Watchdog(clock=clock, freeze_seconds=90, cooldown_seconds=100, max_per_hour=3)
    wd.step("a")
    got = run(wd, clock, "a", 3000)
    assert got == ["reboot"] * 3
    clock.t += 4000
    wd.step("a")
    assert run(wd, clock, "a", 100) == ["reboot"]  # old reboots aged out
