from __future__ import annotations

import time

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.unit.event_hub.helpers import new_hub, start_session, unnormalized_event


def test_normalized_timestamps_never_go_backward_within_producer() -> None:
    hub = new_hub()
    start_session(hub)
    source = "ganglion-emg"
    base = time.monotonic_ns()
    arrivals = [base + 10_000_000, base + 3_000_000, base + 20_000_000]
    for index, received in enumerate(arrivals):
        published = hub.ingest(
            unnormalized_event(
                event_type="biosignal.chunk",
                source=source,
                event_id=f"mono{index:08d}aaaaaaaa",
                sequence=index,
                received_monotonic_ns=received,
            )
        )
        assert published is not None
    times = [event.normalized_time_ns for event in hub.published if event.source == source]
    assert times == sorted(times)
    assert hub.metrics.clock_jumps == 1


@given(
    sequences=st.lists(st.integers(min_value=0, max_value=500), min_size=1, max_size=40),
    deltas=st.lists(
        st.integers(min_value=-8_000_000, max_value=25_000_000),
        min_size=1,
        max_size=40,
    ),
)
@settings(max_examples=40, deadline=None)
def test_property_normalized_time_and_sequence(sequences: list[int], deltas: list[int]) -> None:
    n = min(len(sequences), len(deltas))
    sequences = sequences[:n]
    deltas = deltas[:n]
    hub = new_hub()
    start_session(hub)
    source = "prop-producer"
    received = max(time.monotonic_ns(), 10_000_000)
    expected_gaps = 0
    expected_regressions = 0
    last_seq: int | None = None
    for index, (seq, delta) in enumerate(zip(sequences, deltas, strict=True)):
        received = max(0, received + delta)
        event_id = f"prop{index:010d}"
        published = hub.ingest(
            unnormalized_event(
                source=source,
                event_id=event_id,
                sequence=seq,
                received_monotonic_ns=received,
            )
        )
        assert published is not None
        if last_seq is not None:
            if seq > last_seq + 1:
                expected_gaps += 1
            elif seq != last_seq + 1:
                expected_regressions += 1
        last_seq = seq
    times = [event.normalized_time_ns for event in hub.published if event.source == source]
    assert all(t is not None for t in times)
    assert times == sorted(times)
    assert hub.metrics.sequence_gaps == expected_gaps
    assert hub.metrics.sequence_regressions == expected_regressions
    assert hub.metrics.duplicate == 0


@given(st.lists(st.integers(min_value=0, max_value=20), min_size=2, max_size=15))
@settings(max_examples=25, deadline=None)
def test_property_duplicate_ids_publish_once(values: list[int]) -> None:
    hub = new_hub()
    event_id = "dupprop00000001"
    published_count = 0
    for index, seq in enumerate(values):
        result = hub.ingest(
            unnormalized_event(
                event_id=event_id,
                sequence=seq,
                source="dup-source",
                received_monotonic_ns=time.monotonic_ns() + index,
            )
        )
        if result is not None:
            published_count += 1
    assert published_count == 1
    assert hub.metrics.duplicate == len(values) - 1
    assert [event.event_id for event in hub.published if event.source == "dup-source"] == [event_id]
