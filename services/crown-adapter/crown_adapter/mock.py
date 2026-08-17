from __future__ import annotations

import math
import random
import time

from intent_contracts.envelope import EventEnvelope

from crown_adapter.events import device_status, heartbeat, make_event
from crown_adapter.quality import (
    CROWN_CHANNELS,
    device_ms_to_ns,
    sample_index_to_device_ms,
    sanitize_samples,
    score_quality,
)

SAMPLE_RATE_HZ = 256
CHANNELS = 8
SAMPLES_PER_CHUNK = 16
MOTION_AXES = ("x", "y", "z")


class CrownMockRuntime:
    def __init__(
        self,
        *,
        seed: int = 7,
        motion: bool = False,
        packet_loss: float = 0.0,
        noise_std: float = 8.0,
        alpha_uv: float = 12.0,
        motion_artifact_threshold: float = 0.8,
        shadow_only: bool = True,
    ) -> None:
        self.rng = random.Random(seed)
        self.motion = motion
        self.packet_loss = packet_loss
        self.noise_std = noise_std
        self.alpha_uv = alpha_uv
        self.motion_artifact_threshold = motion_artifact_threshold
        self.shadow_only = shadow_only
        self.sample_index = 0
        self.sequence = 0
        self.packet_loss_count = 0
        self.chunks_emitted = 0
        self._started = time.monotonic()
        self._last_data = time.monotonic()

    def tick(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        if self.sequence == 0:
            events.append(device_status(self.sequence, "healthy", "mock stream started"))
            self.sequence += 1
        if self.packet_loss > 0 and self.rng.random() < self.packet_loss:
            self.packet_loss_count += 1
            self.sample_index += SAMPLES_PER_CHUNK
            return events

        device_ms = sample_index_to_device_ms(self.sample_index, SAMPLE_RATE_HZ)
        source_time_ns = device_ms_to_ns(device_ms)
        samples, invalid = sanitize_samples(self._synthesize_eeg())
        motion = self._synthesize_motion()
        quality = score_quality(
            samples=samples,
            packet_loss_count=self.packet_loss_count,
            chunks_since_loss=self.chunks_emitted,
            motion_magnitude=motion["magnitude"],
            motion_artifact_threshold=self.motion_artifact_threshold,
        )
        if invalid:
            quality.flags.append("sanitized_non_finite")

        events.append(
            make_event(
                event_type="biosignal.chunk",
                sequence=self.sequence,
                source_time_ns=source_time_ns,
                quality=quality.score,
                payload={
                    "sample_rate_hz": SAMPLE_RATE_HZ,
                    "channel_names": list(CROWN_CHANNELS),
                    "sample_count": SAMPLES_PER_CHUNK,
                    "samples": samples,
                    "units": "microvolts",
                    "filters_applied": ["crown_raw_filtered"],
                    "packet_loss_count": self.packet_loss_count,
                    "clock_confidence": 1,
                    "estimated_first_sample_ns": source_time_ns,
                },
            )
        )
        self.sequence += 1
        events.append(
            make_event(
                event_type="motion.chunk",
                modality="imu",
                sequence=self.sequence,
                source_time_ns=source_time_ns,
                quality=quality.score,
                payload={
                    "sample_rate_hz": SAMPLE_RATE_HZ / SAMPLES_PER_CHUNK,
                    "axes": list(MOTION_AXES),
                    "sample_count": 1,
                    "samples": motion["samples"],
                    "units": "g",
                    "magnitude": motion["magnitude"],
                },
            )
        )
        self.sequence += 1
        events.append(
            make_event(
                event_type="data.quality",
                sequence=self.sequence,
                source_time_ns=source_time_ns,
                quality=quality.score,
                payload={
                    "score": quality.score,
                    "components": {
                        "packet_quality": quality.packet_quality,
                        "channel_validity": quality.channel_validity,
                        "motion_penalty": quality.motion_penalty,
                    },
                    "flags": quality.flags,
                },
            )
        )
        self.sequence += 1
        if self.chunks_emitted > 0 and self.chunks_emitted % 16 == 0:
            events.append(self._shadow_feature(source_time_ns, quality.score, motion["magnitude"]))
        self.sample_index += SAMPLES_PER_CHUNK
        self.chunks_emitted += 1
        self._last_data = time.monotonic()
        return events

    def heartbeat_event(self, dropped: int) -> EventEnvelope:
        event = heartbeat(
            self.sequence,
            time.monotonic() - self._started,
            (time.monotonic() - self._last_data) * 1000.0,
            dropped,
            "degraded" if dropped > 0 else "healthy",
        )
        self.sequence += 1
        return event

    def shutdown_event(self) -> EventEnvelope:
        event = device_status(self.sequence, "offline", "adapter stopping")
        self.sequence += 1
        return event

    def simulate_disconnect(self) -> list[EventEnvelope]:
        events = [
            device_status(self.sequence, "degraded", "mock disconnect"),
        ]
        self.sequence += 1
        events.append(device_status(self.sequence, "offline", "mock stream interrupted"))
        self.sequence += 1
        self.sample_index = 0
        self.chunks_emitted = 0
        self.sequence += 1
        events.append(device_status(self.sequence, "healthy", "mock stream resumed"))
        self.sequence += 1
        return events

    def _shadow_feature(
        self, source_time_ns: int, quality: float, magnitude: float
    ) -> EventEnvelope:
        artifact = magnitude > self.motion_artifact_threshold
        event = make_event(
            event_type="modality.feature",
            sequence=self.sequence,
            source_time_ns=source_time_ns,
            quality=quality,
            payload={
                "feature_name": "eeg_shadow",
                "window_start_ns": source_time_ns,
                "window_end_ns": source_time_ns + device_ms_to_ns(62),
                "label": "artifact" if artifact else "ok",
                "confidence": quality,
                "candidate_scores": {
                    "ok": max(0.0, 1.0 - quality) if artifact else quality,
                    "artifact": quality if artifact else max(0.0, 1.0 - quality),
                },
                "model_id": "crown-shadow-v0",
                "shadow_only": self.shadow_only,
            },
        )
        self.sequence += 1
        return event

    def _synthesize_eeg(self) -> list[list[float]]:
        samples = [[0.0] * SAMPLES_PER_CHUNK for _ in range(CHANNELS)]
        for n in range(SAMPLES_PER_CHUNK):
            t = (self.sample_index + n) / SAMPLE_RATE_HZ
            alpha = math.sin(2 * math.pi * 10 * t) * self.alpha_uv
            motion_bleed = (
                math.sin(2 * math.pi * 1.2 * t) * 40 + self.rng.gauss(0, 1) * 15
                if self.motion
                else 0.0
            )
            for ch in range(CHANNELS):
                posterior = alpha if ch in {3, 4} else alpha * 0.25
                samples[ch][n] = posterior + self.rng.gauss(0, 1) * self.noise_std + motion_bleed
        return samples

    def _synthesize_motion(self) -> dict[str, object]:
        base = 1.4 + abs(self.rng.gauss(0, 1)) * 0.6 if self.motion else 0.05
        x = base * (0.4 + self.rng.random()) if self.motion else self.rng.gauss(0, 1) * 0.02
        y = base * (0.3 + self.rng.random()) if self.motion else self.rng.gauss(0, 1) * 0.02
        z = 1 + self.rng.gauss(0, 1) * (0.2 if self.motion else 0.01)
        magnitude = math.sqrt(x * x + y * y + z * z)
        return {"samples": [[x], [y], [z]], "magnitude": magnitude}
