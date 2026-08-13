"""Parquet schemas and row conversions for recorded events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from session_recorder.constants import BIOSIGNAL_EVENT_TYPE

EVENT_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string()),
        pa.field("event_id", pa.string()),
        pa.field("event_type", pa.string()),
        pa.field("source", pa.string()),
        pa.field("modality", pa.string()),
        pa.field("session_id", pa.string()),
        pa.field("trial_id", pa.string()),
        pa.field("sequence", pa.int64()),
        pa.field("source_time_ns", pa.int64()),
        pa.field("received_monotonic_ns", pa.int64()),
        pa.field("normalized_time_ns", pa.int64()),
        pa.field("quality", pa.float64()),
        pa.field("producer_version", pa.string()),
        pa.field("payload_json", pa.string()),
    ]
)

BIOSIGNAL_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string()),
        pa.field("source", pa.string()),
        pa.field("modality", pa.string()),
        pa.field("sample_rate_hz", pa.float64()),
        pa.field("channel_names_json", pa.string()),
        pa.field("sample_count", pa.int64()),
        pa.field("n_channels", pa.int64()),
        pa.field("units", pa.string()),
        pa.field("filters_applied_json", pa.string()),
        pa.field("packet_loss_count", pa.int64()),
        pa.field("clock_confidence", pa.float64()),
        pa.field("estimated_first_sample_ns", pa.int64()),
        pa.field("normalized_time_ns", pa.int64()),
        pa.field("samples_f32", pa.binary()),
    ]
)


def atomic_write_parquet(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)


def concat_parquet(
    parts: list[Path],
    rows: list[dict[str, Any]],
    schema: pa.Schema,
    dest: Path,
) -> pa.Table:
    tables: list[pa.Table] = []
    for part in parts:
        if part.is_file():
            tables.append(pq.read_table(part))
    if rows:
        tables.append(pa.Table.from_pylist(rows, schema=schema))
    if tables:
        table = pa.concat_tables(tables, promote_options="default")
    else:
        table = schema.empty_table()
    atomic_write_parquet(dest, table)
    return table


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def strip_biosignal_samples(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return event row payload without dense samples, plus an optional chunk row."""
    event_type = str(event.get("event_type", ""))
    payload = dict(event.get("payload") or {})
    if event_type != BIOSIGNAL_EVENT_TYPE:
        return payload, None
    samples = payload.pop("samples", None)
    payload["samples_ref"] = event.get("event_id")
    if samples is None:
        return payload, None
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim != 2:
        array = array.reshape(len(samples), -1)
    chunk = {
        "event_id": event.get("event_id"),
        "source": event.get("source"),
        "modality": event.get("modality"),
        "sample_rate_hz": float(payload.get("sample_rate_hz") or 0.0),
        "channel_names_json": _json_dumps(payload.get("channel_names") or []),
        "sample_count": int(payload.get("sample_count") or array.shape[-1]),
        "n_channels": int(array.shape[0]),
        "units": payload.get("units") or "microvolts",
        "filters_applied_json": _json_dumps(payload.get("filters_applied") or []),
        "packet_loss_count": int(payload.get("packet_loss_count") or 0),
        "clock_confidence": float(payload.get("clock_confidence") or 1.0),
        "estimated_first_sample_ns": payload.get("estimated_first_sample_ns"),
        "normalized_time_ns": event.get("normalized_time_ns"),
        "samples_f32": array.tobytes(order="C"),
    }
    return payload, chunk


def event_to_row(event: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": event.get("schema_version"),
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "source": event.get("source"),
        "modality": event.get("modality"),
        "session_id": event.get("session_id"),
        "trial_id": event.get("trial_id"),
        "sequence": event.get("sequence"),
        "source_time_ns": event.get("source_time_ns"),
        "received_monotonic_ns": event.get("received_monotonic_ns"),
        "normalized_time_ns": event.get("normalized_time_ns"),
        "quality": event.get("quality"),
        "producer_version": event.get("producer_version"),
        "payload_json": _json_dumps(payload),
    }


def row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    payload_raw = row.get("payload_json") or "{}"
    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw)
    return {
        "schema_version": row.get("schema_version"),
        "event_id": row.get("event_id"),
        "event_type": row.get("event_type"),
        "source": row.get("source"),
        "modality": row.get("modality"),
        "session_id": row.get("session_id"),
        "trial_id": row.get("trial_id"),
        "sequence": int(row["sequence"]) if row.get("sequence") is not None else 0,
        "source_time_ns": _maybe_int(row.get("source_time_ns")),
        "received_monotonic_ns": _maybe_int(row.get("received_monotonic_ns")) or 0,
        "normalized_time_ns": _maybe_int(row.get("normalized_time_ns")),
        "quality": float(row["quality"]) if row.get("quality") is not None else 1.0,
        "producer_version": row.get("producer_version"),
        "payload": payload,
    }


def _maybe_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def load_events_parquet(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        import polars as pl

        frame = pl.read_parquet(path)
        rows = frame.to_dicts()
    except ImportError:
        rows = pq.read_table(path).to_pylist()
    return [row_to_event(row) for row in rows]


def load_biosignal_chunks(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    table = pq.read_table(path)
    chunks: dict[str, dict[str, Any]] = {}
    for row in table.to_pylist():
        event_id = row.get("event_id")
        if not event_id:
            continue
        chunks[event_id] = row
    return chunks


def reattach_samples(event: dict[str, Any], chunk: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(event.get("payload") or {})
    payload.pop("samples_ref", None)
    if chunk is None:
        event["payload"] = payload
        return event
    blob = chunk.get("samples_f32") or b""
    n_channels = int(chunk.get("n_channels") or 0)
    sample_count = int(chunk.get("sample_count") or 0)
    if blob and n_channels and sample_count:
        array = np.frombuffer(blob, dtype=np.float32)
        payload["samples"] = array.reshape(n_channels, sample_count).tolist()
    event["payload"] = payload
    return event
