from __future__ import annotations

import safety_gateway.main as gateway_main
from safety_gateway.main import HubClock


def test_hub_clock_maps_polls_onto_normalized_timeline(monkeypatch) -> None:
    local = [10_000_000_000_000]
    monkeypatch.setattr(gateway_main, "now_monotonic_ns", lambda: local[0])
    clock = HubClock()
    assert clock.now_ns() == local[0]  # no hub time seen yet

    assert clock.observe(2_000_000_000) == 2_000_000_000
    local[0] += 300_000_000
    assert clock.now_ns() == 2_300_000_000


def test_hub_clock_falls_back_when_event_has_no_normalized_time(monkeypatch) -> None:
    monkeypatch.setattr(gateway_main, "now_monotonic_ns", lambda: 5)
    assert HubClock().observe(None) == 5
