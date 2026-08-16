from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from intent_contracts.envelope import EventEnvelope
from numpy.typing import NDArray

from ganglion_adapter.acquisition import CHANNEL_NAMES, MockAcquisition
from ganglion_adapter.events import heartbeat, make_event
from ganglion_adapter.features import WindowBuffer
from ganglion_adapter.filters import CausalEmgFilter
from ganglion_adapter.live_inference import LiveSmoother, classify_by_rms


def score_emg_quality(
    samples: NDArray[np.floating], packet_loss_count: int
) -> tuple[float, dict[str, float], list[str]]:
    flags: list[str] = []
    n_channels = samples.shape[0]
    valid = 0
    for i, channel in enumerate(samples):
        if not np.isfinite(channel).all():
            flags.append(f"non_finite:ch{i}")
            continue
        if float(np.max(channel) - np.min(channel)) < 1e-6:
            flags.append(f"flat:ch{i}")
            continue
        if float(np.mean(np.abs(channel) > 400.0)) > 0.05:
            flags.append(f"clipping:ch{i}")
        valid += 1
    channel_validity = valid / max(n_channels, 1)
    packet_quality = 1.0 / (1.0 + 0.15 * packet_loss_count)
    if packet_loss_count:
        flags.append("packet_loss")
    score = max(0.0, min(1.0, channel_validity * packet_quality))
    return score, {"channel_validity": channel_validity, "packet_quality": packet_quality}, flags


@dataclass
class GanglionMockRuntime:
    seed: int = 7
    sample_rate_hz: float = 200.0
    chunk_ms: float = 80.0
    window_ms: float = 250.0
    hop_ms: float = 50.0
    dwell_ms: float = 200.0
    hysteresis: float = 0.12
    refractory_ms: float = 400.0
    confidence_threshold: float = 0.7
    snr_db: float = 12.0
    packet_loss: float = 0.0
    device_alias: str = "ganglion-mock"
    capture_mode: str = "usb_dongle_mock"
    model_id: str = "emg-mock-rms-v0"
    shadow_only: bool = True
    acquisition: object | None = None

    sequence: int = 0
    started_ns: int = 0
    last_data_age_ms: float = 0.0
    _acq: Any = field(init=False)
    _filters: CausalEmgFilter = field(init=False)
    _windows: WindowBuffer = field(init=False)
    _smoother: LiveSmoother = field(init=False)
    _started: bool = False

    def __post_init__(self) -> None:
        if self.acquisition is None:
            self._acq = MockAcquisition(
                sample_rate_hz=self.sample_rate_hz,
                chunk_ms=self.chunk_ms,
                seed=self.seed,
                snr_db=self.snr_db,
                packet_loss=self.packet_loss,
            )
        else:
            self._acq = self.acquisition
            rate = getattr(self._acq, "sample_rate_hz", None)
            if rate:
                self.sample_rate_hz = float(rate)
        self._filters = CausalEmgFilter(sample_rate_hz=self.sample_rate_hz)
        window_samples = int(round(self.sample_rate_hz * self.window_ms / 1000.0))
        hop_samples = int(round(self.sample_rate_hz * self.hop_ms / 1000.0))
        self._windows = WindowBuffer(window_samples, hop_samples)
        self._smoother = LiveSmoother(
            dwell_ms=self.dwell_ms,
            hysteresis=self.hysteresis,
            refractory_ms=self.refractory_ms,
            confidence_threshold=self.confidence_threshold,
        )

    def set_disconnected(self, disconnected: bool) -> None:
        was = self._acq.disconnected
        self._acq.set_disconnected(disconnected)
        if disconnected and not was:
            self._smoother.reset()
            self._windows.reset()
            self._filters.reset()

    def tick(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        if not self._started:
            events.append(
                make_event(
                    event_type="device.status",
                    sequence=self._next_seq(),
                    payload={
                        "status": "healthy",
                        "device_alias": self.device_alias,
                        "detail": "mock stream started"
                        if "mock" in self.device_alias
                        else "ganglion stream started",
                        "battery_percent": 100.0,
                        "metadata": {"mode": self.capture_mode},
                    },
                )
            )
            self._started = True

        if self._acq.disconnected:
            events.append(
                make_event(
                    event_type="device.status",
                    sequence=self._next_seq(),
                    payload={
                        "status": "offline",
                        "device_alias": self.device_alias,
                        "detail": "disconnected",
                        "metadata": {},
                    },
                    quality=0.0,
                )
            )
            return events

        chunk = self._acq.next_chunk()
        if chunk is None:
            return events
        raw, first_ns, _label = chunk
        receive_ns = getattr(self._acq, "last_receive_ns", None)
        filtered = self._filters.process(raw)
        quality, components, flags = score_emg_quality(raw, self._acq.packet_loss_count)
        self.last_data_age_ms = 0.0
        events.append(
            make_event(
                event_type="biosignal.chunk",
                sequence=self._next_seq(),
                source_time_ns=first_ns,
                quality=quality,
                received_monotonic_ns=receive_ns,
                payload={
                    "sample_rate_hz": self.sample_rate_hz,
                    "channel_names": CHANNEL_NAMES,
                    "sample_count": int(raw.shape[1]),
                    "samples": raw.tolist(),
                    "units": "microvolts",
                    "filters_applied": [],
                    "packet_loss_count": self._acq.packet_loss_count,
                    "clock_confidence": 1.0,
                    "estimated_first_sample_ns": first_ns,
                },
            )
        )
        windows = self._windows.push(filtered, first_ns, self.sample_rate_hz)
        for window in windows:
            raw_label, scores = classify_by_rms(window.features)
            if quality < 0.4:
                raw_label, scores = (
                    "unknown",
                    {
                        "unknown": 1.0,
                        "rest": 0.0,
                        "confirm": 0.0,
                        "cancel": 0.0,
                    },
                )
            label, confidence = self._smoother.update(raw_label, scores, quality, window.end_ns)
            events.append(
                make_event(
                    event_type="modality.feature",
                    sequence=self._next_seq(),
                    source_time_ns=window.end_ns,
                    quality=quality,
                    payload={
                        "feature_name": "emg_gesture",
                        "window_start_ns": window.start_ns,
                        "window_end_ns": window.end_ns,
                        "label": label,
                        "confidence": confidence,
                        "candidate_scores": {
                            key: scores.get(key, 0.0)
                            for key in ("rest", "confirm", "cancel", "unknown")
                        },
                        "model_id": self.model_id,
                        "shadow_only": self.shadow_only,
                    },
                )
            )
        events.append(
            make_event(
                event_type="data.quality",
                sequence=self._next_seq(),
                source_time_ns=first_ns,
                quality=quality,
                payload={"score": quality, "components": components, "flags": flags},
            )
        )
        _ = filtered
        return events

    def heartbeat_event(self, uptime_seconds: float, dropped: int) -> EventEnvelope:
        status = "degraded" if dropped else "healthy"
        if self._acq.disconnected:
            status = "offline"
        return heartbeat(self._next_seq(), uptime_seconds, self.last_data_age_ms, dropped, status)

    def shutdown_event(self) -> EventEnvelope:
        return make_event(
            event_type="device.status",
            sequence=self._next_seq(),
            payload={
                "status": "offline",
                "device_alias": self.device_alias,
                "detail": "adapter stopping",
                "metadata": {},
            },
        )

    def _next_seq(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value
