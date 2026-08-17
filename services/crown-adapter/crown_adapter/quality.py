from __future__ import annotations

from dataclasses import dataclass

CROWN_CHANNELS = ("CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4")


@dataclass(frozen=True)
class QualityResult:
    score: float
    packet_quality: float
    channel_validity: float
    motion_penalty: float
    flags: list[str]
    invalid_channels: list[str]


def _clamp01(value: float) -> float:
    if value != value or value == float("inf") or value == float("-inf"):
        return 0.0
    return min(1.0, max(0.0, value))


def channel_has_non_finite(channel: list[float]) -> bool:
    return any(value != value or value in (float("inf"), float("-inf")) for value in channel)


def channel_is_flat(channel: list[float], epsilon: float = 1e-9) -> bool:
    if len(channel) < 2:
        return True
    return max(channel) - min(channel) <= epsilon


def clip_ratio(channel: list[float], clip_abs: float = 200.0) -> float:
    if not channel:
        return 0.0
    clipped = sum(1 for value in channel if abs(value) >= clip_abs)
    return clipped / len(channel)


def sanitize_samples(samples: list[list[float]]) -> tuple[list[list[float]], list[int]]:
    invalid: list[int] = []
    cleaned: list[list[float]] = []
    for index, channel in enumerate(samples):
        invalid_ch = False
        next_ch: list[float] = []
        for value in channel:
            if value != value or value in (float("inf"), float("-inf")):
                invalid_ch = True
                next_ch.append(0.0)
            else:
                next_ch.append(float(value))
        if invalid_ch:
            invalid.append(index)
        cleaned.append(next_ch)
    return cleaned, invalid


def score_quality(
    *,
    samples: list[list[float]],
    packet_loss_count: int,
    chunks_since_loss: int,
    motion_magnitude: float,
    motion_artifact_threshold: float,
) -> QualityResult:
    flags: list[str] = []
    invalid_names: list[str] = []
    channel_count = len(samples) or 1
    valid_channels = 0
    for index, channel in enumerate(samples):
        name = CROWN_CHANNELS[index] if index < len(CROWN_CHANNELS) else f"ch{index}"
        if channel_has_non_finite(channel):
            invalid_names.append(name)
            flags.append(f"non_finite:{name}")
            continue
        if channel_is_flat(channel):
            flags.append(f"flat:{name}")
            continue
        if clip_ratio(channel) > 0.05:
            flags.append(f"clipping:{name}")
        valid_channels += 1

    channel_validity = _clamp01(valid_channels / channel_count)
    if packet_loss_count <= 0:
        loss_ratio = 0.0
    else:
        loss_ratio = packet_loss_count / (packet_loss_count + max(1, chunks_since_loss))
    extra = 0.2 if packet_loss_count > 0 and chunks_since_loss == 0 else 0.0
    packet_quality = _clamp01(1.0 - min(1.0, loss_ratio * 4.0 + extra))
    over = max(0.0, motion_magnitude - motion_artifact_threshold)
    motion_penalty = _clamp01(1.0 / (1.0 + 2.5 * over))
    if over > 0:
        flags.append("motion_artifact")
    if packet_loss_count > 0:
        flags.append("packet_loss")
    score = _clamp01(packet_quality * channel_validity * motion_penalty)
    return QualityResult(
        score=score,
        packet_quality=packet_quality,
        channel_validity=channel_validity,
        motion_penalty=motion_penalty,
        flags=flags,
        invalid_channels=invalid_names,
    )


def device_ms_to_ns(device_ms: float) -> int:
    if device_ms != device_ms or device_ms in (float("inf"), float("-inf")):
        raise ValueError("device time must be finite")
    return int(device_ms) * 1_000_000


def sample_index_to_device_ms(sample_index: int, sample_rate_hz: int) -> int:
    return int((sample_index * 1000) / sample_rate_hz)
