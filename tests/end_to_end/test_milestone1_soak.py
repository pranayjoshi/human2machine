"""Milestone 1 soak: concurrent Crown + Ganglion recording in fast/CI mode.

Acquisition and record only. Fusion and safety are not required and must not run.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from soak_biosignals import HARDWARE_MESSAGE, main, run_soak  # noqa: E402

TWENTY_MIN_NS = 20 * 60 * 1_000_000_000


def test_fast_soak_covers_twenty_minute_timeline(tmp_path: Path) -> None:
    started = time.perf_counter()
    report = run_soak(minutes=20, fast=True, sessions_dir=tmp_path, seed=7)
    elapsed = time.perf_counter() - started

    assert report.ok, report.to_dict()
    assert not report.hub_failed
    assert report.invalid_events == 0
    assert report.sequence_gaps > 0
    assert report.timestamp_gaps > 0
    assert report.packet_loss_visible
    assert report.packet_loss_count > 0
    assert report.eeg_chunks > 0
    assert report.emg_chunks > 0
    assert report.session_finalized
    assert report.session_id
    assert report.duration_ns >= TWENTY_MIN_NS - 62_500_000
    assert report.timeline_span_ns >= TWENTY_MIN_NS - 62_500_000
    assert elapsed < 45.0
    assert report.wall_time_s < 45.0

    assert report.acquisition_only
    assert report.fusion_required is False
    assert report.safety_required is False
    assert report.control_events == 0

    if report.eeg_features:
        assert report.eeg_shadow_only is True
    if report.emg_features:
        assert report.emg_shadow_only is True

    manifest_path = next(tmp_path.glob("session_*/manifest.json"), None)
    assert manifest_path is not None
    manifest = json.loads(manifest_path.read_text())
    assert manifest.get("finalization_status") == "finalized"
    assert int(manifest.get("packet_loss_summary", {}).get("total_packet_loss_count") or 0) > 0


def test_hardware_flag_does_not_fake_devices(capsys) -> None:
    code = main(["--hardware"])
    captured = capsys.readouterr()
    assert code == 0
    assert "just run-hardware --confirm" in captured.out
    assert HARDWARE_MESSAGE.strip() in captured.out
    assert "not simulated" in captured.out
